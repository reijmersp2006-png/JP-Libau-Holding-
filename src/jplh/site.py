"""Het HQ-dashboard: zet de stand van alle afdelingen in ``state.json`` naast de game-pagina.

Het dashboard is een statische site (HTML + JSON). Het kan dus gratis op GitHub Pages
staan, of lokaal met ``jplh dashboard``. Het dashboard leest alleen; het kan niets aan de
bot veranderen.
"""

from __future__ import annotations

import json
import math
import shutil
from datetime import UTC, datetime, timedelta
from importlib import resources
from pathlib import Path

from jplh.config import HoldingConfig
from jplh.jarvis import briefing, health
from jplh.desks import DESK_ORDER, Desk, benchmark_equity
from jplh.prices import PriceError
from jplh.research import track_record
from jplh.scouts import recent as recent_alerts
from jplh.store import Store

DESK_INFO = {
    "crypto": {"name": "Crypto Lab", "team": "Crypto"},
    "meme": {"name": "Meme Arcade", "team": "Memecoins"},
    "stocks": {"name": "Beurstoren", "team": "Aandelen"},
    "metals": {"name": "De Kluis", "team": "Goud en zilver"},
    "fx": {"name": "Wisselhaven", "team": "Valuta"},
}


def _downsample(points: list, n: int = 400) -> list:
    if len(points) <= n:
        return points
    step = len(points) / n
    return [points[int(i * step)] for i in range(n - 1)] + [points[-1]]


def _level(xp: int) -> int:
    return 1 + int(math.sqrt(max(xp, 0) / 20))


def desk_state(desk: Desk, now: datetime, max_age: timedelta) -> dict:
    h = desk.holding
    prices = h.prices(now)
    equity = h.portfolio.equity_eur(prices)
    cap0 = desk.config.start_capital_eur
    cap = cap0 + desk.meta.get("transfers_eur", 0.0)   # overboekingen tussen afdelingen tellen niet als winst
    bench = benchmark_equity(desk, now)
    if bench is not None and cap0:
        bench *= cap / cap0
    fills = h.store.fills()
    events = h.store.events(limit=200)
    decisions = [p for _, k, p in events if k == "decision"]
    positions = []
    for sym, pos in h.portfolio.positions.items():
        try:
            px = prices.price_eur(sym)
        except PriceError:
            px = pos.avg_price_eur
        positions.append({"symbol": sym, "quantity": pos.quantity, "avg_eur": pos.avg_price_eur,
                          "value_eur": pos.quantity * px, "pnl_pct": px / pos.avg_price_eur - 1,
                          "strategy": desk.selection().get(sym, "")})
    instruments = []
    fresh = 0
    for inst in desk.instruments:
        ts = prices.ts(inst.symbol)
        try:
            px = prices.price_eur(inst.symbol)
        except PriceError:
            px = None
        is_fresh = ts is not None and now - ts <= max_age
        fresh += is_fresh
        day_ago = h.market.candles(inst.symbol, "1h", known_at=now, limit=25)
        change = (day_ago[-1].close / day_ago[0].close - 1) if len(day_ago) >= 2 else None
        instruments.append({"symbol": inst.symbol, "price_eur": px, "change_24h": change, "fresh": is_fresh,
                            "strategy": desk.selection().get(inst.symbol, "nog geen keuze"),
                            "in_market": inst.symbol in h.portfolio.positions})
    paused = h.meta.get("paused_reason")
    if paused:
        status = "alarm"
    elif fresh == 0:
        status = "gesloten"
    elif positions:
        status = "aan het werk"
    else:
        status = "wacht af"
    started = h.meta.get("started_at")
    days = (now - datetime.fromisoformat(started)).days if started else 0
    approved = sum(1 for d in decisions if d.get("approved"))
    xp = 10 * len(fills) + 2 * approved + len(decisions) - approved + 5 * days
    curve = [[t.isoformat(), round(e, 2)] for t, e in h.store.equity_curve()]
    return {
        "id": desk.cls, **DESK_INFO[desk.cls],
        "capital_eur": cap, "equity_eur": equity, "cash_eur": h.portfolio.cash_eur,
        # Procent t.o.v. het grootste bedrag dat erin zat, zodat afgeven of krijgen het niet opblaast.
        "pnl_eur": equity - cap, "pnl_pct": (equity - cap) / max(cap, cap0) if cap else 0.0,
        "benchmark_eur": bench, "peak_eur": h.meta.get("peak_equity", cap),
        "drawdown": 1 - equity / h.meta["peak_equity"] if h.meta.get("peak_equity") else 0.0,
        "fees_eur": h.portfolio.fees_eur, "trades": len(fills), "status": status, "paused_reason": paused,
        "xp": xp, "level": _level(xp), "days_active": days,
        "positions": positions, "instruments": instruments,
        "selected_at": h.meta.get("selected_at"),
        "mode": desk.mode, "weather": desk.regime(now)[1] if desk.mode != "vasthouden" else "",
        "equity_curve": _downsample(curve),
    }


def _missions(total: dict, desks: list[dict], days: int, ever_paused: bool) -> list[dict]:
    trades = sum(d["trades"] for d in desks)
    beat = total["benchmark_eur"] is not None and total["equity_eur"] > total["benchmark_eur"]
    return [
        {"id": "first", "title": "Eerste paper trade", "progress": min(trades, 1), "goal": 1},
        {"id": "fifty", "title": "50 paper trades", "progress": min(trades, 50), "goal": 50},
        {"id": "discipline", "title": "30 dagen binnen de risicogrenzen",
         "progress": 0 if ever_paused else min(days, 30), "goal": 30},
        {"id": "beat", "title": "Na 30 dagen beter dan koop-en-houd",
         "progress": 1 if (beat and days >= 30) else 0, "goal": 1,
         "hint": "nu " + ("voor" if beat else "achter") + " op koop-en-houd"},
        {"id": "demo", "title": "Demofase: 90 dagen", "progress": min(days, 90), "goal": 90},
        {"id": "live", "title": "Klaar voor live", "progress": 0, "goal": 1, "locked": True,
         "hint": "alleen Phil kan dit vrijgeven"},
    ]


def lab_state(config: HoldingConfig, desks: dict[str, Desk], market: Store, now: datetime,
              alerts: list[dict]) -> dict:
    """Alles voor het Onderzoekslab: terugblikken, rapportcijfers, weekrapporten en verkenners."""
    reflections, records, reports, adjust = [], [], [], {}
    for c in DESK_ORDER:
        if c not in desks:
            continue
        refl = desks[c].reflections()
        reflections += [{"desk": c, **r} for r in refl]
        for label, t in track_record(refl).items():
            records.append({"desk": c, "strategy": label, **{k: t[k] for k in
                            ("trades", "hit_rate", "avg_pnl", "avg_edge")}})
        last = desks[c].holding.store.events(kind="weekreport", limit=1)
        if last:
            reports.append({"desk": c, "ts": last[0][0].isoformat(), **last[0][2]})
        for label, a in (desks[c].meta.get("adjustments") or {}).items():
            adjust[f"{c}:{label}"] = a
    reflections.sort(key=lambda r: r["exit_ts"], reverse=True)
    wins = sum(1 for r in reflections if r["pnl_pct"] > 0)
    watch = []
    for w in config.watch:
        day = market.candles(w.symbol, "1h", known_at=now, limit=25)
        if not day:
            continue
        fresh = now - day[-1].ts <= timedelta(hours=config.risk.max_data_age_hours)
        watch.append({"symbol": w.symbol, "name": w.name, "kind": w.kind, "price": day[-1].close,
                      "change_24h": day[-1].close / day[0].close - 1 if len(day) >= 2 else None, "fresh": fresh})
    return {
        "reviewed": len(reflections), "wins": wins,
        "hit_rate": wins / len(reflections) if reflections else None,
        "avg_edge": sum(r["edge_vs_hold"] for r in reflections) / len(reflections) if reflections else None,
        "reflections": reflections[:25], "records": sorted(records, key=lambda r: -r["trades"])[:20],
        "reports": reports, "adjustments": adjust, "alerts": alerts, "watch": watch,
    }


TICKER_NAMES = {"BTC-EUR": "Bitcoin", "ETH-EUR": "Ether", "SOL-EUR": "Solana", "XRP-EUR": "XRP", "DOGE-EUR": "Dogecoin",
                "SHIB-EUR": "Shiba", "PEPE-EUR": "Pepe", "IWDA.AS": "Wereldindex", "ASML.AS": "ASML", "AAPL": "Apple",
                "MSFT": "Microsoft", "NVDA": "Nvidia", "GC=F": "Goud", "SI=F": "Zilver", "EURUSD=X": "EUR/USD",
                "EURGBP=X": "EUR/GBP", "EURJPY=X": "EUR/JPY", "EURCHF=X": "EUR/CHF"}


def ticker(config: HoldingConfig, market: Store, now: datetime) -> list[dict]:
    """De koersband: laatste koers, verandering over 24 uur en een mini-lijntje per instrument."""
    out = []
    for inst in config.instruments:
        cs = market.candles(inst.symbol, "1h", known_at=now, limit=25)
        if len(cs) < 2:
            continue
        last, first = cs[-1].close, cs[0].close
        out.append({"symbol": inst.symbol, "name": TICKER_NAMES.get(inst.symbol, inst.symbol), "desk": inst.asset_class.value,
                    "price": last, "currency": inst.currency, "change": last / first - 1 if first else None,
                    "fresh": (now - cs[-1].ts) <= timedelta(hours=3), "line": [round(c.close, 8) for c in cs]})
    return out


def build_state(config: HoldingConfig, desks: dict[str, Desk], market: Store, home: Path,
                now: datetime | None = None, demo: bool = False, problems: list[str] | None = None) -> dict:
    now = now or datetime.now(tz=UTC)
    max_age = timedelta(hours=config.risk.max_data_age_hours)
    states = [desk_state(desks[c], now, max_age) for c in DESK_ORDER if c in desks]
    cap = sum(d["capital_eur"] for d in states)
    equity = sum(d["equity_eur"] for d in states)
    bench_parts = [d["benchmark_eur"] for d in states if d["benchmark_eur"] is not None]
    bench = sum(bench_parts) + sum(d["capital_eur"] for d in states if d["benchmark_eur"] is None) if bench_parts else None

    # Totale vermogenscurve: alle afdelingen worden per ronde op hetzelfde moment gewaardeerd.
    # Draaien er twee rondes in hetzelfde uur, dan telt per afdeling alleen de laatste mee
    # (anders telt het totaal dubbel en lijkt er een top van duizenden euro's te zijn geweest).
    total_curve: dict[str, float] = {}
    for c in DESK_ORDER:
        if c in desks:
            per_hour = {t.replace(minute=0, second=0, microsecond=0).isoformat(): e
                        for t, e in desks[c].holding.store.equity_curve()}
            for key, e in per_hour.items():
                total_curve[key] = total_curve.get(key, 0.0) + e
    curve = sorted(total_curve.items())
    full = [[t, round(e, 2)] for t, e in curve]
    peak = max([e for _, e in full] + [cap])
    day_ago = (now - timedelta(hours=24)).isoformat()
    past = [e for t, e in full if t <= day_ago]
    day_start = past[-1] if past else cap

    feed = []
    for c in DESK_ORDER:
        if c not in desks:
            continue
        for ts, kind, p in desks[c].holding.store.events(limit=60):
            if kind == "decision":
                verb = "koopt" if p["side"] == "buy" else "verkoopt"
                text = f"{p['instrument']}: {verb}" if p["approved"] else f"{p['instrument']}: {verb} NIET"
                why = p.get("signal_reason", "")
                feed.append({"ts": ts.isoformat(), "desk": c, "kind": "trade" if p["approved"] else "refused",
                             "text": text, "why": why,
                             "detail": (why + ". " if why else "") + "Risico: " + p["reason"],
                             "strategy": p.get("strategy", "")})
            elif kind == "reflection":
                feed.append({"ts": ts.isoformat(), "desk": c, "kind": "reflection",
                             "text": f"terugblik {p['instrument']}: {p['verdict']}", "detail": p["reason"],
                             "strategy": p.get("strategy", "")})
            elif kind == "weekreport":
                feed.append({"ts": ts.isoformat(), "desk": c, "kind": "weekreport", "text": p["reason"],
                             "detail": ""})
            elif kind in ("selection", "pause", "resume"):
                feed.append({"ts": ts.isoformat(), "desk": c, "kind": kind, "text": p.get("reason", kind),
                             "detail": ""})
    alerts = recent_alerts(market, 40)
    for a in alerts[:15]:
        feed.append({"ts": a["ts"], "desk": "scouts", "kind": "alert", "text": a["text"], "detail": "",
                     "level": a["level"]})
    feed.sort(key=lambda f: f["ts"], reverse=True)

    started = [d["days_active"] for d in states]
    days = max(started) if started else 0
    ever_paused = any(d["paused_reason"] for d in states) or any(f["kind"] == "pause" for f in feed)
    total = {"capital_eur": cap, "equity_eur": equity, "pnl_eur": equity - cap,
             "pnl_pct": equity / cap - 1 if cap else 0.0, "benchmark_eur": bench,
             "peak_eur": peak, "drawdown": 1 - equity / peak if peak else 0.0,
             "day_pnl_pct": equity / day_start - 1 if day_start else 0.0, "equity_curve": _downsample(full)}
    radar = market.db.execute(
        "SELECT base_symbol, chain, price_usd, liquidity_usd, volume_24h_usd, change_24h_pct, flags FROM radar "
        "WHERE fetched_at = (SELECT MAX(fetched_at) FROM radar) ORDER BY volume_24h_usd DESC LIMIT 12").fetchall()
    lab = lab_state(config, desks, market, now, alerts)
    weather = []
    for cls_, name in (("crypto", "Crypto (bitcoin)"), ("stocks", "Beurs (wereldindex)")):
        if cls_ in desks:
            ok, text = desks[cls_].regime(now)
            if ok is not None:
                weather.append({"name": name, "ok": ok, "text": text})
    vix = next((w for w in lab["watch"] if w["symbol"] == "^VIX"), None)
    state = {
        "lab": lab, "market_weather": weather, "vix": vix and vix["price"],
        "generated_at": now.isoformat(), "name": config.name, "mode": config.mode, "demo": demo,
        "kill": (home / "KILL").exists(), "days_active": days,
        "limits": {"max_drawdown_pct": config.risk.max_drawdown_pct,
                   "daily_loss_limit_pct": config.risk.daily_loss_limit_pct},
        "total": total, "desks": states, "feed": feed[:60],
        "missions": _missions(total, states, days, ever_paused),
        "radar": [{"symbol": r[0], "chain": r[1], "price_usd": r[2], "liquidity_usd": r[3], "volume_24h_usd": r[4],
                   "change_24h_pct": r[5], "flags": json.loads(r[6] or "[]")} for r in radar],
    }
    state["ticker"] = ticker(config, market, now)
    state["arena"] = market.get_state("arena")
    state["whatif"] = market.get_state("whatif")
    state["risk"] = market.get_state("risk") if config.risk_director else None
    h = health(state, problems)
    state["jarvis"] = {"health": h, "briefing": briefing(state, now, h)}
    return state


def write_site(state: dict, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    src = resources.files("jplh").joinpath("hq")
    for name in ("index.html", "factsheet.html"):
        with resources.as_file(src.joinpath(name)) as p:
            shutil.copyfile(p, out / name)
    (out / "state.json").write_text(json.dumps(state, ensure_ascii=False, default=str), encoding="utf-8")
    return out / "index.html"

"""De schaduw-arena: andere strategieën draaien op papier mee naast de echte afdelingen.

Elke uitdager krijgt per afdeling hetzelfde startgeld en dezelfde echte koersen als de afdeling
zelf, en telt pas mee vanaf de dag dat de holding begon. Er wordt dus alleen vooruit gekeken:
niemand kan winnen door achteraf het verleden te passen.

De arena handelt nooit en verandert nooit iets aan de afdelingen. Wint een uitdager lang genoeg
op rendement én op Sharpe, dan wordt hij voorgedragen. Alleen Phil beslist of hij promoveert,
en ook dan moet hij eerst in ``jplh backtest --desks`` winnen (de spelregel)."""

from __future__ import annotations

import bisect
import math
from dataclasses import replace
from datetime import date, datetime

from jplh.backtest import metrics
from jplh.config import HoldingConfig
from jplh.deskbacktest import ALLOCATIONS, VARIANTS, allocation, compare, live_variant
from jplh.desks import ALL_CANDIDATES, DESK_NAMES
from jplh.riskdirector import assess
from jplh.store import Store

LIVE = "gekozen (live)"
CONTENDERS = (
    "vasthouden (maatlat)",
    "oude versie",
    "2+3",
    "2+3+6",
    "7 vasthouden + marktweer",
    "8 rotatie top 2 (6 mnd)",
    "9b vasthouden + marktweer, marge 5%",
    "alles",
)
NICE = {
    LIVE: "huidige regels (live)",
    "vasthouden (maatlat)": "gewoon vasthouden",
    "oude versie": "actief kiezen (oude versie)",
    "2+3": "actief, minder wisselen + marktweer",
    "2+3+6": "actief, minder wisselen + marktweer + strenge drempel",
    "7 vasthouden + marktweer": "vasthouden met marktweer",
    "8 rotatie top 2 (6 mnd)": "rotatie: alleen de 2 sterkste",
    "9b vasthouden + marktweer, marge 5%": "vasthouden met marktweer, 5% marge",
    "alles": "alle trucs tegelijk",
}
PROMOTE_DAYS = 90       # zo lang moet een uitdager winnen voor hij wordt voorgedragen
MIN_EDGE = 0.01         # en dan minstens 1 procentpunt meer rendement


def arena_start(home_books: list[Store]) -> date | None:
    """De eerste dag dat de holding handelde: daar begint de arena."""
    firsts = [c[0][0].date() for c in (b.equity_curve() for b in home_books) if c]
    return min(firsts) if firsts else None


def run_arena(config: HoldingConfig, market: Store, start: date, now: datetime) -> dict:
    """Ranglijst per afdeling, alleen over de dagen sinds ``start``."""
    candles_of = {i.symbol: market.candles(i.symbol, "1d", known_at=now) for i in config.instruments}
    variants = [v for v in VARIANTS if v.name in CONTENDERS]
    res = compare(config, candles_of, ALL_CANDIDATES, variants, start=start)
    by_name = {v.name: v for v in variants}
    desks = {}
    for cls, rows in res.items():
        live_rules = replace(live_variant(config.desk_modes.get(cls, "actief")), name="")
        board = []
        for name, m in rows.items():
            if name in by_name and replace(by_name[name], name="") == live_rules:
                continue          # dezelfde regels als live: geen echte uitdager
            board.append({"name": NICE.get(name, name), "variant": name, "live": name == LIVE,
                          "return": m["return"], "sharpe": m["sharpe"], "max_dd": m["max_dd"],
                          "trades": m["trades"], "days": m["days"]})
        board.sort(key=lambda r: (-r["return"], -r["sharpe"], not r["live"]))   # gelijk: live eerst
        live = next((r for r in board if r["live"]), None)
        for r in board:
            r["promote"] = bool(live and not r["live"] and r["days"] >= PROMOTE_DAYS
                                and r["return"] >= live["return"] + MIN_EDGE and r["sharpe"] > live["sharpe"])
        desks[cls] = {"name": DESK_NAMES.get(cls, cls), "board": board,
                      "live_rank": next((i + 1 for i, r in enumerate(board) if r["live"]), None)}
    return {"start": start.isoformat(), "computed_at": now.isoformat(), "promote_days": PROMOTE_DAYS,
            "desks": desks}


WHATIF_POINTS = 260     # zoveel punten per curve op het dashboard (ongeveer wekelijks)


def _thin(rows: list, n: int = WHATIF_POINTS) -> list:
    if len(rows) <= n:
        return rows
    step = len(rows) / n
    return [rows[int(i * step)] for i in range(n - 1)] + [rows[-1]]


SHADOW_NAMES = {"schatkist": "De Schatkist", "obligaties": "Obligatiebank", "vastgoed": "Vastgoedkantoor",
                "grondstoffen": "Grondstoffenhal"}
SHADOW_WHY = {
    "schatkist": "geld dat stilligt laten renderen, bijna zonder risico",
    "obligaties": "rustige rente-inkomsten die vaak stijgen als aandelen dalen",
    "vastgoed": "huurinkomsten van gebouwen, beweegt anders dan crypto",
    "grondstoffen": "olie, metalen en landbouw: bescherming tegen inflatie",
}
MIX_SHARE = 0.10        # de test: wat als 10% van de holding naar deze afdeling was gegaan?


def _close_at(dates: list, closes: list, d) -> float | None:
    """Laatste slotkoers op of voor dag ``d``."""
    i = bisect.bisect_right(dates, d) - 1
    return closes[i] if i >= 0 else None


def _corr(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 30:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def shadow_desks(config: HoldingConfig, market: Store, start: date | None, now: datetime,
                 holding_curve: list | None) -> list[dict]:
    """Schaduw-afdelingen: hoe doen ze het sinds de start (alleen vooruit), bewegen ze anders
    dan de holding, en zou 10% erin de holding op echte koersen sterker hebben gemaakt?"""
    out = []
    groups: dict[str, list] = {}
    for x in config.shadow:
        groups.setdefault(x.desk, []).append(x)
    for desk, items in groups.items():
        series = {}
        insts = []
        for x in items:
            cs = market.candles(x.symbol, "1d", known_at=now)
            if len(cs) < 2:
                insts.append({"symbol": x.symbol, "name": x.name, "since_start": None, "fresh": False})
                continue
            dates, closes = [c.ts.date() for c in cs], [c.close for c in cs]
            series[x.symbol] = (dates, closes)
            base = _close_at(dates, closes, start) if start else None
            base = base if base is not None else closes[0]
            fresh = (now.date() - dates[-1]).days <= 5
            insts.append({"symbol": x.symbol, "name": x.name, "since_start": closes[-1] / base - 1 if start else None,
                          "fresh": fresh, "price": closes[-1]})
        rets = [i["since_start"] for i in insts if i["since_start"] is not None]
        days = (now.date() - start).days if start else 0
        row = {"id": desk, "name": SHADOW_NAMES.get(desk, desk.capitalize()), "why": SHADOW_WHY.get(desk, ""),
               "instruments": insts, "since_start": sum(rets) / len(rets) if rets else None, "days": max(days - 1, 0),
               "corr": None, "mix": None, "stronger": False}
        if holding_curve and series:
            hd = [d for d, _ in holding_curve]
            hv = [v for _, v in holding_curve]
            r_h, r_s = [], []
            for k in range(1, len(hd)):
                daily = []
                for dates, closes in series.values():
                    if dates[0] > hd[k - 1]:
                        continue
                    a, b = _close_at(dates, closes, hd[k - 1]), _close_at(dates, closes, hd[k])
                    if a and b:
                        daily.append(b / a - 1)
                if not daily:
                    continue
                r_h.append(hv[k] / hv[k - 1] - 1)
                r_s.append(sum(daily) / len(daily))
            if len(r_h) >= 180:
                mix = [(1 - MIX_SHARE) * a + MIX_SHARE * b for a, b in zip(r_h, r_s)]
                mb, mm = metrics(r_h, 0, 0, 0, 365), metrics(mix, 0, 0, 0, 365)
                row["corr"] = _corr(r_h, r_s)
                row["mix"] = {"share": MIX_SHARE, "days": len(r_h),
                              "base": {"return": mb.total_return, "sharpe": mb.sharpe, "max_dd": mb.max_drawdown},
                              "mix": {"return": mm.total_return, "sharpe": mm.sharpe, "max_dd": mm.max_drawdown}}
                row["stronger"] = mm.sharpe >= mb.sharpe + 0.02 and mm.max_drawdown <= mb.max_drawdown + 0.005
        out.append(row)
    return out


def run_whatif(config: HoldingConfig, market: Store, now: datetime, start: date | None = None) -> dict | None:
    """Voor de 'wat als'-machine: hoe de huidige regels het op echte koersen hadden gedaan,
    naast gewoon vasthouden. Per afdeling en voor de hele holding (elk kwartaal terug naar de
    vaste verdeling, zoals live). Curves beginnen op 1,0."""
    candles_of = {i.symbol: market.candles(i.symbol, "1d", known_at=now) for i in config.instruments}
    hold = [v for v in VARIANTS if v.name == "vasthouden (maatlat)"]
    res = compare(config, candles_of, ALL_CANDIDATES, hold)
    out: dict = {"computed_at": now.isoformat(), "series": {}}

    def pack(name: str, live: list, base: list) -> None:
        b = dict(base)
        rows = [(d, v) for d, v in live if d in b]
        if len(rows) < 30:
            return
        l0, b0 = rows[0][1], b[rows[0][0]]
        out["series"][name] = [[d.isoformat(), round(v / l0, 5), round(b[d] / b0, 5)] for d, v in _thin(rows)]

    for cls, rows in res.items():
        live, base = rows.get(LIVE, {}).get("curve"), rows.get(hold[0].name, {}).get("curve")
        if live and base:
            pack(DESK_NAMES.get(cls, cls), live, base)
    a_live = allocation(res, config.desks).get(ALLOCATIONS[1])
    a_hold = allocation(res, config.desks, variant=hold[0].name).get(ALLOCATIONS[1])
    if a_live and a_hold:
        pack("Hele holding", a_live["curve"], a_hold["curve"])
    if config.shadow:
        out["shadow"] = shadow_desks(config, market, start, now, a_live["curve"] if a_live else None)
    risk = assess(res, config.desks, (market.get_state("risk") or {}).get("exposure"), now)
    if risk:
        out["risk"] = risk
    return out if out["series"] or out.get("shadow") or out.get("risk") else None


def maybe_run_arena(config: HoldingConfig, market: Store, books: list[Store], now: datetime, log=print) -> dict | None:
    """Eén keer per dag de arena bijwerken (de dagkoersen veranderen maar één keer per dag)."""
    old = market.get_state("arena")
    today = now.date().isoformat()
    risk = market.get_state("risk") or {}
    if (old and old.get("computed_at", "")[:10] == today and ("shadow" in old or not config.shadow)
            and risk.get("computed_at", "")[:10] == today):
        return old
    start = arena_start(books)
    if start is None:
        return old
    try:
        new = run_arena(config, market, start, now)
    except (ValueError, KeyError, ZeroDivisionError) as exc:   # de arena mag de ronde nooit stoppen
        log(f"arena mislukt: {type(exc).__name__}: {exc}")
        return old
    try:
        w = run_whatif(config, market, now, start)
        if w:
            new["shadow"] = w.pop("shadow", [])
            risk = w.pop("risk", None)
            market.set_state("whatif", w)
            if risk:
                market.set_state("risk", risk)
                log(f"risicodirecteur: crypto+memes bewegen {risk['vol'] or 0:.0%} per jaar (doel {risk['target']:.0%}), "
                    f"stand {risk['exposure']:.0%} in de markt" + (" (verschoven)" if risk["changed"] else ""))
    except (ValueError, KeyError, ZeroDivisionError) as exc:
        log(f"wat-als mislukt: {type(exc).__name__}: {exc}")
    market.set_state("arena", new)
    for sd in new.get("shadow", []):
        if sd["mix"]:
            log(f"schaduw {sd['name']}: 10% erbij -> Sharpe {sd['mix']['base']['sharpe']:.2f} -> "
                f"{sd['mix']['mix']['sharpe']:.2f}, daling {sd['mix']['base']['max_dd']:.0%} -> {sd['mix']['mix']['max_dd']:.0%}")
    for d in new["desks"].values():
        top = d["board"][0] if d["board"] else None
        if top:
            log(f"arena {d['name']}: koploper {top['name']} {top['return']:+.1%}, echte afdeling op plek {d['live_rank']}")
    return new

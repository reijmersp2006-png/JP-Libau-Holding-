"""Milestone D: gegevens voor de Trading Workstation, Market Pulse en het agentdossier.

Alles komt uit opgeslagen koersen (holding- en onderzoeksdatabase) en de NEXUS-database. Er wordt
niets bijgemaakt: een tijdschaal zonder opgeslagen candles bestaat voor de UI niet, een ontbrekende
bron (orderboek, jaarcijfers, macrokalender) staat als ``unavailable`` met de reden erbij.
"""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path
import statistics as stats
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from nexus.datasets import periods_per_year, universe
from nexus.db import AiCall, Database, Debate, EventWorkflow, Hypothesis, NewsEvent, OrchestratorTask

INTERVALS = ("1h", "1d")
FRESH_DAYS = 4                      # zelfde grens als de Market Pulse: daarna HISTORICAL
MEME_EXTRA = {"BONK-EUR", "WIF-EUR"}

# Wat er per activaklasse wel en niet is. Dit staat in de UI, zodat geen klasse beter lijkt dan ze is.
QUALITY = {
    "crypto": {"source": "Bitvavo (publiek, EUR)", "available": ["dag- en uurkoersen", "volume"],
               "unavailable": {"orderboek en spread": "geen bron gekoppeld",
                               "funding en open interest": "geen bron gekoppeld",
                               "on-chainstromen": "geen bron gekoppeld (Glassnode/Etherscan zijn betaald of gelimiteerd)"}},
    "meme": {"source": "Bitvavo (publiek, EUR) + Social Radar", "available": ["dag- en uurkoersen", "volume",
                                                                            "veiligheidscontrole (indien gemeten)"],
             "unavailable": {"X-discussie": "X API niet verbonden",
                             "concentratie houders": "alleen via GoPlus; host geblokkeerd in deze omgeving"}},
    "stocks": {"source": "Yahoo (onofficieel, vertraagd)", "available": ["dagkoersen sinds 2020", "beperkt uurkoersen"],
               "unavailable": {"jaarcijfers en winstkalender": "aandelenbron nog niet gekozen (betaald)",
                               "bedrijfsnieuws": "alleen SEC/EDGAR, vraagt NEXUS_SEC_USER_AGENT"}},
    "metals": {"source": "Yahoo futures (vertraagd)", "available": ["dagkoersen", "beperkt uurkoersen"],
               "unavailable": {"termijnstructuur": "geen bron gekoppeld"}},
    "fx": {"source": "Yahoo + ECB-referentiekoersen", "available": ["dagkoersen sinds 2021", "beperkt uurkoersen",
                                                                   "context: dollarindex, 10-jaarsrente"],
           "unavailable": {"macrokalender en consensus": "geen bron gekoppeld",
                           "intraday-ticks": "geen bron; alleen opgeslagen uurkoersen"}},
    "context": {"source": "Yahoo (indices, rente, grondstoffen)", "available": ["dagkoersen", "beperkt uurkoersen"],
                "unavailable": {"handel": "contextreeks, niet in het handelsuniversum"}},
}


def _utc(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _classes(data) -> dict[str, tuple[str, str]]:
    """symbool → (activaklasse, munt). Eerst het handelsuniversum, daarna opgeslagen contextreeksen."""
    out = {i.symbol: (i.asset_class.value, i.currency) for i in universe(data.config)}
    for sym in stored_symbols(data):
        if sym in out:
            continue
        if sym in MEME_EXTRA:
            out[sym] = ("meme", "EUR")
        elif sym.endswith("-EUR"):
            out[sym] = ("crypto", "EUR")
        else:
            out[sym] = ("context", "USD")
    return out


def stored_symbols(data) -> list[str]:
    syms: set[str] = set()
    for path in (getattr(data, "research_db", None), getattr(data, "holding_db", None)):
        if path and Path(path).exists():
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                syms |= {r[0] for r in con.execute("select distinct symbol from candles")}
            except sqlite3.Error:
                pass
            finally:
                con.close()
    return sorted(syms)


def label_for(ts: datetime, now: datetime) -> str:
    return "DELAYED" if (now - _utc(ts)).total_seconds() / 86400 <= FRESH_DAYS else "HISTORICAL"


def universe_view(data, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(tz=UTC)
    tradeable = {i.symbol for i in universe(data.config)}
    out = []
    for sym, (cls, ccy) in sorted(_classes(data).items(), key=lambda x: (x[1][0], x[0])):
        d = data.raw(sym, "1d")
        h = data.raw(sym, "1h")
        row = {"symbol": sym, "asset_class": cls, "currency": ccy, "tradeable_universe": sym in tradeable,
               "intervals": [iv for iv, c in (("1h", h), ("1d", d)) if len(c) >= 2],
               "bars": {"1d": len(d), "1h": len(h)}}
        if len(d) >= 2:
            row.update(last=d[-1].close, ts=_utc(d[-1].ts).isoformat(), ret_1d=d[-1].close / d[-2].close - 1,
                       ret_30d=(d[-1].close / d[-31].close - 1) if len(d) > 31 else None, label=label_for(d[-1].ts, now))
        else:
            row["label"] = "UNAVAILABLE"
        out.append(row)
    return out


# ── Indicatoren (alleen op opgeslagen candles; geen vooruitkijken) ──────────────────────────────
def sma(xs: list[float], n: int) -> list[float | None]:
    out: list[float | None] = []
    s = 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n:
            s -= xs[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def rsi(xs: list[float], n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(xs)
    if len(xs) <= n:
        return out
    gains = [max(0.0, b - a) for a, b in zip(xs, xs[1:])]
    losses = [max(0.0, a - b) for a, b in zip(xs, xs[1:])]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    for i in range(n, len(xs)):
        if i > n:
            ag = (ag * (n - 1) + gains[i - 1]) / n
            al = (al * (n - 1) + losses[i - 1]) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def max_drawdown(xs: list[float]) -> float:
    peak, mdd = -math.inf, 0.0
    for x in xs:
        peak = max(peak, x)
        mdd = min(mdd, x / peak - 1)
    return mdd


def _ret(c, k):
    return c[-1].close / c[-1 - k].close - 1 if len(c) > k else None


def asset(db: Database, data, symbol: str, interval: str = "1d", limit: int = 750, now: datetime | None = None) -> dict:
    now = now or datetime.now(tz=UTC)
    classes = _classes(data)
    if symbol not in classes:
        raise KeyError(symbol)
    if interval not in INTERVALS:
        raise ValueError("interval moet 1h of 1d zijn")
    cls, ccy = classes[symbol]
    c = data.raw(symbol, interval)
    daily = data.raw(symbol, "1d") if interval != "1d" else c
    closes = [x.close for x in c]
    ind = {"sma20": sma(closes, 20), "sma50": sma(closes, 50), "sma200": sma(closes, 200), "rsi14": rsi(closes, 14)}
    lo = max(0, len(c) - max(2, min(limit, 2000)))
    candles = [{"t": int(_utc(x.ts).timestamp()), "o": x.open, "h": x.high, "l": x.low, "c": x.close, "v": x.volume}
               for x in c[lo:]]
    indicators = {k: [v for v in vs[lo:]] for k, vs in ind.items()}

    stats_out: dict = {"available": len(daily) >= 31}
    if len(daily) >= 31:
        dc = [x.close for x in daily]
        rets = [b / a - 1 for a, b in zip(dc, dc[1:])]
        ppy = periods_per_year("1d", cls if cls in ("crypto", "meme", "stocks", "metals", "fx") else "stocks")
        ytd = [x for x in daily if _utc(x.ts).year == now.year]
        vol20 = [x.volume for x in daily[-20:]]
        vol250 = [x.volume for x in daily[-250:]]
        stats_out.update({
            "ret": {"1d": _ret(daily, 1), "7d": _ret(daily, 7), "30d": _ret(daily, 30), "90d": _ret(daily, 90),
                    "1y": _ret(daily, 252 if cls in ("stocks", "metals", "fx", "context") else 365),
                    "ytd": (daily[-1].close / ytd[0].open - 1) if ytd else None},
            "vol_20d": stats.stdev(rets[-20:]) * math.sqrt(ppy) if len(rets) >= 20 else None,
            "vol_1y": stats.stdev(rets[-250:]) * math.sqrt(ppy) if len(rets) >= 60 else None,
            "max_drawdown_1y": max_drawdown(dc[-365:]),
            "high_52w": max(x.high for x in daily[-260:]), "low_52w": min(x.low for x in daily[-260:]),
            "volume_20d_vs_1y": (stats.mean(vol20) / stats.mean(vol250) - 1) if vol250 and stats.mean(vol250) > 0 else None,
            "trend": ("boven 200-daags gemiddelde" if (s := sma(dc, 200)[-1]) and dc[-1] > s
                      else "onder 200-daags gemiddelde" if s else "te kort voor 200-daags gemiddelde"),
            "rsi14": rsi(dc, 14)[-1],
        })

    with db.session() as s:
        news = [e for e in s.scalars(select(NewsEvent).order_by(NewsEvent.published_at.desc()).limit(500))
                if symbol in (e.assets or [])][:12]
        wf = {w.news_id: w for w in s.scalars(select(EventWorkflow).where(EventWorkflow.news_id.in_([e.id for e in news])))}
        news_out = [{"id": e.id, "title": e.title, "source": e.source, "source_kind": e.source_kind, "url": e.url,
                     "published_at": _utc(e.published_at).isoformat(), "category": e.category,
                     "relevance": e.relevance, "simulated": e.source_kind == "fixture",
                     "trace_id": wf[e.id].trace_id if e.id in wf else None,
                     "workflow_id": wf[e.id].id if e.id in wf else None,
                     "research_priority": (wf[e.id].intelligence or {}).get("research_priority") if e.id in wf else None}
                    for e in news]
        hyps = [{"id": h.id, "title": h.title, "status": h.status, "source": h.source,
                 "created_at": _utc(h.created_at).isoformat()}
                for h in s.scalars(select(Hypothesis).order_by(Hypothesis.id.desc()).limit(300))
                if symbol in str(h.test or {}) or symbol in h.statement][:8]
        tasks = [{"id": t.id, "agent": t.agent, "kind": t.kind, "status": t.status, "reason": t.reason[:200],
                  "updated_at": _utc(t.updated_at).isoformat()}
                 for t in s.scalars(select(OrchestratorTask).where(OrchestratorTask.subject == symbol)
                                    .order_by(OrchestratorTask.id.desc()).limit(8))]
    last = c[-1] if c else None
    return {
        "symbol": symbol, "asset_class": cls, "currency": ccy, "interval": interval,
        "intervals": [iv for iv in INTERVALS if len(data.raw(symbol, iv)) >= 2],
        "label": label_for(last.ts, now) if last else "UNAVAILABLE",
        "last": last.close if last else None, "ts": _utc(last.ts).isoformat() if last else None,
        "age_hours": round((now - _utc(last.ts)).total_seconds() / 3600, 1) if last else None,
        "candles": candles, "indicators": indicators, "stats": stats_out,
        "quality": QUALITY.get(cls, QUALITY["context"]),
        "news": news_out, "events": [{"t": int(datetime.fromisoformat(n["published_at"]).timestamp()),
                                      "text": n["title"][:80], "simulated": n["simulated"]} for n in news_out],
        "research": {"hypotheses": hyps, "tasks": tasks,
                     "note": "Hypothesen en taken zijn onderzoek, geen handelsadvies. Gemeten cijfers komen uit vaste code."},
    }


def overview(data, now: datetime | None = None) -> dict:
    """Market Pulse: rendement per klasse, beweeglijkheid, correlaties (60 dagen) en grootste bewegers."""
    now = now or datetime.now(tz=UTC)
    rows, series = [], {}
    for sym, (cls, _ccy) in _classes(data).items():
        c = data.raw(sym, "1d")
        if len(c) < 62:
            continue
        closes = [x.close for x in c]
        rets = [b / a - 1 for a, b in zip(closes[-61:], closes[-60:])]
        sd = stats.stdev(rets) or 1e-12
        rows.append({"symbol": sym, "asset_class": cls, "ts": _utc(c[-1].ts).isoformat(), "label": label_for(c[-1].ts, now),
                     "ret_1d": _ret(c, 1), "ret_7d": _ret(c, 7), "ret_30d": _ret(c, 30),
                     "vol_60d_daily": sd, "move_z": (_ret(c, 1) or 0) / sd})
        series[sym] = {_utc(x.ts).date(): x.close for x in c[-90:]}
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["asset_class"], []).append(r)
    classes = [{"asset_class": k, "n": len(v), "ret_1d": stats.mean(x["ret_1d"] for x in v),
                "ret_7d": stats.mean(x["ret_7d"] for x in v), "ret_30d": stats.mean(x["ret_30d"] for x in v),
                "breadth_up_1d": sum(x["ret_1d"] > 0 for x in v) / len(v)} for k, v in sorted(by.items())]
    keys = [r["symbol"] for r in sorted(rows, key=lambda r: (r["asset_class"], r["symbol"]))
            if r["asset_class"] != "context" or r["symbol"] in ("^GSPC", "^VIX", "^TNX", "DX-Y.NYB")]
    corr = _corr_matrix(series, keys)
    vix = data.raw("^VIX", "1d")
    newest = max((r["ts"] for r in rows), default=None)
    return {"as_of": newest, "label": label_for(datetime.fromisoformat(newest), now) if newest else "UNAVAILABLE",
            "classes": classes, "rows": sorted(rows, key=lambda r: -abs(r["move_z"])),
            "movers": sorted(rows, key=lambda r: -abs(r["move_z"]))[:8],
            "correlation": corr, "vix": vix[-1].close if vix else None,
            "regime": _regime(by, vix[-1].close if vix else None),
            "note": "Dagkoersen uit de opslag (geen streaming). Correlatie: dagrendementen over de laatste 60 gemeenschappelijke dagen."}


def _corr_matrix(series: dict, keys: list[str]) -> dict:
    common = sorted(set.intersection(*(set(series[k]) for k in keys))) if keys else []
    common = common[-61:]
    rets = {k: [series[k][b] / series[k][a] - 1 for a, b in zip(common, common[1:])] for k in keys}
    m = []
    for a in keys:
        row = []
        for b in keys:
            xa, xb = rets[a], rets[b]
            if len(xa) < 20 or stats.pstdev(xa) == 0 or stats.pstdev(xb) == 0:
                row.append(None)
            else:
                row.append(round(stats.correlation(xa, xb), 3))
        m.append(row)
    return {"symbols": keys, "matrix": m, "days": max(0, len(common) - 1)}


def _regime(by: dict, vix: float | None) -> dict:
    eq = by.get("stocks", [])
    cr = by.get("crypto", [])
    parts = []
    if eq:
        parts.append(f"aandelen 30d {stats.mean(x['ret_30d'] for x in eq):+.1%}")
    if cr:
        parts.append(f"crypto 30d {stats.mean(x['ret_30d'] for x in cr):+.1%}")
    if vix is not None:
        parts.append(f"VIX {vix:.1f} ({'verhoogd' if vix >= 20 else 'rustig'})")
    return {"summary": "; ".join(parts) or "te weinig data", "method": "eenvoudige beschrijving uit vaste code, geen voorspelling"}


# ── Agentdossier voor de Neural Core ─────────────────────────────────────────────────────────────
def agent(db: Database, key: str) -> dict:
    from nexus import central
    roles = {r["key"]: r for r in central.organization(db)}
    if key not in roles:
        raise KeyError(key)
    r = roles[key]
    with db.session() as s:
        cost = float(s.scalar(select(func.sum(OrchestratorTask.cost_usd)).where(OrchestratorTask.agent == key)) or 0)
        counts = dict(s.execute(select(OrchestratorTask.status, func.count()).where(OrchestratorTask.agent == key)
                                .group_by(OrchestratorTask.status)).all())
        steps = []
        for w in s.scalars(select(EventWorkflow).order_by(EventWorkflow.id.desc()).limit(200)):
            for st in w.steps or []:
                if st.get("agent") == key:
                    steps.append({"trace_id": w.trace_id, "workflow_id": w.id, "step": st["step"], "status": st["status"],
                                  "at": st.get("at"), "simulated": w.simulated})
        debates = []
        if key in ("crypto", "auditor", "quant", "cio"):
            for d in s.scalars(select(Debate).order_by(Debate.id.desc()).limit(10)):
                debates.append({"id": d.id, "subject": d.subject, "status": d.status,
                                "author": d.author_provider, "challenger": d.challenger_provider,
                                "recommendation": (d.summary or {}).get("recommendation")})
        ai = [{"provider": p, "calls": n, "cost_usd": float(c or 0)} for p, n, c in s.execute(
            select(AiCall.provider, func.count(), func.sum(AiCall.cost_usd)).group_by(AiCall.provider))] \
            if r["kind"] == "llm" or key in ("cio", "crypto", "auditor") else []
    return {**r, "task_counts": counts, "cost_usd": cost, "workflow_steps": steps[:20], "debates": debates,
            "ai_usage": ai, "pending": r["open_tasks"],
            "note": "Alleen echte taken, sporen en debatten. Zonder activiteit is dit dossier leeg."}


def handoffs(db: Database, limit: int = 200) -> dict:
    """Overdrachten tussen rollen, geteld uit de stappenreeks van echte gebeurtenis-sporen."""
    edges: dict[tuple[str, str], int] = {}
    sim = 0
    with db.session() as s:
        for w in s.scalars(select(EventWorkflow).order_by(EventWorkflow.id.desc()).limit(limit)):
            sim += bool(w.simulated)
            agents = [st.get("agent") for st in (w.steps or []) if st.get("status") not in ("skipped", "not_applicable", "unavailable")]
            for a, b in zip(agents, agents[1:]):
                if a and b and a != b:
                    edges[(a, b)] = edges.get((a, b), 0) + 1
        escalated = s.scalar(select(func.count()).select_from(OrchestratorTask)
                             .where(OrchestratorTask.status == "escalated")) or 0
        disagreements = sum(len((d.summary or {}).get("disagreements", []))
                            for d in s.scalars(select(Debate).order_by(Debate.id.desc()).limit(50)))
        since = datetime.now(tz=UTC) - timedelta(days=7)
        decided = s.scalar(select(func.count()).select_from(OrchestratorTask).where(
            OrchestratorTask.status == "done", OrchestratorTask.updated_at >= since)) or 0
    return {"edges": [{"from": a, "to": b, "n": n} for (a, b), n in sorted(edges.items(), key=lambda x: -x[1])],
            "simulated_traces": sim, "escalations_open": escalated, "disagreements": disagreements,
            "completed_7d": decided}

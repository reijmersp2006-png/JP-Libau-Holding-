"""NEXUS Evolution: leren van elk besluit, met meetbare gevolgen.

    Waarnemen → Besluiten → Uitvoeren of Afwijzen → Meten → Analyseren → Leren → Valideren → Verbeteren

- **Waarnemen**: elk besluit komt in het trade-geheugen (``decision_records``): uitgevoerd, afgewezen of
  gemist, met regime, indicatoren, nieuws, adviezen van agents, in- en uitstapvoorwaarden, omvang en
  verwachte kosten. Bronnen: de paper-bots van de holding, NEXUS-paper, het lab (historische
  herhaling van een strategie, gelabeld als SIMULATED) en de AI Council.
- **Meten**: na afloop het rendement op 1, 5 en 20 perioden, het grootste tussentijdse plus en min.
- **Analyseren**: vaste, controleerbare regels zetten foutlabels (te laat na een uitbraak, te vroeg
  uit in een trend, weinig liquiditeit, verkeerd op nieuws, overtrading in een zijwaartse markt,
  te veel risico bij een volatiliteitspiek, gemiste kans).
- **Leren**: terugkerende fouten worden een hypothese met een concreet testplan (familie, rooster).
- **Valideren**: de Alpha Research Engine test het plan walk-forward tegen de bron-strategie.
- **Verbeteren**: een gesteunde hypothese levert een nieuwe modelversie (status ``candidate``) in het
  register. Die moet daarna alle champion-challenger-poorten door. Er verandert nooit iets aan een
  lopende strategie of aan risicolimieten zonder menselijke goedkeuring.

"Het systeem heeft geleerd" telt alleen als er een nieuwe modelversie, een gewijzigde
hypothese-status of een bijgestelde agent-weging met cijfers tegenover staat.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jplh.models import Candle
from sqlalchemy import func, select

from nexus import alpha, lab, stats
from nexus.datasets import ResearchData, universe
from nexus.db import (DEFAULT_ORG, Database, DecisionRecord, Hypothesis, ModelVersion, NewsEvent, PortfolioValuation,
                      utcnow)

HORIZONS = (1, 5, 20)

# Foutlabel → wat we testen. ``grid`` is klein met opzet: minder pogingen, minder toeval.
PLAYBOOK = {
    "early_exit_in_trend": {
        "title": "Te vroeg uit de markt tijdens een stijgende trend",
        "statement": "Uitstappen terwijl de trend omhoog wijst kost meer dan het bespaart. Een strategie die bij "
                     "onrust de positie verkleint of langer vasthoudt, haalt meer van de stijging binnen.",
        "test": [{"family": "volfilter_v2", "grid": {"quantile": [0.8, 0.9], "min_hold": [10, 20]}},
                 {"family": "vol_target", "grid": {"target": [0.15, 0.20], "window": [20, 60], "trend": [200]}}],
    },
    "late_entry_after_breakout": {
        "title": "Te laat instappen na een uitbraak",
        "statement": "Instappen nadat de koers al ver boven de uitbraak staat verkleint de winst. Een sneller, "
                     "bevestigd uitbraaksignaal zou eerder instappen.",
        "test": [{"family": "breakout_confirm", "grid": {"entry": [20, 55], "exit": [10, 20], "confirm": [1]}}],
    },
    "overtrading_sideways": {
        "title": "Te vaak handelen in een zijwaartse markt",
        "statement": "In een vlakke markt kosten snelle wissels meer dan ze opleveren. Een minimale houdtijd of "
                     "graduele positie verlaagt de kosten zonder rendement te verliezen.",
        "test": [{"family": "volfilter_v2", "grid": {"quantile": [0.7, 0.8], "min_hold": [10, 20]}},
                 {"family": "trend_strength", "grid": {"fast": [50], "slow": [200], "floor": [0.5]}}],
    },
    "risk_in_vol_spike": {
        "title": "Te veel risico tijdens een volatiliteitspiek",
        "statement": "Volle posities tijdens extreme beweeglijkheid geven de grootste verliezen. Een positie die "
                     "meebeweegt met de beweeglijkheid verlaagt de daling.",
        "test": [{"family": "vol_target", "grid": {"target": [0.10, 0.15], "window": [20], "trend": [0, 200]}}],
    },
    "low_liquidity": {
        "title": "Handelen bij weinig liquiditeit",
        "statement": "Orders bij een fractie van het normale volume hebben meer slippage dan het model aanneemt.",
        "test": [],   # vergt een uitvoeringsregel, geen nieuwe familie: open voor menselijk ontwerp
    },
    "news_misreaction": {
        "title": "Verkeerd gereageerd op nieuws",
        "statement": "Besluiten kort na een nieuwsfeit gingen vaker tegen de latere koersrichting in.",
        "test": [],   # wacht op genoeg historische gebeurtenissen (event study in nexus.news)
    },
    "missed_opportunity": {
        "title": "Gemiste stijging buiten de markt",
        "statement": "De strategie stond buiten de markt tijdens grote stijgingen; een deel van die tijd kan "
                     "met een kleinere positie in de markt.",
        "test": [{"family": "vol_target", "grid": {"target": [0.10, 0.15, 0.20], "window": [20, 60], "trend": [0]}},
                 {"family": "tsmom_multi", "grid": {"scale": [0.5, 1]}}],
    },
}
MIN_TAGS = 3                 # pas vanaf zoveel gevallen wordt een fout een hypothese
SUPPORT_P = 0.80             # kans dat de nieuwe versie een betere Sharpe heeft dan de bron


# ── Waarnemen ──────────────────────────────────────────────────────────────────────────────
def _dt(s: str) -> datetime:
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def record(db: Database, **kw) -> bool:
    """Voegt één besluit toe; ``dedupe_key`` voorkomt dubbele regels. Geeft True als het nieuw was."""
    with db.session.begin() as s:
        if s.scalar(select(DecisionRecord.id).where(DecisionRecord.dedupe_key == kw["dedupe_key"])):
            return False
        s.add(DecisionRecord(org_id=DEFAULT_ORG, **kw))
        return True


def ingest_holding(db: Database, holding_home: Path) -> int:
    """Besluiten van de paper-bots van de holding (events ``decision`` in elke afdeling)."""
    n = 0
    for f in sorted((holding_home / "data" / "desks").glob("*.sqlite3")):
        con = sqlite3.connect(f"file:{f}?mode=ro", uri=True)
        try:
            rows = con.execute("SELECT id, ts, payload FROM events WHERE kind='decision' ORDER BY id").fetchall()
        finally:
            con.close()
        for eid, ts, payload in rows:
            p = json.loads(payload)
            approved = bool(p.get("approved"))
            n += record(db, ts=_dt(ts), symbol=p.get("instrument", "?"), kind="executed" if approved else "rejected",
                        source=f"holding:{f.stem}", side=p.get("side", "buy"), strategy_key=p.get("strategy"),
                        entry_conditions={"signal": p.get("signal_reason")}, size_eur=p.get("size_eur") or 0.0,
                        actual={"checks": p.get("checks", []), "reason": p.get("reason")},
                        reject_reason=None if approved else p.get("reason"),
                        dedupe_key=f"holding:{f.stem}:{eid}")
    return n


def ingest_nexus(db: Database) -> int:
    """Voorstellen in NEXUS zelf: uitgevoerd (paper-order) of afgewezen door de Risk Guardian."""
    from nexus.db import Order, RiskEvaluation, TradeProposal
    n = 0
    with db.session() as s:
        rows = s.execute(select(TradeProposal, RiskEvaluation).join(RiskEvaluation,
                         RiskEvaluation.proposal_id == TradeProposal.id)).all()
        orders = {o.evaluation_id: o for o in s.scalars(select(Order))}
    for p, ev in rows:
        o = orders.get(ev.id)
        executed = o is not None and o.status in ("filled", "partially_filled")
        kind = "executed" if executed else ("rejected" if not ev.approved else None)
        if kind is None:
            continue
        payload = p.payload or {}
        n += record(db, ts=p.created_at if p.created_at.tzinfo else p.created_at.replace(tzinfo=UTC),
                    symbol=p.symbol, kind=kind, source="nexus", side=p.direction,
                    strategy_key=p.strategy_id, entry_conditions={"entry": payload.get("entry_conditions"),
                                                                  "entry_price": payload.get("entry_price")},
                    exit_conditions={"stop": payload.get("stop_loss"), "target": payload.get("take_profit"),
                                     "alternative": payload.get("alternative_exit")},
                    agent_recommendations=payload.get("agents", []), size_eur=payload.get("size_eur") or 0.0,
                    price=payload.get("entry_price") or 0.0,
                    est_costs_eur=(payload.get("size_eur") or 0.0) * ((payload.get("est_fee_pct") or 0.0)
                                                                     + (payload.get("est_slippage_pct") or 0.0)
                                                                     + (payload.get("spread_pct") or 0.0) / 2),
                    actual={"order_status": o.status if o else None, "checks": ev.checks,
                            "filled_eur": o.filled_notional_eur if o else 0.0},
                    reject_reason=None if executed else ev.reason,
                    dedupe_key=f"nexus:proposal:{p.id}")
    return n


def replay(db: Database, key: str, symbol: str, candles: list[Candle], cost_pct: float, start: int = 0,
           version: int = 1, label: str = "lab") -> int:
    """Historische besluiten van een lab-strategie, gelabeld als simulatie (``source = backtest``)."""
    sp = lab.spec(key, version)
    strat = sp.build()
    t = strat.targets(candles)
    n = 0
    for i in range(max(start, 1), len(candles)):
        if t[i] == t[i - 1]:
            continue
        side = "buy" if t[i] else "sell"
        n += record(db, ts=candles[i].ts, symbol=symbol, kind="executed", source="backtest", side=side,
                    strategy_key=key, strategy_version=version, regime=regime_at(candles, i),
                    indicators=indicators_at(candles, i), entry_conditions={"rule": sp.entry} if t[i] else {},
                    exit_conditions={"rule": sp.exit} if not t[i] else {}, price=candles[i].close,
                    est_costs_eur=cost_pct * 1000, explanation=strat.explain(candles[:i + 1]),
                    actual={"data_label": "SIMULATED", "execution": "volgende opening"},
                    dedupe_key=f"{label}:{key}:v{version}:{symbol}:{candles[i].ts.isoformat()}")
    return n


def missed(db: Database, key: str, symbol: str, candles: list[Candle], horizon: int = 20, k: float = 2.0,
           start: int = 0, version: int = 1) -> int:
    """Gemiste kansen: de strategie stond buiten de markt en de koers steeg daarna uitzonderlijk."""
    t = lab.spec(key, version).build().targets(candles)
    px = [c.close for c in candles]
    sd = alpha.rolling_std(alpha.returns(px), 60)
    n = 0
    last = -horizon
    for i in range(max(start, 60), len(candles) - horizon):
        if t[i] or sd[i] is None or i - last < horizon:
            continue
        fwd = px[i + horizon] / px[i] - 1
        if fwd > k * sd[i] * math.sqrt(horizon):
            last = i
            n += record(db, ts=candles[i].ts, symbol=symbol, kind="missed", source="backtest", side="buy",
                        strategy_key=key, strategy_version=version, regime=regime_at(candles, i),
                        indicators=indicators_at(candles, i), price=px[i],
                        reject_reason="strategie stond buiten de markt",
                        actual={"data_label": "SIMULATED"},
                        dedupe_key=f"missed:{key}:v{version}:{symbol}:{candles[i].ts.isoformat()}")
    return n


# ── Context ────────────────────────────────────────────────────────────────────────────────
def indicators_at(c: list[Candle], i: int) -> dict:
    px = [x.close for x in c[max(0, i - 260): i + 1]]
    j = len(px) - 1
    rets = alpha.returns(px)

    def sma(n):
        return sum(px[j + 1 - n: j + 1]) / n if j + 1 >= n else None
    vol20 = stats.stdev(rets[-20:]) if len(rets) > 21 else None
    vol_hist = [stats.stdev(rets[k - 20:k]) for k in range(21, len(rets), 5)] if len(rets) > 60 else []
    v = [x.volume for x in c[max(0, i - 20): i + 1]]
    return {"close": px[-1], "sma20": sma(20), "sma50": sma(50), "sma200": sma(200), "vol20": vol20,
            "vol_pct_rank": (sum(1 for x in vol_hist if x <= vol20) / len(vol_hist)) if vol_hist and vol20 else None,
            "ret20": px[-1] / px[-21] - 1 if len(px) > 21 else None,
            "low20": min(x.low for x in c[max(0, i - 20): i]) if i > 0 else None,
            "high20": max(x.high for x in c[max(0, i - 20): i]) if i > 0 else None,
            "volume_ratio": v[-1] / stats.mean(v[:-1]) if len(v) > 5 and stats.mean(v[:-1]) > 0 else None}


def regime_at(c: list[Candle], i: int) -> dict:
    ind = indicators_at(c, i)
    trend = ("up" if ind["sma200"] and ind["close"] > ind["sma200"] and (ind["sma50"] or 0) > ind["sma200"] else
             "down" if ind["sma200"] and ind["close"] < ind["sma200"] else "mixed")
    vol = ("high" if (ind["vol_pct_rank"] or 0) > 0.8 else "low" if (ind["vol_pct_rank"] or 1) < 0.2 else "normal")
    slope = None
    if i >= 220:
        s_now = sum(x.close for x in c[i - 99: i + 1]) / 100
        s_old = sum(x.close for x in c[i - 119: i - 19]) / 100
        slope = s_now / s_old - 1
    sideways = slope is not None and abs(slope) < 0.01
    return {"trend": trend, "volatility": vol, "sideways": sideways, "label": f"{trend}/{vol}"}


# ── Meten ──────────────────────────────────────────────────────────────────────────────────
def measure(db: Database, candles_of: dict[str, list[Candle]]) -> int:
    """Rekent openstaande besluiten af zodra er genoeg koersen na het besluit zijn."""
    n = 0
    with db.session.begin() as s:
        for r in s.scalars(select(DecisionRecord).where(DecisionRecord.outcome_at.is_(None))):
            c = candles_of.get(r.symbol)
            if not c:
                continue
            ts = r.ts if r.ts.tzinfo else r.ts.replace(tzinfo=UTC)
            i = next((k for k, x in enumerate(c) if x.ts >= ts), None)
            if i is None or i + max(HORIZONS) >= len(c):
                continue
            p0 = c[i].close
            out = {f"fwd_{h}": c[i + h].close / p0 - 1 for h in HORIZONS}
            window = c[i + 1: i + 21]
            out["mfe_20"] = max(x.high for x in window) / p0 - 1
            out["mae_20"] = min(x.low for x in window) / p0 - 1
            f20 = out["fwd_20"]
            if r.kind == "executed":
                out["good"] = f20 > 0 if r.side == "buy" else f20 < 0
            elif r.kind == "rejected":
                out["good"] = f20 <= 0 if r.side == "buy" else f20 >= 0
            else:
                out["good"] = False
            r.outcome = out
            r.outcome_at = utcnow()
            if not r.regime:
                r.regime = regime_at(c, i)
            if not r.indicators:
                r.indicators = indicators_at(c, i)
            r.error_tags = tag(r, c, i)
            n += 1
    return n


# ── Analyseren ─────────────────────────────────────────────────────────────────────────────
def tag(r: DecisionRecord, c: list[Candle], i: int) -> list[str]:
    """Vaste regels; elk label is na te rekenen uit de opgeslagen indicatoren en uitkomst."""
    tags = []
    ind, reg, out = r.indicators or {}, r.regime or {}, r.outcome or {}
    vol = ind.get("vol20") or 0.0
    f20 = out.get("fwd_20")
    if r.kind == "executed" and r.side == "sell" and f20 is not None and reg.get("trend") == "up" \
            and f20 > 2 * vol * math.sqrt(20):
        tags.append("early_exit_in_trend")
    if r.kind == "executed" and r.side == "buy" and ind.get("high20") and ind.get("low20"):
        run = ind["close"] / ind["low20"] - 1
        if ind["close"] > ind["high20"] and vol and run > 3 * vol * math.sqrt(20):
            tags.append("late_entry_after_breakout")
    if r.kind == "executed" and (ind.get("volume_ratio") or 1) < 0.5:
        tags.append("low_liquidity")
    if r.kind == "executed" and r.side == "buy" and reg.get("volatility") == "high" and (out.get("mae_20") or 0) < -2 * vol * math.sqrt(20):
        tags.append("risk_in_vol_spike")
    if r.kind == "missed" or (r.kind == "rejected" and r.side == "buy" and f20 is not None and f20 > 2 * vol * math.sqrt(20)):
        tags.append("missed_opportunity")
    if r.news_context and f20 is not None:
        sign = 1 if r.side == "buy" else -1
        if sign * f20 < -vol * math.sqrt(20):
            tags.append("news_misreaction")
    return tags


def tag_overtrading(db: Database, window_days: int = 20, min_trades: int = 4) -> int:
    """Overtrading: veel wissels in korte tijd terwijl de markt zijwaarts ging (over records heen)."""
    n = 0
    with db.session.begin() as s:
        rows = s.scalars(select(DecisionRecord).where(DecisionRecord.kind == "executed")
                         .order_by(DecisionRecord.symbol, DecisionRecord.strategy_key, DecisionRecord.ts)).all()
        groups = defaultdict(list)
        for r in rows:
            groups[(r.symbol, r.strategy_key, r.source)].append(r)
        for rs in groups.values():
            for k, r in enumerate(rs):
                ts = r.ts if r.ts.tzinfo else r.ts.replace(tzinfo=UTC)
                recent = [x for x in rs[max(0, k - min_trades + 1): k + 1]
                          if ts - (x.ts if x.ts.tzinfo else x.ts.replace(tzinfo=UTC)) <= timedelta(days=window_days)]
                if len(recent) >= min_trades and (r.regime or {}).get("sideways") and "overtrading_sideways" not in (r.error_tags or []):
                    r.error_tags = [*(r.error_tags or []), "overtrading_sideways"]
                    n += 1
    return n


def analyze(db: Database) -> dict:
    with db.session() as s:
        rows = s.scalars(select(DecisionRecord).where(DecisionRecord.outcome_at.is_not(None))).all()
    by_tag: dict[str, dict] = {}
    for r in rows:
        for t in r.error_tags or []:
            d = by_tag.setdefault(t, {"count": 0, "symbols": Counter(), "strategies": Counter(), "fwd20": []})
            d["count"] += 1
            d["symbols"][r.symbol] += 1
            d["strategies"][r.strategy_key or "?"] += 1
            d["fwd20"].append((r.outcome or {}).get("fwd_20") or 0.0)
    kinds = Counter(r.kind for r in rows)
    good = Counter((r.kind, bool((r.outcome or {}).get("good"))) for r in rows)
    return {"measured": len(rows), "by_kind": dict(kinds),
            "hit_rate": {k: good[(k, True)] / kinds[k] for k in kinds if kinds[k]},
            "tags": {t: {"count": d["count"], "symbols": dict(d["symbols"]), "strategies": dict(d["strategies"]),
                         "avg_fwd20": stats.mean(d["fwd20"])} for t, d in sorted(by_tag.items(), key=lambda kv: -kv[1]["count"])}}


# ── Leren: hypothesen ──────────────────────────────────────────────────────────────────────
def generate_hypotheses(db: Database, analysis: dict) -> list[int]:
    created = []
    with db.session.begin() as s:
        for t, d in analysis["tags"].items():
            if d["count"] < MIN_TAGS or t not in PLAYBOOK:
                continue
            sym, cnt = max(d["symbols"].items(), key=lambda kv: kv[1])
            strat = max(d["strategies"].items(), key=lambda kv: kv[1])[0]
            exists = s.scalar(select(Hypothesis.id).where(Hypothesis.error_tag == t,
                                                          Hypothesis.status.in_(("open", "testing")),
                                                          Hypothesis.test["symbol"].as_string() == sym))
            if exists:
                continue
            pb = PLAYBOOK[t]
            h = Hypothesis(source="evolution", error_tag=t, title=f"{pb['title']} ({sym}, {strat})",
                           statement=pb["statement"],
                           test={"symbol": sym, "baseline": {"key": strat, "version": 1}, "candidates": pb["test"]},
                           evidence={"cases": cnt, "all_cases": d["count"], "avg_fwd20": d["avg_fwd20"]},
                           status="open" if pb["test"] else "inconclusive")
            s.add(h)
            s.flush()
            created.append(h.id)
    if created:
        db.audit("evolution", "hypotheses_created", {"ids": created})
    return created


def seed_audit_hypotheses(db: Database) -> list[int]:
    """De vier hypothesen uit de IWDA-diagnose (research/IWDA-DIAGNOSE.md)."""
    seeds = [
        ("A: kleiner in plaats van eruit", "Een positie die meebeweegt met de beweeglijkheid houdt meer van de drift "
         "van IWDA vast dan volfilter v1.", [{"family": "vol_target", "grid": {"target": [0.10, 0.15, 0.20], "window": [20, 60], "trend": [0, 200]}}]),
        ("B: minder handelen", "Een filter met hysterese en houdtijd halveert het aantal trades en de kosten.",
         [{"family": "volfilter_v2", "grid": {"quantile": [0.7, 0.8, 0.9], "min_hold": [5, 10, 20]}}]),
        ("C: risico-gematchte maatlat", "Op een breed gespreide index is het doel dezelfde Sharpe met kleinere "
         "dalingen; toets tegen koop-en-houd geschaald naar hetzelfde risico.",
         [{"family": "trend_strength", "grid": {"fast": [20, 50], "slow": [100, 200], "floor": [0.5]}}]),
        ("D: rotatie in plaats van cash", "Buiten aandelen naar geldmarkt of obligaties verandert de rekensom.",
         [{"family": "regime_switch", "grid": {"trend": [100, 200], "vol_cap": [0.18, 0.25, 0.35]}}]),
    ]
    ids = []
    with db.session.begin() as s:
        for title, stmt, test in seeds:
            if s.scalar(select(Hypothesis.id).where(Hypothesis.title == f"IWDA {title}")):
                continue
            h = Hypothesis(source="audit", error_tag=None, title=f"IWDA {title}", statement=stmt,
                           test={"symbol": "IWDA.AS", "baseline": {"key": "volatility_filter", "version": 1},
                                 "candidates": test}, evidence={"report": "research/IWDA-DIAGNOSE.md"})
            s.add(h)
            s.flush()
            ids.append(h.id)
    return ids


# ── Valideren en verbeteren ────────────────────────────────────────────────────────────────
def test_hypothesis(db: Database, data: ResearchData, hid: int, capital: float = 1000.0) -> dict:
    """Walk-forward toets van de kandidaten tegen de bron-strategie. Gesteund → nieuwe modelversie."""
    with db.session() as s:
        h = s.get(Hypothesis, hid)
        test = dict(h.test)
    sym = test["symbol"]
    inst = next(i for i in universe(data.config) if i.symbol == sym)
    ds = data.load(inst, "1d")
    sp = alpha.make_split(len(ds.candles), alpha.WARMUP)
    if sp is None or not test.get("candidates"):
        return _resolve(db, hid, "inconclusive", {"reason": "te weinig geschiedenis of geen testplan"})
    from nexus.champion import _wf_fixed, lab_weights
    costs = {sym: alpha.research_costs(data, inst)}
    base = test["baseline"]
    panel = {sym: ds.candles}
    bench_w = [{sym: 1.0}] * len(ds.candles)
    base_wf = _wf_fixed(lab_weights(base["key"], base.get("version"), ds.candles, sym), panel, costs, sp, ds.ppy,
                        capital, bench_w)
    rows = []
    for cand in test["candidates"]:
        fam = alpha.family(cand["family"])
        if fam.kind == "portfolio":
            group = [i for i in universe(data.config) if i.symbol in ("IWDA.AS", "IEAG.AS", "XEON.DE")]
            dsets = [data.load(i, "1d") for i in group]
            ppanel = alpha.align(dsets)
            pcosts = {d.inst.symbol: alpha.research_costs(data, d.inst) for d in dsets}
            fam_g = alpha.Family(**{**fam.__dict__, "grid": cand["grid"]})
            res = alpha.evaluate_dataset(fam_g, ppanel, sym, pcosts, ds.ppy, "1d", capital, len(fam_g.combos()))
            if "_split" not in res:
                rows.append({"family": fam.key, "grid": cand["grid"], "status": "insufficient_history"})
                continue
            # Bron op dezelfde (uitgelijnde) dagen.
            psp = res.pop("_split")
            base_cmp = _wf_fixed(lab_weights(base["key"], base.get("version"), ppanel[sym], sym), {sym: ppanel[sym]},
                                 costs, psp, ds.ppy, capital, [{sym: 1.0}] * len(ppanel[sym]))
        else:
            fam_g = alpha.Family(**{**fam.__dict__, "grid": cand["grid"]})
            res = alpha.evaluate_dataset(fam_g, panel, sym, costs, ds.ppy, "1d", capital, len(fam_g.combos()))
            if res.pop("_split", None) is None:
                rows.append({"family": fam.key, "grid": cand["grid"], "status": "insufficient_history"})
                continue
            base_cmp = base_wf
        r = res.pop("_wf_returns")
        n = min(len(r), len(base_cmp["returns"]))
        vs = stats.excess_uncertainty(r[-n:], base_cmp["returns"][-n:], ds.ppy)
        rows.append({"family": fam.key, "grid": cand["grid"], "frozen_params": res["frozen_params"],
                     "walk_forward": res["walk_forward"], "baseline_walk_forward": base_cmp["metrics"],
                     "buy_hold": res["benchmark"], "vs_baseline": vs, "vs_buy_hold": res["uncertainty"],
                     "vs_risk_matched": res["risk_matched_excess"]})
    tested = [x for x in rows if "vs_baseline" in x]
    if not tested:
        return _resolve(db, hid, "inconclusive", {"reason": "geen kandidaat had genoeg geschiedenis", "candidates": rows})
    best = max(tested, key=lambda x: x["vs_baseline"].get("p_sharpe_better") or 0)
    p = best["vs_baseline"].get("p_sharpe_better") or 0
    beats_bh = (best["vs_buy_hold"].get("p_sharpe_better") or 0) >= SUPPORT_P
    status = "supported" if p >= SUPPORT_P else ("rejected" if p < 0.5 else "inconclusive")
    result = {"candidates": rows, "best": best["family"], "p_better_than_baseline": p,
              "beats_buy_hold": beats_bh, "support_threshold": SUPPORT_P}
    model_id = None
    if status == "supported":
        model_id = register_candidate(db, best["family"], [sym], "1d", best["frozen_params"],
                                      {"walk_forward": best["walk_forward"], "vs_baseline": best["vs_baseline"],
                                       "vs_buy_hold": best["vs_buy_hold"]},
                                      notes=f"uit hypothese #{hid}: {h.title}")
        result["model_version_id"] = model_id
    return _resolve(db, hid, status, result)


def _resolve(db: Database, hid: int, status: str, result: dict) -> dict:
    with db.session.begin() as s:
        h = s.get(Hypothesis, hid)
        h.status, h.result = status, json.loads(json.dumps(result, default=str))
        h.resolved_at = utcnow() if status in ("supported", "rejected", "inconclusive") else None
        db.audit("evolution", "hypothesis_tested", {"id": hid, "status": status,
                                                     "model_version_id": result.get("model_version_id")}, s=s)
    return {"id": hid, "status": status, **result}


def register_candidate(db: Database, key: str, symbols: list[str], interval: str, params: dict, metrics: dict,
                       notes: str = "", status: str = "candidate", role: str | None = "challenger") -> int:
    with db.session.begin() as s:
        prev = s.scalar(select(func.max(ModelVersion.version)).where(ModelVersion.key == key))
        existing = s.scalars(select(ModelVersion).where(ModelVersion.key == key, ModelVersion.interval == interval)).all()
        for e in existing:
            if e.params == params and e.symbols == symbols:
                return e.id
        m = ModelVersion(key=key, version=(prev or 0) + 1, symbols=symbols, interval=interval, params=params,
                         status=status, role=role, metrics=json.loads(json.dumps(metrics, default=str)), notes=notes)
        s.add(m)
        s.flush()
        db.audit("evolution", "model_registered", {"id": m.id, "key": key, "version": m.version, "status": status}, s=s)
        return m.id


def seed_champions(db: Database) -> None:
    """De bestaande lab-strategie op IWDA is de kampioen (research/paper; live blijft dicht)."""
    with db.session.begin() as s:
        if s.scalar(select(ModelVersion.id).where(ModelVersion.role == "champion")):
            return
        sp = lab.spec("volatility_filter")
        s.add(ModelVersion(key="lab:volatility_filter", version=1, symbols=["IWDA.AS"], interval="1d",
                           params=sp.params, status="champion", role="champion",
                           notes="bestaande strategie (Master Prompt 2); kampioen tot een uitdager alle poorten haalt"))


def cycle(db: Database, data: ResearchData, holding_home: Path | None = None, replay_symbols: tuple[str, ...] = ("IWDA.AS",),
          test: bool = True) -> dict:
    """Eén volledige leerronde. Geeft terug wat er meetbaar veranderde."""
    seed_champions(db)
    seeded = seed_audit_hypotheses(db)
    obs = {"holding": ingest_holding(db, holding_home) if holding_home else 0, "nexus": ingest_nexus(db)}
    candles_of = {}
    for sym in replay_symbols:
        inst = next((i for i in universe(data.config) if i.symbol == sym), None)
        if inst is None:
            continue
        c = data.load(inst, "1d").candles
        candles_of[sym] = c
        cm = data.config.costs[inst.asset_class.value]
        obs[f"replay:{sym}"] = replay(db, "volatility_filter", sym, c, cm.fee_pct + cm.slippage_pct, start=260)
        obs[f"missed:{sym}"] = missed(db, "volatility_filter", sym, c, start=260)
    with db.session() as s:
        for sym in {r for r in s.scalars(select(DecisionRecord.symbol).distinct())}:
            if sym not in candles_of:
                inst = next((i for i in universe(data.config) if i.symbol == sym), None)
                if inst is not None:
                    candles_of[sym] = data.load(inst, "1d").candles
    measured = measure(db, candles_of)
    over = tag_overtrading(db)
    an = analyze(db)
    created = generate_hypotheses(db, an)
    tested = []
    if test:
        with db.session() as s:
            open_ids = [h.id for h in s.scalars(select(Hypothesis).where(Hypothesis.status == "open"))]
        for hid in open_ids:
            tested.append(test_hypothesis(db, data, hid))
    return {"observed": obs, "measured": measured, "overtrading_tags": over, "analysis": an,
            "hypotheses_seeded": seeded, "hypotheses_created": created,
            "tested": [{"id": t["id"], "status": t["status"], "best": t.get("best"),
                        "p_better_than_baseline": t.get("p_better_than_baseline"),
                        "beats_buy_hold": t.get("beats_buy_hold"),
                        "model_version_id": t.get("model_version_id")} for t in tested]}


def news_context(db: Database, symbol: str, ts: datetime, hours: int = 48) -> list[dict]:
    with db.session() as s:
        rows = s.scalars(select(NewsEvent).where(NewsEvent.published_at <= ts,
                                                 NewsEvent.published_at >= ts - timedelta(hours=hours))).all()
    return [{"id": r.id, "title": r.title, "source": r.source, "published_at": r.published_at.isoformat()}
            for r in rows if symbol in (r.assets or [])]


__all__ = ["cycle", "record", "measure", "analyze", "generate_hypotheses", "test_hypothesis", "PortfolioValuation"]

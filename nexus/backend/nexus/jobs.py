"""Geplande onderzoekstaken met vaste ritmes en kostenbewaking.

| Ritme     | Taken |
|-----------|-------|
| elk uur   | nieuws ophalen, koersreacties bijwerken, grote marktbewegingen signaleren, risico bewaken |
| dagelijks | paper reconciliëren, afgeronde besluiten en voorspellingen afrekenen, prestatierapport |
| wekelijks | leerronde (terugkerende fouten, hypothesen, toetsen), verslechtering van de kampioen |
| maandelijks | volledige ontdekkingsrun, champion-challenger-arena, vergelijking met maatlatten |

Taken draaien in de worker (in een thread, niet in de webserver-lus). Elke run komt in ``job_runs``.
AI-verzoeken gebeuren alleen in de Council-taak, alleen voor ``NEXUS_COUNCIL_SYMBOLS`` en binnen het
dagbudget (``NEXUS_AI_DAILY_BUDGET_USD``). Een taak die faalt, blokkeert de andere niet.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from nexus.db import Database, JobRun, ResearchRun, utcnow

log = logging.getLogger("nexus.jobs")

CADENCE = {"hourly": timedelta(hours=1), "daily": timedelta(days=1), "weekly": timedelta(days=7),
           "monthly": timedelta(days=30)}


@dataclass(frozen=True)
class Job:
    key: str
    cadence: str
    description: str
    fn: Callable[[dict], dict]
    uses_ai: bool = False


def last_run(db: Database, key: str) -> JobRun | None:
    with db.session() as s:
        return s.scalars(select(JobRun).where(JobRun.job == key).order_by(JobRun.id.desc()).limit(1)).first()


def due(db: Database, job: Job, now: datetime) -> bool:
    r = last_run(db, job.key)
    if r is None:
        return True
    started = r.started_at if r.started_at.tzinfo else r.started_at.replace(tzinfo=UTC)
    return now - started >= CADENCE[job.cadence]


def run_job(db: Database, job: Job, ctx: dict) -> dict:
    with db.session.begin() as s:
        jr = JobRun(job=job.key, status="running")
        s.add(jr)
        s.flush()
        jid = jr.id
    status, detail = "ok", {}
    try:
        detail = job.fn(ctx) or {}
        if detail.get("skipped"):
            status = "skipped"
    except Exception as e:  # noqa: BLE001
        log.exception("taak %s mislukt", job.key)
        status, detail = "failed", {"error": str(e)[:500]}
    with db.session.begin() as s:
        jr = s.get(JobRun, jid)
        jr.status, jr.finished_at = status, utcnow()
        jr.detail = _jsonable(detail)
        jr.ai_requests = int(detail.get("ai_requests", 0) or 0)
        jr.ai_cost_usd = float(detail.get("ai_cost_usd", 0) or 0)
    return {"job": job.key, "status": status, "detail": detail}


def run_due(db: Database, jobs: list[Job], ctx: dict, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(tz=UTC)
    return [run_job(db, j, ctx) for j in jobs if due(db, j, now)]


def _jsonable(x):
    import json
    return json.loads(json.dumps(x, default=str))


def overview(db: Database, jobs: list[Job]) -> list[dict]:
    out = []
    now = datetime.now(tz=UTC)
    for j in jobs:
        r = last_run(db, j.key)
        started = (r.started_at if r and r.started_at.tzinfo else (r.started_at.replace(tzinfo=UTC) if r else None))
        out.append({"job": j.key, "cadence": j.cadence, "description": j.description, "uses_ai": j.uses_ai,
                    "last_status": r.status if r else None, "last_started": started.isoformat() if started else None,
                    "next_due": (started + CADENCE[j.cadence]).isoformat() if started else now.isoformat(),
                    "last_detail": r.detail if r else None})
    return out


# ── Taken ──────────────────────────────────────────────────────────────────────────────────
def _candles_of(ctx: dict, symbols: list[str], interval: str = "1d") -> dict:
    from nexus.datasets import universe
    data = ctx["data"]
    insts = {i.symbol: i for i in universe(data.config)}
    return {s: data.load(insts[s], interval).candles for s in symbols if s in insts}


def job_news(ctx: dict) -> dict:
    from nexus import news
    db = ctx["db"]
    rep = news.ingest(db)
    syms = sorted({a for e in news.latest(db, 200) for a in e["assets"]})
    candles = {s: {"1d": c} for s, c in _candles_of(ctx, syms).items()}
    for s, c in _candles_of(ctx, syms, "1h").items():
        candles.setdefault(s, {})["1h"] = c
    return {"feeds": rep, "reactions_updated": news.track_reactions(db, candles)}


def job_market_moves(ctx: dict) -> dict:
    """Grote bewegingen: laatste dagrendement groter dan 3× de normale beweeglijkheid."""
    from nexus import stats
    from nexus.datasets import universe
    data = ctx["data"]
    moves = []
    for inst in universe(data.config):
        c = data.load(inst, "1d").candles
        if len(c) < 62:
            continue
        rets = [b.close / a.close - 1 for a, b in zip(c[-62:-1], c[-61:])]
        sd = stats.stdev(rets[:-1])
        if sd > 0 and abs(rets[-1]) > 3 * sd:
            moves.append({"symbol": inst.symbol, "ts": c[-1].ts.isoformat(), "return": rets[-1], "z": rets[-1] / sd})
    if moves:
        ctx["db"].audit("jobs", "large_market_moves", {"moves": moves})
        bus = ctx.get("bus")
        if bus:
            bus.publish("market_move", {"moves": moves})
    return {"moves": moves}


def job_risk(ctx: dict) -> dict:
    paper = ctx.get("paper")
    if paper is None:
        return {"skipped": True}
    v = paper.valuation()
    return {"equity_eur": v["equity_eur"], "positions": len(v["positions"]), "kill": ctx["controls"].kill_engaged()}


def job_reconcile(ctx: dict) -> dict:
    paper = ctx.get("paper")
    if paper is None:
        return {"skipped": True}
    r = paper.reconcile()
    if not r.get("ok", True):
        ctx["db"].audit("jobs", "reconcile_mismatch", r)
    return r


def job_evaluate(ctx: dict) -> dict:
    from nexus import council, evolution
    from nexus.db import AgentForecast, DecisionRecord
    db = ctx["db"]
    with db.session() as s:
        syms = sorted({x for x in s.scalars(select(DecisionRecord.symbol).distinct())}
                      | {x for x in s.scalars(select(AgentForecast.symbol).distinct())})
    candles = _candles_of(ctx, syms)
    return {"decisions_measured": evolution.measure(db, candles),
            "forecasts_resolved": council.resolve_forecasts(db, candles)}


def job_report(ctx: dict) -> dict:
    db = ctx["db"]
    from nexus.db import DecisionRecord, Hypothesis, ModelVersion
    with db.session() as s:
        summary = {"decisions": s.query(DecisionRecord).count(),
                   "hypotheses_open": s.query(Hypothesis).filter(Hypothesis.status == "open").count(),
                   "candidates": s.query(ModelVersion).filter(ModelVersion.status == "candidate").count()}
    paper = ctx.get("paper")
    if paper is not None:
        v = paper.valuation()
        summary["paper_equity_eur"] = v["equity_eur"]
        summary["paper_pnl_eur"] = v["pnl_eur"]
    with db.session.begin() as s:
        s.add(ResearchRun(kind="job:daily_report", status="done", summary=summary))
    return summary


def job_evolution(ctx: dict) -> dict:
    from nexus import evolution
    out = evolution.cycle(ctx["db"], ctx["data"], ctx.get("holding_home"))
    with ctx["db"].session.begin() as s:
        s.add(ResearchRun(kind="evolution", status="done", summary={k: out[k] for k in ("observed", "measured", "tested")},
                          report=_jsonable(out)))
    return {"observed": out["observed"], "tested": out["tested"]}


def job_deterioration(ctx: dict) -> dict:
    """Kampioen: rollende Sharpe van de laatste 120 dagen tegen die van de walk-forward-periode."""
    from nexus import alpha, champion, lab, stats
    from nexus.datasets import universe
    from nexus.db import ModelVersion
    db, data = ctx["db"], ctx["data"]
    out = []
    with db.session() as s:
        champs = s.scalars(select(ModelVersion).where(ModelVersion.role == "champion")).all()
    for m in champs:
        sym = m.symbols[0]
        inst = next((i for i in universe(data.config) if i.symbol == sym), None)
        if inst is None or not m.key.startswith("lab:"):
            continue
        ds = data.load(inst, "1d")
        c = ds.candles
        if len(c) < 400:
            continue
        w = champion.lab_weights(m.key.removeprefix("lab:"), m.version, c, sym)
        cost = {sym: alpha.research_costs(data, inst)}
        recent = alpha.simulate_weights({sym: c}, w, cost, len(c) - 120, len(c))
        bench = alpha.simulate_weights({sym: c}, [{sym: 1.0}] * len(c), cost, len(c) - 120, len(c))
        expected = (m.metrics or {}).get("walk_forward", {}).get("sharpe")
        sh, bsh = stats.sharpe(recent.returns, ds.ppy), stats.sharpe(bench.returns, ds.ppy)
        flag = expected is not None and sh < expected - 1.0
        out.append({"model": m.id, "symbol": sym, "recent_sharpe": sh, "benchmark_recent_sharpe": bsh,
                    "expected_sharpe": expected, "deteriorated": flag})
        _ = lab
    if any(x["deteriorated"] for x in out):
        db.audit("jobs", "champion_deterioration", {"models": out})
    return {"champions": out, "note": "rollend venster 120 dagen; signaal pas bij > 1,0 Sharpe onder verwachting"}


def job_discovery(ctx: dict) -> dict:
    from nexus import alpha
    db = ctx["db"]
    ledger = alpha.HoldoutLedger(ctx["research_out"] / "holdout-ledger.jsonl") if ctx.get("research_out") else None
    rep = alpha.discover(ctx["data"], "1d", ledger=ledger)
    with db.session.begin() as s:
        s.add(ResearchRun(kind="discovery", interval="1d", status="done", summary=rep["summary"], report=_jsonable(rep)))
    for r in rep["results"]:
        if r["status"] == "holdout_passed":
            from nexus.evolution import register_candidate
            register_candidate(db, r["family"], r["symbols"], r["interval"], r["frozen_params"],
                               {"walk_forward": r["walk_forward"], "holdout": r["holdout"]},
                               notes=f"ontdekkingsrun {rep['run']}")
    return rep["summary"]


def job_arena(ctx: dict) -> dict:
    from nexus import champion
    rep = champion.arena(ctx["data"], "IWDA.AS")
    with ctx["db"].session.begin() as s:
        s.add(ResearchRun(kind="arena", interval="1d", status="done",
                          summary={"symbol": "IWDA.AS", "passed_dev_gates": rep.get("passed_dev_gates", [])}, report=_jsonable(rep)))
    return {"passed_dev_gates": rep.get("passed_dev_gates", [])}


def job_council(ctx: dict) -> dict:
    from nexus import council
    syms = ctx.get("council_symbols") or ()
    if not syms:
        return {"skipped": True, "reason": "geen NEXUS_COUNCIL_SYMBOLS"}
    from nexus.datasets import universe
    data = ctx["data"]
    insts = {i.symbol: i for i in universe(data.config)}
    out, cost, reqs = [], 0.0, 0
    for s in syms:
        if s not in insts:
            continue
        r = council.convene(ctx["db"], s, insts[s].asset_class.value, data.load(insts[s], "1d").candles)
        out.append({"symbol": s, "status": r["status"], "action": (r.get("decision") or {}).get("action")})
        cost += r.get("cost_usd") or 0
        reqs += 0 if r["status"] != "done" or r.get("cached") else len(r["debate"]) + 1
    return {"runs": out, "ai_cost_usd": cost, "ai_requests": reqs}


def job_central(ctx: dict) -> dict:
    from nexus import central
    out = central.step(ctx["db"], ctx)
    return {**out, "ai_cost_usd": sum((r.get("cost_usd") or 0) for r in out["ran"])}


def job_briefing(ctx: dict) -> dict:
    from nexus import central
    b = central.briefing(ctx["db"], ctx)
    return {"day": b["day"], "actions": len(b["actions"]), "missing": b["missing"]}


def job_providers(ctx: dict) -> dict:
    """Verbindingstest van alle externe bronnen (zonder sleutel wordt er niets verstuurd)."""
    from nexus import providers
    rows = providers.check_all(ctx["db"])
    return {"ok": sum(r["status"] == "ok" for r in rows), "total": len(rows),
            "errors": {r["provider"]: r["error_class"] for r in rows if r["status"] != "ok"}}


def job_security(ctx: dict) -> dict:
    """Integriteit van het auditlog en de live-poort."""
    v = ctx["db"].verify_audit_chain()
    live = ctx["controls"].mode() == "live" if ctx.get("controls") else False
    if not v["ok"]:
        ctx["db"].audit("security", "audit_chain_broken", v)
        raise RuntimeError(f"auditketen gebroken bij regel {v['broken_at']}")
    return {"audit_chain": v, "live_mode": live}


def job_social(ctx: dict) -> dict:
    from nexus import social
    db = ctx["db"]
    checks = [{"symbol": t.symbol, "status": social.check_token(db, t)["status"]} for t in social.WATCHLIST if t.address]
    snaps = []
    if social.x_status()["connected"]:
        snaps = [{"topic": r["topic"], "status": r["status"]} for r in (social.snapshot(db, t) for t in social.WATCHLIST)]
    return {"token_checks": checks, "x": social.x_status(), "snapshots": snaps}


JOBS: list[Job] = [
    Job("central", "hourly", "NEXUS Central: taken plannen en uitvoeren, escalaties", job_central, uses_ai=True),
    Job("social", "hourly", "Meme-radar: on-chain veiligheid en X-metingen (als verbonden)", job_social),
    Job("briefing", "daily", "CEO-briefing", job_briefing),
    Job("providers", "hourly", "Verbindingstest van alle externe bronnen en AI-aanbieders", job_providers),
    Job("security", "daily", "Hash-keten van het auditlog controleren", job_security),
    Job("news", "hourly", "Nieuws ophalen en koersreacties bijwerken", job_news),
    Job("market_moves", "hourly", "Grote marktbewegingen signaleren (>3× normale beweeglijkheid)", job_market_moves),
    Job("risk_monitor", "hourly", "Paper-risico en noodstop bewaken", job_risk),
    Job("reconcile", "daily", "Paper-administratie reconciliëren", job_reconcile),
    Job("evaluate", "daily", "Besluiten en agent-voorspellingen afrekenen", job_evaluate),
    Job("daily_report", "daily", "Prestatierapport", job_report),
    Job("council", "daily", "AI Council voor ingestelde instrumenten (binnen dagbudget)", job_council, uses_ai=True),
    Job("evolution", "weekly", "Leerronde: fouten, hypothesen, toetsen", job_evolution),
    Job("deterioration", "weekly", "Verslechtering van de kampioen", job_deterioration),
    Job("discovery", "monthly", "Volledige ontdekkingsrun met holdout-register", job_discovery),
    Job("arena", "monthly", "Champion-challenger-arena IWDA", job_arena),
]

__all__ = ["JOBS", "run_due", "overview", "math"]

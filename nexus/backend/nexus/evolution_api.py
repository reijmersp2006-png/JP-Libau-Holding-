"""API van het Evolution Lab: onderzoek, leren, Council, nieuws, modelregister en externe vergelijking.

Lezen mag zonder token. Alles wat rekenwerk start, AI-budget kost, data importeert of een model
promoveert vraagt het admin-token. Geen enkel endpoint verandert live handelen (dat staat uit).
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from nexus import alpha, audit, champion, council, evolution, external, jobs, lab, news
from nexus.datasets import ResearchData, universe
from nexus.db import (DecisionRecord, ExternalBatch, Hypothesis, ModelVersion, ResearchRun, iso, utcnow)

REPO_RESEARCH = Path(__file__).resolve().parents[2] / "research"


class CouncilIn(BaseModel):
    symbol: str = Field(max_length=64)


class PromoteIn(BaseModel):
    target: Literal["paper", "champion"]
    reason: str = Field(min_length=3, max_length=500)


class ImportIn(BaseModel):
    system: str = Field("grok", max_length=48)
    format: Literal["csv", "json"]
    content: str = Field(min_length=2, max_length=5_000_000)
    starting_capital_eur: float | None = Field(None, gt=0)


def _clean(x):
    """JSON zonder NaN/oneindig (die breken de browser)."""
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_clean(v) for v in x]
    return x


def mount(app: FastAPI, *, db, bridge, settings, paper, controls, bus, require_admin, limiter, market_db) -> dict:
    data = ResearchData(bridge.config, market_db, settings.research_db)
    research_out = settings.research_out or Path("nexus-research")
    ledger = alpha.HoldoutLedger(research_out / "holdout-ledger.jsonl")
    ctx = {"db": db, "data": data, "paper": paper, "controls": controls, "bus": bus, "research_out": research_out,
           "holding_home": market_db.parent.parent if market_db else None, "council_symbols": settings.council_symbols}

    def inst_of(symbol: str):
        i = next((i for i in universe(bridge.config) if i.symbol == symbol), None)
        if i is None:
            raise HTTPException(404, f"onbekend instrument {symbol}")
        return i

    def latest_run(kind: str, max_age: timedelta | None = None, symbol: str | None = None) -> ResearchRun | None:
        with db.session() as s:
            q = select(ResearchRun).where(ResearchRun.kind == kind).order_by(ResearchRun.id.desc())
            for r in s.scalars(q.limit(20)):
                if symbol and (r.summary or {}).get("symbol") != symbol:
                    continue
                created = r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=UTC)
                if max_age and datetime.now(tz=UTC) - created > max_age:
                    return None
                return r
        return None

    def arena_for(symbol: str, fresh: bool = False) -> dict:
        r = None if fresh else latest_run("arena", timedelta(days=1), symbol)
        if r is not None:
            return {**r.report, "run_id": r.id, "created_at": iso(r.created_at)}
        rep = _clean(champion.arena(data, symbol, ledger=ledger))
        with db.session.begin() as s:
            row = ResearchRun(kind="arena", interval="1d", status="done",
                              summary={"symbol": symbol, "passed_dev_gates": rep.get("passed_dev_gates", [])}, report=rep)
            s.add(row)
            s.flush()
            rid = row.id
        return {**rep, "run_id": rid, "created_at": datetime.now(tz=UTC).isoformat()}

    # ── overzicht ──────────────────────────────────────────────────────────────────────────
    @app.get("/api/evolution/overview")
    def overview() -> dict:
        with db.session() as s:
            counts = {
                "decisions": s.query(DecisionRecord).count(),
                "decisions_measured": s.query(DecisionRecord).filter(DecisionRecord.outcome_at.is_not(None)).count(),
                "hypotheses": {st: s.query(Hypothesis).filter(Hypothesis.status == st).count()
                               for st in ("open", "testing", "supported", "rejected", "inconclusive")},
                "models": {st: s.query(ModelVersion).filter(ModelVersion.status == st).count()
                           for st in ("candidate", "challenger", "paper", "champion", "retired", "rejected")},
            }
        disc = latest_run("discovery")
        return {"counts": counts, "discovery": disc.summary if disc else None,
                "discovery_at": iso(disc.created_at) if disc else None,
                "jobs": jobs.overview(db, jobs.JOBS), "live_trading": False,
                "labels": {"actual": "uitkomsten van echte paper-trades en echte koersen",
                           "simulated": "backtests en historische herhaling van strategieën",
                           "estimate": "onderzoeksschattingen met onzekerheid (bootstrap, kansen)"}}

    # ── onderzoek ──────────────────────────────────────────────────────────────────────────
    @app.get("/api/research/audit")
    def research_audit(symbol: str = "IWDA.AS", strategy: str = "volatility_filter", oos_start: str | None = None) -> dict:
        inst = inst_of(symbol)
        try:
            sp = lab.spec(strategy)
        except KeyError:
            raise HTTPException(404, "onbekende strategie")
        candles = data.raw(symbol, "1d")
        if len(candles) < 400:
            raise HTTPException(422, "te weinig koersgeschiedenis voor een audit")
        a = audit.audit_backtest(sp, inst, candles, bridge.config.costs[inst.asset_class.value], oos_start=oos_start)
        a["findings"] = audit.findings(a)
        a["data_label"] = "SIMULATED" if settings.demo else "HISTORICAL"
        return _clean(a)

    @app.get("/api/research/baseline")
    def research_baseline() -> dict:
        files = sorted((REPO_RESEARCH / "baselines").glob("*.json")) if (REPO_RESEARCH / "baselines").exists() else []
        if not files:
            raise HTTPException(404, "geen ijkpunt gevonden")
        doc = json.loads(files[-1].read_text())
        return {"label": doc["label"], "created_at": doc["created_at"], "method": doc["method"],
                "rows": [{k: r.get(k) for k in ("symbol", "strategy", "version", "passes", "skipped")}
                         | {"oos_return": (r.get("out_of_sample") or {}).get("net_return"),
                            "benchmark_oos_return": (r.get("benchmark_oos") or {}).get("net_return"),
                            "oos_sharpe": (r.get("out_of_sample") or {}).get("sharpe"),
                            "benchmark_oos_sharpe": (r.get("benchmark_oos") or {}).get("sharpe")} for r in doc["rows"]]}

    @app.get("/api/evolution/discovery")
    def discovery_latest() -> dict:
        r = latest_run("discovery")
        if r is None:
            return {"available": False, "families": [_family(f) for f in alpha.FAMILIES]}
        return {"available": True, "run_id": r.id, "created_at": iso(r.created_at), **_clean(r.report),
                "families": [_family(f) for f in alpha.FAMILIES]}

    @app.post("/api/evolution/discovery", dependencies=[Depends(limiter)])
    async def discovery_run(actor: str = Depends(require_admin)) -> dict:
        out = await run_in_threadpool(jobs.run_job, db, next(j for j in jobs.JOBS if j.key == "discovery"), ctx)
        db.audit(actor, "discovery_started", {"status": out["status"]})
        return _clean(out)

    @app.get("/api/evolution/arena")
    async def arena(symbol: str = "IWDA.AS") -> dict:
        inst_of(symbol)
        return await run_in_threadpool(arena_for, symbol)

    @app.get("/api/evolution/hypotheses")
    def hypotheses() -> list[dict]:
        with db.session() as s:
            return [_clean({"id": h.id, "source": h.source, "error_tag": h.error_tag, "title": h.title,
                            "statement": h.statement, "test": h.test, "status": h.status, "evidence": h.evidence,
                            "result": _brief_result(h.result), "created_at": iso(h.created_at),
                            "resolved_at": iso(h.resolved_at)})
                    for h in s.scalars(select(Hypothesis).order_by(Hypothesis.id.desc()))]

    @app.post("/api/evolution/cycle", dependencies=[Depends(limiter)])
    async def cycle(actor: str = Depends(require_admin)) -> dict:
        out = await run_in_threadpool(jobs.run_job, db, next(j for j in jobs.JOBS if j.key == "evolution"), ctx)
        db.audit(actor, "evolution_cycle", {"status": out["status"]})
        return _clean(out)

    @app.get("/api/evolution/memory")
    def memory(symbol: str | None = None, kind: str | None = None, tag: str | None = None, q: str | None = None,
               limit: int = 100) -> dict:
        with db.session() as s:
            query = select(DecisionRecord).order_by(DecisionRecord.ts.desc())
            if symbol:
                query = query.where(DecisionRecord.symbol == symbol)
            if kind:
                query = query.where(DecisionRecord.kind == kind)
            if q:
                like = f"%{q}%"
                query = query.where(or_(DecisionRecord.explanation.ilike(like), DecisionRecord.reject_reason.ilike(like),
                                        DecisionRecord.strategy_key.ilike(like)))
            rows = s.scalars(query.limit(2000)).all()
        if tag:
            rows = [r for r in rows if tag in (r.error_tags or [])]
        items = [_clean({"id": r.id, "ts": iso(r.ts), "symbol": r.symbol, "kind": r.kind, "source": r.source,
                         "side": r.side, "strategy": r.strategy_key, "version": r.strategy_version,
                         "regime": (r.regime or {}).get("label"), "price": r.price, "size_eur": r.size_eur,
                         "est_costs_eur": r.est_costs_eur, "outcome": r.outcome, "error_tags": r.error_tags,
                         "explanation": r.explanation, "reject_reason": r.reject_reason,
                         "data_label": (r.actual or {}).get("data_label", "ACTUAL" if r.source != "backtest" else "SIMULATED")})
                 for r in rows[:max(1, min(limit, 500))]]
        return {"total": len(rows), "items": items, "analysis": _clean(evolution.analyze(db))}

    @app.get("/api/evolution/models")
    def models() -> list[dict]:
        with db.session() as s:
            return [_clean({"id": m.id, "key": m.key, "version": m.version, "symbols": m.symbols, "interval": m.interval,
                            "params": m.params, "status": m.status, "role": m.role, "gates": m.gates,
                            "metrics": _brief_metrics(m.metrics), "notes": m.notes, "parent_id": m.parent_id,
                            "approved_by": m.approved_by, "approved_at": iso(m.approved_at),
                            "created_at": iso(m.created_at)})
                    for m in s.scalars(select(ModelVersion).order_by(ModelVersion.id.desc()))]

    @app.post("/api/evolution/models/{mid}/promote", dependencies=[Depends(limiter)])
    async def promote(mid: int, body: PromoteIn, actor: str = Depends(require_admin)) -> dict:
        with db.session() as s:
            m = s.get(ModelVersion, mid)
            if m is None:
                raise HTTPException(404, "onbekend model")
            key, sym = m.key, (m.symbols or [""])[0]
        rep = await run_in_threadpool(arena_for, sym)
        ch = next((c for c in rep.get("challengers", []) if c["family"] == key), None)
        if ch is None:
            raise HTTPException(409, "dit model staat niet in de arena; alleen getoetste uitdagers kunnen promoveren")
        need = ["1_backtest", "2_walk_forward", "3_holdout", "4_costs", "5_sensitivity", "6_monte_carlo"]
        if body.target == "champion":
            need += ["7_paper"]
        missing = [g for g in need if ch["gates"].get(g, {}).get("status") != "pass"]
        if missing:
            db.audit(actor, "promotion_refused", {"model": mid, "target": body.target, "missing": missing})
            raise HTTPException(409, {"error": "poorten niet gehaald", "missing": missing,
                                      "gates": ch["gates"]})
        with db.session.begin() as s:
            m = s.get(ModelVersion, mid)
            prev = None
            if body.target == "champion":
                prev = next((x for x in s.scalars(select(ModelVersion).where(ModelVersion.role == "champion"))
                             if x.id != m.id and sorted(x.symbols or []) == sorted(m.symbols or [])), None)
                if prev is not None:
                    prev.role, prev.status, prev.updated_at = None, "retired", utcnow()
                    m.parent_id = prev.id
                m.role = "champion"
            m.status, m.gates = body.target, ch["gates"]
            m.approved_by, m.approved_at, m.updated_at = actor, utcnow(), utcnow()
            db.audit(actor, "model_promoted", {"model": mid, "target": body.target, "reason": body.reason,
                                               "replaced": prev.id if prev else None, "live_trading": False}, s=s)
        return {"ok": True, "model": mid, "status": body.target, "live_trading": False}

    @app.post("/api/evolution/models/{mid}/rollback", dependencies=[Depends(limiter)])
    def rollback(mid: int, body: PromoteIn | None = None, actor: str = Depends(require_admin)) -> dict:
        with db.session.begin() as s:
            m = s.get(ModelVersion, mid)
            if m is None or m.role != "champion" or m.parent_id is None:
                raise HTTPException(409, "alleen een kampioen met een voorganger kan teruggedraaid worden")
            prev = s.get(ModelVersion, m.parent_id)
            m.role, m.status, m.updated_at = None, "retired", utcnow()
            prev.role, prev.status, prev.updated_at = "champion", "champion", utcnow()
            db.audit(actor, "model_rollback", {"from": mid, "to": prev.id}, s=s)
            return {"ok": True, "champion": prev.id}

    # ── nieuws ─────────────────────────────────────────────────────────────────────────────
    @app.get("/api/news")
    def news_list(category: str | None = None, limit: int = 50) -> dict:
        return {"items": _clean(news.latest(db, max(1, min(limit, 200)), category)),
                "feeds": [{"key": f.key, "name": f.name, "kind": f.kind, "url": f.url} for f in news.FEEDS],
                "event_study": _clean(news.event_study(db))}

    @app.post("/api/news/ingest", dependencies=[Depends(limiter)])
    async def news_ingest(actor: str = Depends(require_admin)) -> dict:
        out = await run_in_threadpool(jobs.run_job, db, next(j for j in jobs.JOBS if j.key == "news"), ctx)
        return _clean(out)

    # ── Council ────────────────────────────────────────────────────────────────────────────
    @app.get("/api/council/agents")
    def council_agents() -> dict:
        w = council.weights(db)
        return {"model": council.MODEL, "daily_budget_usd": council.daily_budget(),
                "spent_today_usd": council.spent_today(db), "key_present": settings.anthropic_key_present,
                "agents": [{"key": a.key, "name": a.name, "kind": a.kind, "responsibilities": a.responsibilities,
                            "inputs": a.inputs, "limitations": a.limitations, "asset_classes": a.asset_classes,
                            "weight": w.get(a.key)} for a in council.AGENTS],
                "scorecard": _clean(council.scorecard(db)), "combinations": _clean(council.signal_combinations(db))}

    @app.get("/api/council/runs")
    def council_runs(limit: int = 10) -> list[dict]:
        return _clean(council.runs(db, max(1, min(limit, 50))))

    @app.post("/api/council/run", dependencies=[Depends(limiter)])
    async def council_run(body: CouncilIn, actor: str = Depends(require_admin)) -> dict:
        inst = inst_of(body.symbol)
        candles = data.load(inst, "1d").candles
        rep = None
        try:
            rep = await run_in_threadpool(arena_for, body.symbol)
            research = {"champion": rep.get("champion"), "buy_hold": rep.get("buy_hold"),
                        "challengers": [{k: c[k] for k in ("family", "walk_forward", "gates_passed", "status")}
                                        for c in rep.get("challengers", [])[:5]],
                        "passed_dev_gates": rep.get("passed_dev_gates", [])}
        except Exception:  # noqa: BLE001 - zonder onderzoek draait de Council met minder context
            research = {"available": False}
        try:
            v = paper.valuation()
            port = {"equity_eur": v["equity_eur"], "cash_eur": v["cash_eur"], "positions": v["positions"]}
        except Exception:  # noqa: BLE001
            port = {}
        out = await run_in_threadpool(council.convene, db, body.symbol, inst.asset_class.value, candles,
                                      _clean(research), _clean(port))
        bus.publish("council", {"id": out["id"], "symbol": body.symbol, "status": out["status"]})
        return _clean(out)

    # ── externe vergelijking ───────────────────────────────────────────────────────────────
    @app.post("/api/external/import", dependencies=[Depends(limiter)])
    def external_import(body: ImportIn, actor: str = Depends(require_admin)) -> dict:
        try:
            parsed = external.parse(body.content, body.format)
        except (ValueError, json.JSONDecodeError) as e:
            raise HTTPException(422, f"bestand niet te lezen: {e}")
        with db.session.begin() as s:
            b = ExternalBatch(system=body.system, fmt=body.format, completeness=parsed["completeness"],
                              meta={"starting_capital_eur": body.starting_capital_eur, "aggregate": parsed["aggregate"]},
                              trades=[{**t, "ts": t["ts"].isoformat()} for t in parsed["trades"]], issues=parsed["issues"])
            s.add(b)
            s.flush()
            bid = b.id
            db.audit(actor, "external_import", {"batch": bid, "system": body.system, "trades": len(parsed["trades"]),
                                                "completeness": parsed["completeness"]}, s=s)
        return {"id": bid, "completeness": parsed["completeness"], "trades": len(parsed["trades"]),
                "issues": parsed["issues"]}

    @app.get("/api/external")
    def external_list() -> list[dict]:
        with db.session() as s:
            return [{"id": b.id, "system": b.system, "format": b.fmt, "completeness": b.completeness,
                     "trades": len(b.trades or []), "uploaded_at": iso(b.uploaded_at), "issues": b.issues}
                    for b in s.scalars(select(ExternalBatch).order_by(ExternalBatch.id.desc()))]

    @app.get("/api/external/{bid}/compare")
    def external_compare(bid: int) -> dict:
        with db.session() as s:
            b = s.get(ExternalBatch, bid)
            if b is None:
                raise HTTPException(404, "onbekende import")
            ext = {"completeness": b.completeness, "aggregate": (b.meta or {}).get("aggregate"), "issues": b.issues,
                   "trades": [{**t, "ts": datetime.fromisoformat(t["ts"])} for t in b.trades or []]}
            cap = (b.meta or {}).get("starting_capital_eur")
        nx = external.trades_from_executions(paper.executions(limit=10_000))
        v = paper.valuation()
        res = external.compare(ext, nx, v.get("starting_cash") or 1000.0, "NEXUS paper-account (echte paper-vullingen)",
                               external_capital=cap)
        return _clean(res)

    # ── taken en audit ─────────────────────────────────────────────────────────────────────
    @app.get("/api/jobs")
    def jobs_list() -> list[dict]:
        return _clean(jobs.overview(db, jobs.JOBS))

    @app.post("/api/jobs/{key}/run", dependencies=[Depends(limiter)])
    async def job_run(key: str, actor: str = Depends(require_admin)) -> dict:
        job = next((j for j in jobs.JOBS if j.key == key), None)
        if job is None:
            raise HTTPException(404, "onbekende taak")
        out = await run_in_threadpool(jobs.run_job, db, job, ctx)
        db.audit(actor, "job_run", {"job": key, "status": out["status"]})
        return _clean(out)

    @app.get("/api/audit/verify")
    def audit_verify() -> dict:
        return db.verify_audit_chain()

    return ctx


def _family(f: alpha.Family) -> dict:
    return {"key": f.key, "name": f.name, "group": f.group, "kind": f.kind, "asset_classes": f.asset_classes,
            "grid": f.grid, "trials": len(f.combos()) if f.kind != "unavailable" else 0, "hypothesis": f.hypothesis,
            "data_needs": f.data_needs, "unavailable_reason": f.unavailable_reason}


def _brief_result(r: dict | None) -> dict | None:
    if not r:
        return r
    out = {k: r.get(k) for k in ("best", "p_better_than_baseline", "beats_buy_hold", "model_version_id", "reason")}
    cands = []
    for c in r.get("candidates", []):
        cands.append({"family": c["family"], "frozen_params": c.get("frozen_params"),
                      "sharpe": (c.get("walk_forward") or {}).get("sharpe"),
                      "baseline_sharpe": (c.get("baseline_walk_forward") or {}).get("sharpe"),
                      "buy_hold_sharpe": (c.get("buy_hold") or {}).get("sharpe"),
                      "net_return": (c.get("walk_forward") or {}).get("net_return"),
                      "baseline_net_return": (c.get("baseline_walk_forward") or {}).get("net_return"),
                      "buy_hold_net_return": (c.get("buy_hold") or {}).get("net_return"),
                      "max_drawdown": (c.get("walk_forward") or {}).get("max_drawdown"),
                      "p_vs_baseline": (c.get("vs_baseline") or {}).get("p_sharpe_better"),
                      "p_vs_buy_hold": (c.get("vs_buy_hold") or {}).get("p_sharpe_better")})
    out["candidates"] = cands
    return out


def _brief_metrics(m: dict | None) -> dict:
    if not m:
        return {}
    wf = m.get("walk_forward") or {}
    return {"sharpe": wf.get("sharpe"), "net_return": wf.get("net_return"), "max_drawdown": wf.get("max_drawdown"),
            "p_vs_baseline": (m.get("vs_baseline") or {}).get("p_sharpe_better"),
            "p_vs_buy_hold": (m.get("vs_buy_hold") or {}).get("p_sharpe_better")}

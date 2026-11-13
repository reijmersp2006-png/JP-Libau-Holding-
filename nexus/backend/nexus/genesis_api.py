"""API van Genesis (Milestone E): CEO Control Center voor onderzoek, Prediction Ledger en evaluatie.

Rechten (server-side):
- lezen: zonder token, nooit sleutels of sleutelwaarden;
- onderzoek aanvragen, pauzeren, beoordelen: onderzoekstoken (``NEXUS_RESEARCH_TOKEN``), operator- of admin-token;
- pauze opheffen, vergelijking met AI-kosten, ledger-amendementen: alleen het admin-token (CEO).
Onderzoeksrechten en handelsrechten zijn gescheiden: geen van deze endpoints raakt orders, limieten, modus of noodstop.
Het aantal onderzoeksopdrachten per dag wordt in de database geteld (blijft gelden na een herstart).
"""

from __future__ import annotations

import hmac
import os
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from nexus import agent_specs, ai_gateway, genesis, genesis_eval, ledger, providers
from nexus.db import AiCall, OrchestratorTask, ResearchWorkflow


class ResearchIn(BaseModel):
    subject: str = Field(max_length=32)
    question: str = Field("", max_length=300)
    mode: str = Field("challenger", pattern="^(deterministic|single|challenger|council)$")


class PauseIn(BaseModel):
    reason: str = Field("", max_length=300)


class ArmsIn(BaseModel):
    cap_usd: float = Field(0.0, ge=0, le=50)
    subjects: list[str] | None = Field(None, max_length=20)
    arms: list[str] | None = None


class ReviewIn(BaseModel):
    workflow_id: int
    usefulness: int = Field(ge=1, le=5)
    errors_found: int = Field(0, ge=0, le=50)
    note: str = Field("", max_length=500)


class AmendIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    change: dict


def per_day() -> int:
    try:
        return int(os.environ.get("NEXUS_RESEARCH_PER_DAY", "10"))
    except ValueError:
        return 10


def max_run_usd() -> float:
    try:
        return float(os.environ.get("NEXUS_GENESIS_MAX_RUN_USD", "5"))
    except ValueError:
        return 5.0


def research_guard(require_admin):
    def require_research(request: Request) -> str:
        given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        for env, role in (("NEXUS_RESEARCH_TOKEN", "research"), ("NEXUS_OPERATOR_TOKEN", "operator")):
            tok = os.environ.get(env, "").strip()
            if tok and given and hmac.compare_digest(given.encode(), tok.encode()):
                return role
        return require_admin(request)
    return require_research


def _closes(data):
    return lambda sym: [(c.ts, c.close) for c in data.raw(sym, "1d")]


def mount(app: FastAPI, *, db, ctx: dict, require_admin, limiter) -> None:
    require_research = research_guard(require_admin)

    def gateway() -> ai_gateway.Gateway:
        return ctx["gateway"]

    @app.get("/api/genesis/readiness")
    def readiness() -> dict:
        g = gateway()
        st = {p["key"]: p for p in providers.status(db)}
        return {"ai": ai_gateway.describe(), "providers": [{k: p.get(k) for k in ("key", "name", "group", "state", "missing_env", "last_check", "last_failure_class")}
                                                          for p in st.values()],
                "budget": {"daily_usd": float(os.environ.get("NEXUS_AI_DAILY_BUDGET_USD", "3.0")),
                           "left_usd": round(g.budget_left(), 4), "max_run_usd": max_run_usd()},
                "pause": ai_gateway.paused(db), "research_per_day": per_day(),
                "roles": [{k: r[k] for k in ("key", "name", "kind", "status", "code_status", "ai_status")} for r in agent_specs.audit(db)],
                "live_trading": False}

    @app.get("/api/genesis/roles")
    def roles() -> dict:
        return {"roles": agent_specs.audit(db)}

    @app.get("/api/research")
    def research_list(limit: int = 30, include_eval: bool = False) -> dict:
        return {"items": genesis.recent(db, max(1, min(limit, 100)), include_eval), "per_day": per_day(),
                "modes": genesis.MODES}

    @app.get("/api/research/estimate")
    def estimate(mode: str = "challenger") -> dict:
        if mode not in genesis.MODES:
            raise HTTPException(422, "onbekende variant")
        g = gateway()
        e = genesis.estimate(g, genesis.plan(mode, True))
        return {**e, "budget_left_usd": round(g.budget_left(), 4),
                "providers": {t: g.route(t) for _, t in genesis.plan(mode, True)}}

    @app.get("/api/research/{trace}")
    def research_one(trace: str) -> dict:
        try:
            return genesis.get(db, trace)
        except KeyError:
            raise HTTPException(404, "onbekende onderzoeksopdracht")

    @app.post("/api/research", dependencies=[Depends(limiter)])
    async def research_create(body: ResearchIn, actor: str = Depends(require_research)) -> dict:
        if body.subject not in genesis.known_symbols(ctx):
            raise HTTPException(404, "onbekend instrument")
        today = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        with db.session() as s:
            n = s.scalar(select(func.count()).select_from(ResearchWorkflow).where(
                ResearchWorkflow.created_at >= today, ResearchWorkflow.eval_run.is_(None))) or 0
        if n >= per_day():
            raise HTTPException(429, f"daglimiet van {per_day()} onderzoeksopdrachten bereikt")
        g = genesis.with_run_cap(gateway(), max_run_usd())
        return await run_in_threadpool(genesis.run, db, ctx, g, body.subject, body.question, body.mode, actor)

    @app.post("/api/research/pause", dependencies=[Depends(limiter)])
    def pause(body: PauseIn, actor: str = Depends(require_research)) -> dict:
        st = {"paused": True, "by": actor, "reason": body.reason, "at": datetime.now(tz=UTC).isoformat()}
        db.set_state(ai_gateway.RESEARCH_PAUSE_KEY, st)
        db.audit(actor, "research_pause", {"reason": body.reason})
        return st

    @app.post("/api/research/resume", dependencies=[Depends(limiter)])
    def resume(actor: str = Depends(require_admin)) -> dict:
        db.set_state(ai_gateway.RESEARCH_PAUSE_KEY, {"paused": False, "by": actor, "at": datetime.now(tz=UTC).isoformat()})
        db.audit(actor, "research_resume", {})
        return {"paused": False}

    @app.get("/api/ledger")
    def ledger_view() -> dict:
        return ledger.summary(db)

    @app.post("/api/ledger/resolve", dependencies=[Depends(limiter)])
    def ledger_resolve(actor: str = Depends(require_research)) -> dict:
        out = ledger.resolve_due(db, _closes(ctx["data"]))
        db.audit(actor, "ledger_resolve", {"n": len(out)})
        return {"results": out}

    @app.post("/api/ledger/{pid}/amend", dependencies=[Depends(limiter)])
    def ledger_amend(pid: str, body: AmendIn, actor: str = Depends(require_admin)) -> dict:
        try:
            r = ledger.amend(db, pid, actor, body.reason, body.change)
        except KeyError:
            raise HTTPException(404, "onbekende voorspelling")
        except ledger.LedgerError as e:
            raise HTTPException(409, str(e))
        db.audit(actor, "ledger_amend", {"pid": pid})
        return r

    @app.get("/api/genesis/eval")
    def evaluation() -> dict:
        return {"challenger_benchmark": genesis_eval.challenger_benchmark(), "arms": genesis_eval.latest(db),
                "reviews": genesis_eval.review_summary(db)}

    @app.post("/api/genesis/eval/arms", dependencies=[Depends(limiter)])
    async def eval_arms(body: ArmsIn, actor: str = Depends(require_admin)) -> dict:
        if body.cap_usd > max_run_usd():
            raise HTTPException(422, f"kostengrens boven het maximum per run (${max_run_usd():.2f}, NEXUS_GENESIS_MAX_RUN_USD)")
        arms = tuple(a for a in (body.arms or genesis_eval.ARMS) if a in genesis_eval.ARMS)
        subjects = tuple(body.subjects or genesis_eval.DEFAULT_SUBJECTS)
        return await run_in_threadpool(genesis_eval.compare_arms, db, ctx, gateway(), subjects, arms, body.cap_usd, actor)

    @app.get("/api/genesis/review/next")
    def review_next(actor: str = Depends(require_research)) -> dict:
        return {"item": genesis_eval.next_for_review(db, actor)}

    @app.post("/api/genesis/review", dependencies=[Depends(limiter)])
    def review(body: ReviewIn, actor: str = Depends(require_research)) -> dict:
        try:
            return genesis_eval.add_review(db, body.workflow_id, actor, body.usefulness, body.errors_found, body.note)
        except KeyError:
            raise HTTPException(404, "onbekende onderzoeksopdracht")
        except Exception as e:                    # dubbele beoordeling door dezelfde persoon
            raise HTTPException(409, f"al beoordeeld of ongeldig: {type(e).__name__}")

    @app.get("/api/genesis/costs")
    def costs() -> dict:
        with db.session() as s:
            ws = s.scalars(select(ResearchWorkflow).order_by(ResearchWorkflow.id.desc()).limit(500)).all()
            retries = s.scalar(select(func.coalesce(func.sum(AiCall.cost_usd), 0)).where(AiCall.status == "error")) or 0
            n_err = s.scalar(select(func.count()).select_from(AiCall).where(AiCall.status == "error")) or 0
        done = [w for w in ws if w.status in ("done", "partial")]
        useful = [w for w in done if ((w.conclusion or {}).get("confidence") or {}).get("assessed") in ("medium", "high")]
        total = sum(float(w.cost_usd or 0) for w in ws)
        return {"usage": ai_gateway.usage(db), "research_tasks": len(ws), "research_cost_usd": round(total, 6),
                "cost_per_task_usd": round(total / len(ws), 6) if ws else None,
                "useful_conclusions": len(useful),
                "cost_per_useful_conclusion_usd": round(total / len(useful), 6) if useful else None,
                "useful_definition": "afgeronde opdracht met beoordeeld vertrouwen medium of hoog (regel, geen mens)",
                "failed_calls": n_err, "failed_call_cost_usd": round(float(retries), 6)}

    @app.get("/api/genesis/failures")
    def failures() -> dict:
        with db.session() as s:
            ws = s.scalars(select(ResearchWorkflow).where(ResearchWorkflow.status.in_(("failed", "blocked", "partial")))
                           .order_by(ResearchWorkflow.id.desc()).limit(30)).all()
            calls = s.scalars(select(AiCall).where(AiCall.status == "error").order_by(AiCall.id.desc()).limit(30)).all()
            tasks = s.scalars(select(OrchestratorTask).where(OrchestratorTask.status == "failed")
                              .order_by(OrchestratorTask.id.desc()).limit(30)).all()
        return {"workflows": [{"trace_id": w.trace_id, "subject": w.subject, "status": w.status, "mode": w.mode,
                               "problems": [{"step": st["step"], "status": st["status"],
                                             "reason": (st.get("detail") or {}).get("reason") or (st.get("detail") or {}).get("error")}
                                            for st in (w.steps or []) if st.get("status") in ("blocked", "failed", "skipped")]}
                              for w in ws],
                "ai_calls": [{"task": c.task, "provider": c.provider, "error": c.error, "at": c.created_at.isoformat()}
                             for c in calls],
                "tasks": [{"id": t.id, "kind": t.kind, "agent": t.agent, "error": t.error} for t in tasks]}

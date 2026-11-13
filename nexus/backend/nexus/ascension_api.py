"""API van Ascension (5.0): Provider Control Center, AI Gateway, debat, evaluatie-arena en bewaking.

Lezen kan zonder token en geeft nooit sleutels terug (alleen de *namen* van ontbrekende variabelen).
Alles wat een verbinding test, AI kost of een debat start, vraagt het admin-token."""

from __future__ import annotations

import hmac
import os
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from nexus import activation, ai_eval, ai_gateway, debate, ops, providers, workflow


class DebateIn(BaseModel):
    hypothesis_id: int


class CheckIn(BaseModel):
    keys: list[str] | None = None


class LabelIn(BaseModel):
    news_id: int
    label: str


class EvalIn(BaseModel):
    dataset: str = "news-labels-v1"


class WorkflowIn(BaseModel):
    news_id: int | None = None


def operator_guard(require_admin):
    """Operator-rol (stap naar echte gebruikersaccounts): mag verbindingen testen, evalueren en labelen,
    maar geen besluiten nemen, geen modus of kill switch. Het CEO/admin-token mag alles wat de operator mag.
    Server-side gecontroleerd; er bestaat geen endpoint dat sleutels opslaat of teruggeeft."""
    def require_operator(request: Request) -> str:
        tok = os.environ.get("NEXUS_OPERATOR_TOKEN", "").strip()
        given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if tok and given and hmac.compare_digest(given.encode(), tok.encode()):
            return "operator"
        return require_admin(request)
    return require_operator


def mount(app: FastAPI, *, db, ctx: dict, require_admin, limiter) -> ai_gateway.Gateway:
    gateway = ai_gateway.Gateway.from_env(db)
    ctx["gateway"] = gateway
    require_operator = operator_guard(require_admin)

    @app.get("/api/providers")
    def provider_status() -> dict:
        return {"providers": providers.status(db), "simulated": providers.simulated_services(),
                "states": list(providers.STATES), "ai": ai_gateway.describe(),
                "explain": providers.EXPLAIN, "generated_at": datetime.now(tz=UTC).isoformat()}

    @app.post("/api/providers/check", dependencies=[Depends(limiter)])
    async def provider_check(body: CheckIn | None = None, actor: str = Depends(require_operator)) -> dict:
        rows = await run_in_threadpool(providers.check_all, db, keys=(body.keys if body else None))
        db.audit(actor, "providers_checked", {"n": len(rows), "ok": sum(r["status"] == "ok" for r in rows)})
        return {"results": rows}

    @app.get("/api/ai/gateway")
    def gateway_view() -> dict:
        return {"providers": ai_gateway.describe(),
                "policies": {k: {"providers": list(p.providers), "purpose": p.purpose, "effort": p.effort,
                                 "timeout_s": p.timeout_s} for k, p in gateway.policies.items()},
                "deterministic_only": sorted(ai_gateway.DETERMINISTIC_ONLY),
                "routes": {k: [{"provider": p, "status": why} for p, why in gateway.route(k)] for k in gateway.policies},
                "usage_30d": ai_gateway.usage(db), "spent_today_usd": gateway.spent_today(),
                "budget_left_usd": gateway.budget_left()}

    @app.get("/api/ai/debates")
    def debates(limit: int = 20) -> list[dict]:
        return debate.recent(db, max(1, min(limit, 50)))

    @app.post("/api/ai/debate", dependencies=[Depends(limiter)])
    async def start_debate(body: DebateIn, actor: str = Depends(require_admin)) -> dict:
        try:
            subject, facts, quant = debate.facts_for_hypothesis(db, body.hypothesis_id)
        except KeyError:
            raise HTTPException(404, "onbekende hypothese")
        out = await run_in_threadpool(debate.run, db, gateway, subject, facts, quant, f"hypothesis:{body.hypothesis_id}")
        db.audit(actor, "debate", {"id": out["id"], "status": out["status"]})
        return out

    @app.get("/api/ai/eval")
    def evaluation() -> dict:
        return {"latest": ai_eval.latest(db), "calibration": ai_eval.calibration(db)}

    @app.post("/api/ai/eval", dependencies=[Depends(limiter)])
    async def run_eval(body: EvalIn | None = None, actor: str = Depends(require_operator)) -> dict:
        ds = body.dataset if body else "news-labels-v1"
        if ds not in ("news-labels-v1", ai_eval.CEO_SET):
            raise HTTPException(400, "onbekende dataset")
        out = await run_in_threadpool(ai_eval.news_benchmark, db, gateway, dataset=ds)
        db.audit(actor, "ai_eval", {"benchmark": out["benchmark"]})
        return out

    @app.get("/api/eval/status")
    def eval_status() -> dict:
        return {"labels": ai_eval.label_status(db), "evidence": ai_eval.evidence_quality(db),
                "reliability": ai_eval.reliability(db)}

    @app.get("/api/eval/label-queue")
    def label_queue(limit: int = 20, actor: str = Depends(require_operator)) -> dict:
        return {"items": ai_eval.label_queue(db, max(1, min(limit, 50))), "labels": ai_eval.load()["labels"]}

    @app.post("/api/eval/labels", dependencies=[Depends(limiter)])
    def add_label(body: LabelIn, actor: str = Depends(require_operator)) -> dict:
        try:
            out = ai_eval.add_label(db, body.news_id, body.label, "ceo" if actor == "admin" else "operator")
        except ValueError as e:
            raise HTTPException(400, str(e))
        except KeyError:
            raise HTTPException(404, "onbekend of fixture-bericht")
        db.audit(actor, "news_label", {"news_id": body.news_id})
        return out

    @app.get("/api/activation/council")
    def activation_latest() -> dict:
        return {"latest": activation.latest(db)}

    @app.post("/api/activation/council", dependencies=[Depends(limiter)])
    async def activation_run(actor: str = Depends(require_admin)) -> dict:
        out = await run_in_threadpool(activation.council_activation, db, gateway, ctx)
        db.audit(actor, "activation_council", {"status": out["status"]})
        return out

    @app.get("/api/workflows")
    def workflows(limit: int = 30) -> dict:
        return {"items": workflow.recent(db, max(1, min(limit, 100))), "total": workflow.count(db),
                "ai_per_day": workflow.ai_per_day()}

    @app.get("/api/workflows/{wid}")
    def workflow_one(wid: int) -> dict:
        try:
            return workflow.get(db, wid)
        except KeyError:
            raise HTTPException(404, "onbekende workflow")

    @app.post("/api/workflows/run", dependencies=[Depends(limiter)])
    async def workflow_run(body: WorkflowIn | None = None, actor: str = Depends(require_admin)) -> dict:
        ids = [body.news_id] if body and body.news_id else workflow.pending(db)
        out = []
        for nid in ids[:workflow.MAX_PER_RUN]:
            try:
                out.append(await run_in_threadpool(workflow.run, db, ctx, nid))
            except KeyError:
                raise HTTPException(404, "onbekend bericht")
        db.audit(actor, "event_workflow_run", {"n": len(out)})
        return {"ran": out}

    @app.get("/api/ops/health")
    def health() -> dict:
        return ops.health(db, ctx, gateway)

    return gateway

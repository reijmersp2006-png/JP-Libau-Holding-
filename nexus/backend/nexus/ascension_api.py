"""API van Ascension (5.0): Provider Control Center, AI Gateway, debat, evaluatie-arena en bewaking.

Lezen kan zonder token en geeft nooit sleutels terug (alleen de *namen* van ontbrekende variabelen).
Alles wat een verbinding test, AI kost of een debat start, vraagt het admin-token."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from nexus import ai_eval, ai_gateway, debate, ops, providers


class DebateIn(BaseModel):
    hypothesis_id: int


class CheckIn(BaseModel):
    keys: list[str] | None = None


def mount(app: FastAPI, *, db, ctx: dict, require_admin, limiter) -> ai_gateway.Gateway:
    gateway = ai_gateway.Gateway.from_env(db)
    ctx["gateway"] = gateway

    @app.get("/api/providers")
    def provider_status() -> dict:
        return {"providers": providers.status(db), "ai": ai_gateway.describe(),
                "explain": providers.EXPLAIN, "generated_at": datetime.now(tz=UTC).isoformat()}

    @app.post("/api/providers/check", dependencies=[Depends(limiter)])
    async def provider_check(body: CheckIn | None = None, actor: str = Depends(require_admin)) -> dict:
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
    async def run_eval(actor: str = Depends(require_admin)) -> dict:
        out = await run_in_threadpool(ai_eval.news_benchmark, db, gateway)
        db.audit(actor, "ai_eval", {"benchmark": out["benchmark"]})
        return out

    @app.get("/api/ops/health")
    def health() -> dict:
        return ops.health(db, ctx, gateway)

    return gateway

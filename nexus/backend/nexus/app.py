"""De NEXUS API (FastAPI). Lezen mag zonder token; alles wat de besturing verandert staat in
de audit-log. De noodstop aanzetten mag altijd; uitzetten en de modus wijzigen vraagt het
admin-token (``NEXUS_ADMIN_TOKEN``). Zonder token ingesteld zijn die acties uitgeschakeld."""

from __future__ import annotations

import hmac
import logging
import time
from collections import defaultdict, deque

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from nexus import __version__
from nexus import agents as agents_mod
from nexus.bridge import HoldingBridge
from nexus.controls import Controls, LiveTradingDisabled, Mode
from nexus.db import Database, iso, RiskEvaluation, TradeProposal
from nexus.guardian import RiskGuardian, limits_from_env
from nexus.proposals import TradeProposalIn
from nexus.settings import Settings
from nexus.views import command_center, connections, controls_view, risk_utilization

log = logging.getLogger("nexus")


class RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self.hits: dict[str, deque] = defaultdict(deque)

    def __call__(self, request: Request) -> None:
        key = request.client.host if request.client else "?"
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            raise HTTPException(429, "te veel verzoeken, probeer het over een minuut opnieuw")
        q.append(now)


class KillIn(BaseModel):
    reason: str = Field("handmatig via NEXUS", max_length=500)


class ModeIn(BaseModel):
    mode: Mode
    reason: str = Field("", max_length=500)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    db = Database(settings.database_url)
    bridge = HoldingBridge(settings)
    controls = Controls(db, bridge.home() if not settings.demo else settings.demo_home)
    guardian = RiskGuardian(limits_from_env())
    limiter = RateLimiter(settings.rate_limit_per_minute)

    app = FastAPI(title="NEXUS AI", version=__version__,
                  description="Controlelaag boven op de JP-libau Holding. Live handelen staat uit.")
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["GET", "POST"],
                       allow_headers=["Authorization", "Content-Type"])
    app.state.settings, app.state.db, app.state.bridge = settings, db, bridge
    app.state.controls, app.state.guardian = controls, guardian

    def require_admin(request: Request) -> str:
        if not settings.admin_token:
            raise HTTPException(503, "NEXUS_ADMIN_TOKEN is niet ingesteld: deze actie is uitgeschakeld")
        auth = request.headers.get("authorization", "")
        token = auth.removeprefix("Bearer ").strip()
        if not hmac.compare_digest(token.encode(), settings.admin_token.encode()):
            raise HTTPException(401, "ongeldig of ontbrekend admin-token")
        return "admin"

    def snapshot():
        try:
            return bridge.snapshot()
        except Exception:                       # een kapotte bron mag de API nooit laten crashen
            log.exception("holding-stand ophalen mislukt")
            return None

    def proposals_list(limit: int = 20) -> list[dict]:
        with db.session() as s:
            rows = s.scalars(select(TradeProposal).order_by(TradeProposal.id.desc()).limit(limit)).all()
            evals = {e.proposal_id: e for e in s.scalars(
                select(RiskEvaluation).where(RiskEvaluation.proposal_id.in_([r.id for r in rows]))).all()}
            return [{"id": r.id, "created_at": iso(r.created_at), "source": r.source, "symbol": r.symbol,
                     "asset_class": r.asset_class, "direction": r.direction, "strategy_id": r.strategy_id,
                     "status": r.status, "executed": r.executed, "proposal": r.payload,
                     "verdict": {"approved": evals[r.id].approved, "reason": evals[r.id].reason,
                                 "checks": evals[r.id].checks} if r.id in evals else None} for r in rows]

    @app.get("/api/health")
    def health() -> dict:
        snap = snapshot()
        return {"status": "ok", "version": __version__, "environment": "demo" if settings.demo else
                ("paper" if snap else "unconfigured"), "holding_data": snap is not None,
                "live_trading": False, "kill": controls.kill_engaged()}

    @app.get("/api/command-center")
    def get_command_center() -> dict:
        return command_center(snapshot(), controls, settings, guardian.limits, proposals_list(10))

    @app.get("/api/agents")
    def get_agents() -> dict:
        items = agents_mod.council(snapshot())
        return {"summary": agents_mod.summary(items), "items": items}

    @app.get("/api/risk")
    def get_risk() -> dict:
        snap = snapshot()
        return {"limits": guardian.limits.describe(), "utilization": risk_utilization(snap, guardian.limits) if snap else [],
                "controls": controls_view(controls),
                "holding_limits": {"max_drawdown_pct": bridge.config.risk.max_drawdown_pct,
                                   "daily_loss_limit_pct": bridge.config.risk.daily_loss_limit_pct,
                                   "max_position_pct": bridge.config.risk.max_position_pct,
                                   "max_invested_pct": bridge.config.risk.max_invested_pct,
                                   "max_trades_per_day": bridge.config.risk.max_trades_per_day,
                                   "max_data_age_hours": bridge.config.risk.max_data_age_hours,
                                   "max_class_pct": bridge.config.risk.max_class_pct}}

    @app.get("/api/connections")
    def get_connections() -> list[dict]:
        return connections(snapshot(), settings)

    @app.get("/api/controls")
    def get_controls() -> dict:
        return controls_view(controls)

    @app.post("/api/controls/kill", dependencies=[Depends(limiter)])
    def kill(body: KillIn) -> dict:
        status = controls.engage_kill("api", body.reason)
        bridge.invalidate()
        log.warning("NOODSTOP AAN: %s", body.reason)
        return status

    @app.post("/api/controls/kill/release", dependencies=[Depends(limiter)])
    def release(body: KillIn, actor: str = Depends(require_admin)) -> dict:
        status = controls.release_kill(actor, body.reason)
        bridge.invalidate()
        return status

    @app.post("/api/controls/mode", dependencies=[Depends(limiter)])
    def set_mode(body: ModeIn, actor: str = Depends(require_admin)) -> dict:
        try:
            controls.set_mode(body.mode, actor)
        except LiveTradingDisabled as e:
            raise HTTPException(403, {"error": "live handelen is uitgeschakeld in deze versie", "gate": e.gate})
        return controls_view(controls)

    @app.get("/api/proposals")
    def get_proposals(limit: int = 50) -> list[dict]:
        return proposals_list(min(max(limit, 1), 200))

    @app.post("/api/proposals", dependencies=[Depends(limiter)])
    def submit_proposal(p: TradeProposalIn) -> dict:
        """Laat de Risk Guardian een voorstel beoordelen en legt alles vast. Er wordt NIETS
        uitgevoerd: uitvoeren van NEXUS-voorstellen komt in fase 5 (paper) en 6 (live)."""
        with db.session() as s:
            existing = s.scalar(select(TradeProposal).where(TradeProposal.idempotency_key == p.idempotency_key))
            if existing is not None:
                return {"id": existing.id, "duplicate": True, "status": existing.status}
        snap = snapshot()
        verdict = guardian.evaluate(p, snap.portfolio_view() if snap else None, controls.mode(),
                                    controls.kill_engaged())
        try:
            with db.session.begin() as s:
                row = TradeProposal(idempotency_key=p.idempotency_key, source=p.source, asset_class=p.asset_class,
                                    symbol=p.symbol, direction=p.direction, strategy_id=p.strategy_id,
                                    payload=p.model_dump(), executed=False,
                                    status="approved_by_guardian" if verdict.approved else "vetoed")
                s.add(row)
                s.flush()
                s.add(RiskEvaluation(proposal_id=row.id, approved=verdict.approved, reason=verdict.reason,
                                     checks=verdict.to_dict()["checks"], limits_snapshot=guardian.limits.__dict__))
                db.audit(p.source, "proposal_evaluated",
                         {"proposal_id": row.id, "symbol": p.symbol, "approved": verdict.approved}, s=s)
                pid = row.id
        except IntegrityError:                    # gelijktijdig dubbel ingestuurd
            raise HTTPException(409, "voorstel met deze idempotency_key bestaat al")
        return {"id": pid, "duplicate": False, "executed": False, **verdict.to_dict()}

    @app.get("/api/audit")
    def audit(limit: int = 100) -> list[dict]:
        return db.audit_entries(min(max(limit, 1), 500))

    return app

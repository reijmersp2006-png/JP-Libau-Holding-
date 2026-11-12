"""De NEXUS API (FastAPI).

Grenzen tussen diensten (allemaal in dit proces voor de persoonlijke MVP, los te trekken later):
- bridge      leest de holding-bots (alleen lezen)
- marketdata  bronnen met herkomst, sessie en kwaliteit
- lab         strategieën en backtests
- paper       gesimuleerd account, orders, vullingen, reconciliatie
- guardian    vetorecht over elk voorstel; zonder goedkeuring geen order
- controls    modus, noodstop, live-poort

Lezen mag zonder token. De noodstop aanzetten mag altijd; uitzetten en de modus wijzigen vraagt
het admin-token (``NEXUS_ADMIN_TOKEN``). Geen enkel endpoint kan echt geld bewegen.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import time
from collections import defaultdict, deque
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from nexus import __version__
from nexus import agents as agents_mod
from nexus import evolution_api, jobs, lab, sentinel_api, social
from nexus.bridge import HoldingBridge
from nexus.controls import Controls, LiveTradingDisabled, Mode
from nexus.db import (DEFAULT_ORG, Backtest, BillingRecord, Database, Organization, RiskEvaluation, StrategyRow,
                      StrategyVersion, SubscriptionPlan, TradeProposal, User, iso)
from nexus.events import EventBus
from nexus.guardian import Check, RiskGuardian, limits_from_env
from nexus.marketdata import REGISTRY, MarketData
from nexus.paper import PaperEngine, quote_from_store
from nexus.proposals import TradeProposalIn
from nexus.provenance import DataLabel
from nexus.settings import Settings
from nexus.views import command_center, connections, controls_view, risk_utilization

log = logging.getLogger("nexus")
STARTED = time.time()

LEGAL_GATE = [
    {"item": "Juridische toets MiFID II (beleggingsadvies, vermogensbeheer, orderuitvoering)", "done": False},
    {"item": "Juridische toets MiCA (cryptodiensten)", "done": False},
    {"item": "AFM: vergunning of vrijstelling", "done": False},
    {"item": "AVG/GDPR: verwerkingsregister, DPIA, verwerkersovereenkomsten", "done": False},
    {"item": "Algemene voorwaarden en risicowaarschuwingen", "done": False},
]


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


class BacktestIn(BaseModel):
    strategy: str = Field(max_length=64)
    version: int | None = None
    symbol: str = Field(max_length=64)
    spread_pct: float = Field(0.001, ge=0, le=0.05)
    oos_fraction: float = Field(0.3, ge=0.1, le=0.5)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    db = Database(settings.database_url)
    bridge = HoldingBridge(settings)
    home = bridge.home() if not settings.demo else settings.demo_home
    if settings.demo:
        bridge.home()                                   # demo-wereld bouwen als die er nog niet is
    controls = Controls(db, home)
    guardian = RiskGuardian(limits_from_env())
    limiter = RateLimiter(settings.rate_limit_per_minute)
    market = MarketData(bridge.config)
    market_db = home / "data" / "holding.sqlite3" if home else None
    paper = PaperEngine(db, bridge.config, quote_from_store(market_db, bridge.config, settings.demo),
                        controls.kill_engaged)
    bus = EventBus()
    errors = {"5xx": 0, "requests": 0}
    evo: dict = {}

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        bus.loop = asyncio.get_running_loop()
        tasks = [asyncio.create_task(worker())] if settings.worker else []
        if settings.worker and settings.jobs:
            tasks.append(asyncio.create_task(job_worker()))
        yield
        for t in tasks:
            t.cancel()

    async def worker():
        """Achtergrondronde: open paper-orders aanvullen en de waardering vastleggen."""
        while True:
            try:
                fills = await run_in_threadpool(paper.step)
                for f in fills:
                    bus.publish("fill", f)
                await run_in_threadpool(paper.valuation, DEFAULT_ORG, None, True)
            except Exception:
                log.exception("worker-ronde mislukt")
            await asyncio.sleep(settings.worker_seconds)

    async def job_worker():
        """Geplande onderzoekstaken, los van de paper-ronde zodat zware runs geen vullingen ophouden.
        Nooit live handelen; AI-taken blijven binnen het dagbudget."""
        await asyncio.sleep(30)
        while True:
            try:
                if "ctx" in evo:
                    for r in await run_in_threadpool(jobs.run_due, db, jobs.JOBS, evo["ctx"]):
                        bus.publish("job", {"job": r["job"], "status": r["status"]})
            except Exception:
                log.exception("takenronde mislukt")
            await asyncio.sleep(300)

    app = FastAPI(title="NEXUS AI", version=__version__, lifespan=lifespan,
                  description="Intelligence Behind Every Trade. Paper trading; live handelen staat uit.")
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["GET", "POST"],
                       allow_headers=["Authorization", "Content-Type"])
    app.state.settings, app.state.db, app.state.bridge = settings, db, bridge
    app.state.controls, app.state.guardian, app.state.paper, app.state.market = controls, guardian, paper, market
    app.state.bus = bus

    @app.middleware("http")
    async def count(request: Request, call_next):
        errors["requests"] += 1
        try:
            resp = await call_next(request)
        except Exception:
            errors["5xx"] += 1
            raise
        if resp.status_code >= 500:
            errors["5xx"] += 1
        return resp

    def require_admin(request: Request) -> str:
        if not settings.admin_token:
            raise HTTPException(503, "NEXUS_ADMIN_TOKEN is niet ingesteld: deze actie is uitgeschakeld")
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
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
            rows = s.scalars(select(TradeProposal).where(TradeProposal.org_id == DEFAULT_ORG)
                             .order_by(TradeProposal.id.desc()).limit(limit)).all()
            evals = {e.proposal_id: e for e in s.scalars(
                select(RiskEvaluation).where(RiskEvaluation.proposal_id.in_([r.id for r in rows]))).all()}
            return [{"id": r.id, "created_at": iso(r.created_at), "source": r.source, "symbol": r.symbol,
                     "asset_class": r.asset_class, "direction": r.direction, "strategy_id": r.strategy_id,
                     "status": r.status, "executed": r.executed, "proposal": r.payload,
                     "verdict": {"approved": evals[r.id].approved, "reason": evals[r.id].reason,
                                 "checks": evals[r.id].checks} if r.id in evals else None} for r in rows]

    # ── algemeen ───────────────────────────────────────────────────────────────────────────
    @app.get("/api/health")
    def health() -> dict:
        snap = snapshot()
        return {"status": "ok", "version": __version__, "environment": "demo" if settings.demo else
                ("paper" if snap else "unconfigured"), "holding_data": snap is not None,
                "live_trading": False, "kill": controls.kill_engaged(), "uptime_s": round(time.time() - STARTED)}

    @app.get("/api/command-center")
    def get_command_center() -> dict:
        out = command_center(snapshot(), controls, settings, guardian.limits, proposals_list(10))
        try:
            v = paper.valuation()
            out["nexus_paper"] = {k: v[k] for k in ("equity_eur", "cash_eur", "pnl_eur", "label", "starting_cash")}
            out["nexus_paper"]["positions"] = len(v["positions"])
            out["nexus_paper"]["open_orders"] = sum(1 for o in paper.orders(limit=200)
                                                    if o["status"] in ("new", "partially_filled"))
        except Exception:
            log.exception("paper-waardering mislukt")
            out["nexus_paper"] = None
        return out

    @app.get("/api/agents")
    def get_agents() -> dict:
        items = agents_mod.council(snapshot())
        return {"summary": agents_mod.summary(items), "items": items}

    @app.get("/api/risk")
    def get_risk() -> dict:
        snap = snapshot()
        r = bridge.config.risk
        return {"limits": guardian.limits.describe(),
                "utilization": risk_utilization(snap, guardian.limits) if snap else [],
                "controls": controls_view(controls),
                "holding_limits": {"max_drawdown_pct": r.max_drawdown_pct, "daily_loss_limit_pct": r.daily_loss_limit_pct,
                                   "max_position_pct": r.max_position_pct, "max_invested_pct": r.max_invested_pct,
                                   "max_trades_per_day": r.max_trades_per_day, "max_data_age_hours": r.max_data_age_hours,
                                   "max_class_pct": r.max_class_pct}}

    @app.get("/api/connections")
    def get_connections() -> list[dict]:
        return connections(snapshot(), settings)

    # ── besturing ──────────────────────────────────────────────────────────────────────────
    @app.get("/api/controls")
    def get_controls() -> dict:
        return controls_view(controls)

    @app.post("/api/controls/kill", dependencies=[Depends(limiter)])
    def kill(body: KillIn) -> dict:
        status = controls.engage_kill("api", body.reason)
        bridge.invalidate()
        bus.publish("kill", status)
        log.warning("NOODSTOP AAN: %s", body.reason)
        return status

    @app.post("/api/controls/kill/release", dependencies=[Depends(limiter)])
    def release(body: KillIn, actor: str = Depends(require_admin)) -> dict:
        status = controls.release_kill(actor, body.reason)
        bridge.invalidate()
        bus.publish("kill", status)
        return status

    @app.post("/api/controls/mode", dependencies=[Depends(limiter)])
    def set_mode(body: ModeIn, actor: str = Depends(require_admin)) -> dict:
        try:
            controls.set_mode(body.mode, actor)
        except LiveTradingDisabled as e:
            raise HTTPException(403, {"error": "live handelen is uitgeschakeld in deze versie", "gate": e.gate})
        bus.publish("mode", {"mode": body.mode.value})
        return controls_view(controls)

    # ── voorstellen en paper trading ───────────────────────────────────────────────────────
    @app.get("/api/proposals")
    def get_proposals(limit: int = 50) -> list[dict]:
        return proposals_list(min(max(limit, 1), 200))

    @app.post("/api/proposals", dependencies=[Depends(limiter)])
    def submit_proposal(p: TradeProposalIn) -> dict:
        """De Risk Guardian beoordeelt het voorstel tegen het NEXUS paper-account. Er wordt
        nog niets uitgevoerd; dat gebeurt pas met ``/execute``."""
        with db.session() as s:
            existing = s.scalar(select(TradeProposal).where(TradeProposal.idempotency_key == p.idempotency_key))
            if existing is not None:
                return {"id": existing.id, "duplicate": True, "status": existing.status}
        try:
            view = paper.view()
        except Exception:
            log.exception("paper-account niet te waarderen")
            view = None
        verdict = guardian.evaluate(p, view, controls.mode(), controls.kill_engaged())
        if p.asset_class == "meme" and p.direction == "buy":
            # Verplichte on-chain veiligheidscontrole: zonder recente geslaagde controle geen aankoop.
            ok, why = social.tradeable(db, p.symbol)
            verdict.checks.append(Check("token_safety", ok, why))
            if not ok and verdict.approved:
                verdict.approved, verdict.reason = False, f"token_safety: {why}"
        try:
            with db.session.begin() as s:
                row = TradeProposal(org_id=DEFAULT_ORG, account_id=paper.account_id(), idempotency_key=p.idempotency_key,
                                    source=p.source, asset_class=p.asset_class, symbol=p.symbol, direction=p.direction,
                                    strategy_id=p.strategy_id, payload=p.model_dump(), executed=False,
                                    status="approved_by_guardian" if verdict.approved else "vetoed")
                s.add(row)
                s.flush()
                s.add(RiskEvaluation(proposal_id=row.id, approved=verdict.approved, reason=verdict.reason,
                                     checks=verdict.to_dict()["checks"], limits_snapshot=guardian.limits.__dict__))
                db.audit(p.source, "proposal_evaluated",
                         {"proposal_id": row.id, "symbol": p.symbol, "approved": verdict.approved}, s=s)
                pid = row.id
        except IntegrityError:
            raise HTTPException(409, "voorstel met deze idempotency_key bestaat al")
        bus.publish("proposal", {"id": pid, "approved": verdict.approved})
        return {"id": pid, "duplicate": False, "executed": False, **verdict.to_dict()}

    @app.post("/api/proposals/{pid}/execute", dependencies=[Depends(limiter)])
    def execute(pid: int) -> dict:
        """Zet een goedgekeurd voorstel om in een PAPER-order. Kan nooit echt geld raken."""
        if controls.mode() is not Mode.PAPER:
            raise HTTPException(409, f"uitvoeren kan alleen in paper-modus (nu: {controls.mode().value})")
        if controls.kill_engaged():
            raise HTTPException(423, "noodstop staat aan")
        with db.session() as s:
            prop = s.get(TradeProposal, pid)
            if prop is None or prop.org_id != DEFAULT_ORG:
                raise HTTPException(404, "onbekend voorstel")
            ev = s.scalar(select(RiskEvaluation).where(RiskEvaluation.proposal_id == pid)
                          .order_by(RiskEvaluation.id.desc()).limit(1))
            if ev is None or not ev.approved:
                raise HTTPException(409, "de Risk Guardian heeft dit voorstel niet goedgekeurd")
            args = dict(proposal_id=pid, evaluation_id=ev.id, key=prop.idempotency_key, symbol=prop.symbol,
                        asset_class=prop.asset_class, side=prop.direction, size_eur=prop.payload["size_eur"])
        try:
            order = paper.submit(**args)
        except (PermissionError, ValueError) as e:
            raise HTTPException(409, str(e))
        fills = paper.step()
        with db.session.begin() as s:
            prop = s.get(TradeProposal, pid)
            prop.executed, prop.status = True, "executed"
        for f in fills:
            bus.publish("fill", f)
        return {**order, "fills": [f for f in fills if f["order_id"] == order["order_id"]]}

    @app.post("/api/paper/step", dependencies=[Depends(limiter)])
    def paper_step() -> dict:
        fills = paper.step()
        for f in fills:
            bus.publish("fill", f)
        return {"fills": fills}

    @app.post("/api/paper/orders/{oid}/cancel", dependencies=[Depends(limiter)])
    def cancel(oid: int) -> dict:
        try:
            return {"status": paper.cancel(oid)}
        except KeyError:
            raise HTTPException(404, "onbekende order")

    @app.get("/api/paper")
    def paper_overview() -> dict:
        return {"account": paper.valuation(), "orders": paper.orders(), "executions": paper.executions(),
                "reconciliation": paper.reconcile(), "live_enabled": False,
                "settings": {"participation": paper.participation, "spread_pct": paper.spread_pct}}

    # ── marktdata ──────────────────────────────────────────────────────────────────────────
    @app.get("/api/market/providers")
    def providers() -> list[dict]:
        return [p.__dict__ | {"asset_classes": list(p.asset_classes)} for p in REGISTRY]

    @app.get("/api/market/series")
    def series(symbol: str, interval: str = "1h", limit: int = 200) -> dict:
        if interval not in ("1h", "1d"):
            raise HTTPException(422, "interval moet 1h of 1d zijn")
        try:
            return market.series(symbol, interval, min(max(limit, 2), 1000)).to_dict()
        except KeyError as e:
            raise HTTPException(404, str(e))

    # ── Strategy Lab ───────────────────────────────────────────────────────────────────────
    def _version_row(s, sp: lab.StrategySpec) -> StrategyVersion:
        st = s.scalar(select(StrategyRow).where(StrategyRow.org_id.is_(None), StrategyRow.key == sp.key))
        if st is None:
            st = StrategyRow(org_id=None, key=sp.key, family=sp.family, description=sp.name)
            s.add(st)
            s.flush()
        sv = s.scalar(select(StrategyVersion).where(StrategyVersion.strategy_id == st.id,
                                                    StrategyVersion.version == sp.version))
        if sv is None:
            spec = sp.to_dict()
            sv = StrategyVersion(strategy_id=st.id, version=sp.version, params=sp.params, spec=spec, status=sp.status)
            s.add(sv)
            s.flush()
        return sv

    def _bt_summary(b: Backtest, key: str, version: int) -> dict:
        r = b.result
        return {"id": b.id, "created_at": iso(b.created_at), "strategy": key, "version": version, "symbol": b.symbol,
                "data_label": b.data_label, "passes": r["passes"], "verdict": r["verdict"],
                "oos": {k: r["out_of_sample"].get(k) for k in ("net_return", "sharpe", "max_drawdown", "trades")},
                "benchmark_oos": {k: r["benchmark"]["out_of_sample"].get(k) for k in ("net_return", "sharpe", "max_drawdown")}}

    @app.get("/api/strategies")
    def strategies() -> dict:
        with db.session() as s:
            rows = s.execute(select(Backtest, StrategyRow.key, StrategyVersion.version)
                             .join(StrategyVersion, Backtest.strategy_version_id == StrategyVersion.id)
                             .join(StrategyRow, StrategyVersion.strategy_id == StrategyRow.id)
                             .where(Backtest.org_id == DEFAULT_ORG).order_by(Backtest.id.desc()).limit(50)).all()
            runs = [_bt_summary(b, k, v) for b, k, v in rows]
        syms = [i.symbol for i in bridge.config.instruments]
        return {"strategies": [sp.to_dict() for sp in lab.SPECS], "symbols": syms, "runs": runs}

    @app.post("/api/backtests", dependencies=[Depends(limiter)])
    def run_backtest(body: BacktestIn) -> dict:
        try:
            sp = lab.spec(body.strategy, body.version)
            inst = bridge.config.instrument(body.symbol)
        except KeyError as e:
            raise HTTPException(404, str(e).strip("'"))
        if market_db is None or not market_db.exists():
            raise HTTPException(503, "geen koersgeschiedenis gekoppeld (NEXUS_HOLDING_HOME of NEXUS_DEMO)")
        from jplh.store import Store
        st = Store(market_db)
        try:
            candles = st.candles(body.symbol, "1d")
        finally:
            st.close()
        try:
            result = lab.run_backtest(sp, inst, candles, bridge.config.costs[inst.asset_class.value],
                                      spread_pct=body.spread_pct, oos_fraction=body.oos_fraction)
        except ValueError as e:
            raise HTTPException(422, str(e))
        label = DataLabel.SIMULATED.value if settings.demo else DataLabel.HISTORICAL.value
        result["data_label"] = label
        with db.session.begin() as s:
            sv = _version_row(s, sp)
            b = Backtest(org_id=DEFAULT_ORG, strategy_version_id=sv.id, symbol=body.symbol, interval="1d",
                         data_label=label, settings=body.model_dump(), result=result)
            s.add(b)
            s.flush()
            db.audit("lab", "backtest_run", {"backtest_id": b.id, "strategy": sp.key, "symbol": body.symbol,
                                             "passes": result["passes"]}, s=s)
            result["id"] = b.id
        return result

    @app.get("/api/backtests/{bid}")
    def get_backtest(bid: int) -> dict:
        with db.session() as s:
            b = s.get(Backtest, bid)
            if b is None or b.org_id != DEFAULT_ORG:
                raise HTTPException(404, "onbekende backtest")
            return {**b.result, "id": b.id, "data_label": b.data_label, "created_at": iso(b.created_at)}

    # ── SaaS-administratie ─────────────────────────────────────────────────────────────────
    @app.get("/api/admin/overview")
    def admin_overview() -> dict:
        with db.session() as s:
            plans = [{"key": p.key, "name": p.name, "price_eur": p.price_eur_cents / 100, "trial_days": p.trial_days,
                      "limits": p.limits, "active": p.active} for p in s.scalars(select(SubscriptionPlan)
                                                                                 .order_by(SubscriptionPlan.price_eur_cents))]
            users = s.scalar(select(func.count()).select_from(User)) or 0
            orgs = s.scalar(select(func.count()).select_from(Organization)) or 0
            paid = s.scalar(select(func.count()).select_from(BillingRecord).where(BillingRecord.status == "paid")) or 0
        return {"plans": plans, "organizations": orgs, "users": users, "paid_invoices": paid,
                "billing_connected": False, "mrr_eur": None, "churn": None, "conversion": None,
                "ai_cost_eur": None, "market_data_cost_eur": 0.0,
                "uptime_s": round(time.time() - STARTED), "requests": errors["requests"], "errors_5xx": errors["5xx"],
                "legal_gate": LEGAL_GATE, "customer_features_enabled": False}

    @app.get("/api/audit")
    def audit(limit: int = 100) -> list[dict]:
        return db.audit_entries(min(max(limit, 1), 500))

    # ── realtime ───────────────────────────────────────────────────────────────────────────
    @app.websocket("/ws/events")
    async def events(ws: WebSocket) -> None:
        origin = ws.headers.get("origin")
        if origin and origin not in settings.cors_origins:
            await ws.close(code=1008)
            return
        await ws.accept()
        q = bus.subscribe()
        try:
            await ws.send_json({"ts": datetime.now(tz=UTC).isoformat(), "kind": "hello",
                                "data": {"kill": controls.kill_engaged(), "mode": controls.mode().value}})
            while True:
                await ws.send_text(await q.get())
        except WebSocketDisconnect:
            pass
        finally:
            bus.unsubscribe(q)

    evo["ctx"] = (evolution_api.mount(app, db=db, bridge=bridge, settings=settings, paper=paper, controls=controls,
                                   bus=bus, require_admin=require_admin, limiter=limiter, market_db=market_db))
    sentinel_api.mount(app, db=db, ctx=evo["ctx"], settings=settings, require_admin=require_admin, limiter=limiter)
    return app

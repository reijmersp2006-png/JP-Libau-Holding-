"""API van Sentinel (4.0): NEXUS Central, HQ, beslissingstijdlijn, briefing, News Reactor, Social Radar,
Market Pulse, holdout-status en de CEO Copilot. Lezen zonder token; alles wat iets start of AI kost vraagt
het admin-token. Niets hier plaatst orders of verandert limieten."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from nexus import alpha, central, copilot, holdout, news, social, stats
from nexus.datasets import universe
from nexus.db import OrchestratorTask


class DecideIn(BaseModel):
    decision: Literal["acknowledge", "cancel"]
    note: str = Field(min_length=2, max_length=500)


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)


def _clean(x):
    if isinstance(x, float):
        return None if not math.isfinite(x) else x
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_clean(v) for v in x]
    if isinstance(x, datetime):
        return x.isoformat()
    return x


def pulse(data, now: datetime | None = None) -> list[dict]:
    """Echte laatste dagkoersen per instrument met 1d/7d/30d en beweeglijkheid; label op versheid."""
    now = now or datetime.now(tz=UTC)
    out = []
    for inst in universe(data.config):
        c = data.raw(inst.symbol, "1d")
        if len(c) < 31:
            out.append({"symbol": inst.symbol, "asset_class": inst.asset_class.value, "label": "UNAVAILABLE"})
            continue
        rets = [b.close / a.close - 1 for a, b in zip(c[-61:], c[-60:])]
        age = (now - c[-1].ts).total_seconds() / 86400
        out.append({"symbol": inst.symbol, "asset_class": inst.asset_class.value, "currency": inst.currency,
                    "last": c[-1].close, "ts": c[-1].ts.isoformat(),
                    "ret_1d": c[-1].close / c[-2].close - 1, "ret_7d": c[-1].close / c[-8].close - 1,
                    "ret_30d": c[-1].close / c[-31].close - 1, "vol_annual": stats.stdev(rets) * math.sqrt(252),
                    "move_z": (c[-1].close / c[-2].close - 1) / (stats.stdev(rets) or 1),
                    "spark": [x.close for x in c[-30:]],
                    "label": "DELAYED" if age <= 4 else "HISTORICAL"})
    return out


def mount(app: FastAPI, *, db, ctx: dict, settings, require_admin, limiter) -> None:
    data = ctx["data"]

    @app.get("/api/central/org")
    def org() -> dict:
        return _clean({"departments": central.DEPARTMENTS, "roles": central.organization(db),
                       "ai": {"key_present": settings.anthropic_key_present}, "live_trading": False})

    @app.get("/api/central/tasks")
    def tasks(status: str | None = None, limit: int = 100) -> list[dict]:
        return _clean(central.tasks(db, status, max(1, min(limit, 300))))

    @app.post("/api/central/step", dependencies=[Depends(limiter)])
    async def step(actor: str = Depends(require_admin)) -> dict:
        out = await run_in_threadpool(central.step, db, ctx)
        db.audit(actor, "central_step", {"created": out["created"], "ran": len(out["ran"])})
        return _clean(out)

    @app.post("/api/central/tasks/{tid}/decide", dependencies=[Depends(limiter)])
    def decide(tid: int, body: DecideIn, actor: str = Depends(require_admin)) -> dict:
        try:
            return central.decide(db, tid, actor, body.decision, body.note)
        except KeyError:
            raise HTTPException(404, "onbekende taak")
        except central.InvalidTransition as e:
            raise HTTPException(409, str(e))

    @app.get("/api/central/timeline")
    def timeline(limit: int = 15) -> list[dict]:
        return _clean(central.timeline(db, max(1, min(limit, 50))))

    @app.get("/api/central/briefing")
    def briefing() -> dict:
        b = central.latest_briefing(db)
        today = datetime.now(tz=UTC).date().isoformat()
        if b is None or b.get("day") != today:
            b = {**central.briefing(db, ctx, save=False), "draft": True}
        return _clean(b)

    @app.post("/api/central/briefing", dependencies=[Depends(limiter)])
    def briefing_new(actor: str = Depends(require_admin)) -> dict:
        return _clean(central.briefing(db, ctx))

    @app.get("/api/news/reactor")
    def reactor(limit: int = 60) -> dict:
        from nexus.jobs import last_run
        lr = last_run(db, "news")
        return _clean({"items": news.latest(db, max(1, min(limit, 200))),
                       "latency": news.latency(db, datetime.now(tz=UTC) - timedelta(days=30)),
                       "feeds": [{"key": f.key, "name": f.name, "kind": f.kind,
                                  "status": ((lr.detail or {}).get("feeds") or {}).get(f.key) if lr else None}
                                 for f in news.FEEDS],
                       "last_fetch": lr.started_at.isoformat() if lr else None,
                       "signal_threshold": news.SIGNAL_THRESHOLD, "event_study": news.event_study(db)})

    @app.get("/api/social/radar")
    def radar() -> dict:
        prices = {t.symbol: data.raw(t.symbol, "1d") for t in social.WATCHLIST}
        return _clean(social.radar(db, prices))

    @app.post("/api/social/refresh", dependencies=[Depends(limiter)])
    async def social_refresh(actor: str = Depends(require_admin)) -> dict:
        from nexus import jobs
        out = await run_in_threadpool(jobs.run_job, db, next(j for j in jobs.JOBS if j.key == "social"), ctx)
        return _clean(out)

    @app.get("/api/pulse")
    def market_pulse() -> dict:
        return _clean({"items": pulse(data), "note": "dagkoersen uit de holding-database; geen streaming"})

    @app.get("/api/holdout/status")
    def holdout_status() -> dict:
        rules = json.loads(holdout.CONTAMINATION_FILE.read_text()) if holdout.CONTAMINATION_FILE.exists() else {}
        led = alpha.HoldoutLedger(ctx["research_out"] / "holdout-ledger.jsonl")
        return {"contamination": rules.get("entries", []), "evaluations": len(led.entries()),
                "min_prospective_days": holdout.MIN_PROSPECTIVE_DAYS}

    @app.post("/api/copilot/ask", dependencies=[Depends(limiter)])
    async def ask(body: AskIn, actor: str = Depends(require_admin)) -> dict:
        out = await run_in_threadpool(copilot.ask, db, body.question, ctx)
        tid = central.enqueue(db, "copilot", "cio", f"vraag: {body.question[:200]}", status="queued")
        with db.session.begin() as s:
            t = s.get(OrchestratorTask, tid)
            central.move(t, "running")
            central.move(t, "done", out["mode"])
            t.result, t.cost_usd = {"topic": out["topic"], "refs": out["refs"]}, out["cost_usd"]
        return _clean(out)

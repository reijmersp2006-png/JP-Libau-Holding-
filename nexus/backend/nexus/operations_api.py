"""API voor Master Prompt 8.0: NEXUS leest de stand van JP-Libau Holding en bewaart onderzoeksrecords.

Rechten (server-side, zelfde tokens als Genesis):
- lezen (snapshot, records): zonder token; er staan geen sleutels of besturingsvelden in;
- onderzoek aanvragen: onderzoekstoken (``NEXUS_RESEARCH_TOKEN``), operator- of admin-token.
Geen van deze endpoints raakt orders, limieten, pauzes, modus of noodstop. Bronvolgorde voor de snapshot:
``NEXUS_HOLDING_SNAPSHOT`` (een ``snapshot.json``), anders ``NEXUS_HOLDING_HOME`` (alleen-lezen geopend).
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from nexus import operations
from nexus.genesis_api import research_guard


class OpsResearchIn(BaseModel):
    scope: str = Field("holding", pattern="^(holding|crypto|meme|stocks|metals|fx)$")
    question: str = Field("", max_length=300)


def mount(app: FastAPI, *, db, settings, require_admin, limiter, gateway=None) -> None:
    require_research = research_guard(require_admin)

    def source() -> dict:
        path = os.environ.get("NEXUS_HOLDING_SNAPSHOT")
        return {"path": Path(path).expanduser() if path else None, "home": settings.holding_home}

    def snapshot() -> dict:
        src = source()
        if src["path"] is None and src["home"] is None:
            raise HTTPException(503, "NOT CONNECTED: geen NEXUS_HOLDING_SNAPSHOT of NEXUS_HOLDING_HOME ingesteld")
        try:
            return operations.load(path=src["path"], home=src["home"])
        except operations.SnapshotError as e:
            raise HTTPException(503, f"BLOCKED: {e}") from e

    @app.get("/api/ops/snapshot")
    def ops_snapshot() -> dict:
        snap = snapshot()
        from datetime import UTC, datetime
        return {"snapshot": snap, "freshness": operations.freshness(snap, datetime.now(tz=UTC), operations.max_age_hours())}

    @app.get("/api/ops/research")
    def ops_list(limit: int = 20) -> dict:
        return {"items": operations.recent(db, max(1, min(limit, 100)))}

    @app.get("/api/ops/research/{trace}")
    def ops_one(trace: str) -> dict:
        try:
            return operations.get(db, trace)
        except KeyError:
            raise HTTPException(404, "onbekend onderzoeksrecord")

    @app.get("/api/ops/export")
    def ops_export() -> dict:
        return operations.export(db)

    @app.post("/api/ops/research", dependencies=[Depends(limiter)])
    async def ops_create(body: OpsResearchIn, actor: str = Depends(require_research)) -> dict:
        snap = await run_in_threadpool(snapshot)
        g = gateway() if callable(gateway) else gateway
        return await run_in_threadpool(lambda: operations.run(db, snap, scope=body.scope, question=body.question,
                                                              requested_by=actor, gateway=g,
                                                              max_age_hours=operations.max_age_hours()))

"""API van Milestone D (Apex): Trading Workstation, Market Pulse, agentdossier en overdrachten.

Alleen lezen, zonder token: deze endpoints veranderen niets en kosten geen AI-budget."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool

from nexus import workstation


def _simulated(x):
    """Demo-omgeving: alle koersen zijn synthetisch, dus elk versheidslabel wordt SIMULATED (nooit DELAYED)."""
    if isinstance(x, dict):
        return {k: ("SIMULATED" if k == "label" and v in ("DELAYED", "HISTORICAL") else _simulated(v)) for k, v in x.items()}
    if isinstance(x, list):
        return [_simulated(v) for v in x]
    return x


def mount(app: FastAPI, *, db, ctx: dict, demo: bool = False) -> None:
    data = ctx["data"]
    honest = _simulated if demo else (lambda x: x)

    @app.get("/api/workstation/universe")
    async def ws_universe() -> dict:
        items = await run_in_threadpool(workstation.universe_view, data)
        return honest({"items": items, "quality": workstation.QUALITY, "demo": demo,
                       "note": "Alleen tijdschalen met opgeslagen candles worden getoond; er is geen streaming."})

    @app.get("/api/workstation/asset")
    async def ws_asset(symbol: str, interval: str = "1d", limit: int = 750) -> dict:
        try:
            return honest(await run_in_threadpool(workstation.asset, db, data, symbol, interval, limit))
        except KeyError:
            raise HTTPException(404, "onbekend instrument")
        except ValueError as e:
            raise HTTPException(422, str(e))

    @app.get("/api/market/overview")
    async def market_overview() -> dict:
        return honest(await run_in_threadpool(workstation.overview, data))

    @app.get("/api/hq/agents/{key}")
    def agent(key: str) -> dict:
        try:
            return workstation.agent(db, key)
        except KeyError:
            raise HTTPException(404, "onbekende rol")

    @app.get("/api/hq/handoffs")
    def handoffs() -> dict:
        return workstation.handoffs(db)

"""Gebeurtenissen naar de frontend via WebSocket (noodstop, modus, orders, vullingen).

Fase 1 van de MVP: in-process (één API-proces). Met meerdere processen hoort hier Redis
pub/sub achter; de interface blijft dan gelijk.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime


class EventBus:
    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def publish(self, kind: str, data: dict | None = None) -> None:
        """Mag vanuit elke thread; gebeurtenissen voor trage luisteraars vallen weg (nooit blokkeren)."""
        msg = json.dumps({"ts": datetime.now(tz=UTC).isoformat(), "kind": kind, "data": data or {}}, default=str)
        loop = self.loop
        if loop is None or loop.is_closed():
            return
        for q in list(self._subs):
            loop.call_soon_threadsafe(self._put, q, msg)

    @staticmethod
    def _put(q: asyncio.Queue, msg: str) -> None:
        if not q.full():
            q.put_nowait(msg)

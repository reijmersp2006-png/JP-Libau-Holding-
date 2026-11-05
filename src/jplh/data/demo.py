"""Nep-koersen voor demo en tests. Deterministisch: dezelfde seed geeft dezelfde koersen."""

from __future__ import annotations

import hashlib
import math
import random
from datetime import UTC, datetime, timedelta

from jplh.models import Candle

# Beginprijs en beweeglijkheid per uur, grofweg realistisch per soort.
_PROFILE = {
    "crypto": (50_000.0, 0.008),
    "meme": (0.0001, 0.02),
    "stocks": (200.0, 0.004),
    "metals": (2_400.0, 0.003),
    "fx": (1.08, 0.0008),
}


class Demo:
    name = "demo"

    def __init__(self, asset_class_of: dict[str, str] | None = None, seed: int = 7,
                 end: datetime | None = None) -> None:
        self.asset_class_of = asset_class_of or {}
        self.seed = seed
        self.end = (end or datetime.now(tz=UTC)).replace(minute=0, second=0, microsecond=0)

    def candles(self, symbol: str, interval: str = "1h", limit: int = 200) -> list[Candle]:
        step = timedelta(hours=1) if interval == "1h" else timedelta(days=1)
        start_price, vol = _PROFILE.get(self.asset_class_of.get(symbol, "crypto"), _PROFILE["crypto"])
        digest = hashlib.sha256(f"{self.seed}:{symbol}".encode()).digest()
        rng = random.Random(int.from_bytes(digest[:8], "big"))
        price = start_price * (0.5 + rng.random())
        out = []
        t0 = self.end - step * limit
        for i in range(limit):
            ret = rng.gauss(0.00005, vol)
            o = price
            c = o * math.exp(ret)
            h = max(o, c) * (1 + abs(rng.gauss(0, vol / 2)))
            l = min(o, c) * (1 - abs(rng.gauss(0, vol / 2)))
            out.append(Candle(t0 + step * i, o, h, l, c, rng.uniform(10, 1000)))
            price = c
        return out

    def ping(self) -> str:
        return "nep-data, altijd beschikbaar"

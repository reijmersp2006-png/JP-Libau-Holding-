"""Databronnen. Elke bron heeft ``candles(symbol, interval, limit)`` en ``ping()``."""

from __future__ import annotations

from typing import Protocol

from jplh.data.bitvavo import Bitvavo
from jplh.data.demo import Demo
from jplh.data.dexscreener import DexScreener
from jplh.data.ecb import ECB
from jplh.data.http import DataError
from jplh.data.yahoo import Yahoo
from jplh.models import Candle


class CandleSource(Protocol):
    name: str

    def candles(self, symbol: str, interval: str = "1h", limit: int = 200) -> list[Candle]: ...

    def ping(self) -> str: ...


def live_sources() -> dict[str, CandleSource]:
    return {"bitvavo": Bitvavo(), "yahoo": Yahoo()}


__all__ = ["Bitvavo", "CandleSource", "DataError", "Demo", "DexScreener", "ECB", "Yahoo", "live_sources"]

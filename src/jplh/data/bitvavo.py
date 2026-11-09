"""Openbare koersen van Bitvavo (crypto en memecoins in euro). Geen account nodig.

Endpoint: ``GET https://api.bitvavo.com/v2/{market}/candles?interval=1h&limit=N``
Antwoord: lijst van ``[timestamp_ms, open, high, low, close, volume]``, nieuwste eerst.
"""

from __future__ import annotations

from datetime import UTC, datetime

from jplh.data.http import get_json
from jplh.models import Candle

BASE_URL = "https://api.bitvavo.com/v2"


def parse_candles(payload: list) -> list[Candle]:
    out = [
        Candle(
            ts=datetime.fromtimestamp(row[0] / 1000, tz=UTC),
            open=float(row[1]), high=float(row[2]), low=float(row[3]),
            close=float(row[4]), volume=float(row[5]),
        )
        for row in payload
    ]
    return sorted(out, key=lambda c: c.ts)


class Bitvavo:
    name = "bitvavo"

    def __init__(self, base_url: str = BASE_URL) -> None:
        self.base_url = base_url

    def candles(self, symbol: str, interval: str = "1h", limit: int = 200) -> list[Candle]:
        """Nieuwste ``limit`` candles. Bitvavo geeft er max 1440 per keer, dus bij meer bladeren we terug."""
        out: dict = {}
        end = None
        while len(out) < limit:
            n = min(limit - len(out), 1440)
            url = f"{self.base_url}/{symbol}/candles?interval={interval}&limit={n}"
            if end is not None:
                url += f"&end={end}"
            page = parse_candles(get_json(url))
            new = [c for c in page if c.ts not in out]
            if not new:
                break
            for c in new:
                out[c.ts] = c
            end = int(min(c.ts for c in new).timestamp() * 1000) - 1
            if len(page) < n:
                break
        return sorted(out.values(), key=lambda c: c.ts)[-limit:]

    def ping(self) -> str:
        data = get_json(f"{self.base_url}/time")
        return f"servertijd {datetime.fromtimestamp(data['time'] / 1000, tz=UTC):%Y-%m-%d %H:%M} UTC"

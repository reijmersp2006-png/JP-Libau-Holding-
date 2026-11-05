"""Koersen van Yahoo Finance voor aandelen, goud/zilver en valuta.

Let op: dit is een openbaar maar niet officieel gedocumenteerd endpoint. Het kan
veranderen of tijdelijk weigeren; ``jplh doctor`` laat dat meteen zien.
Endpoint: ``GET https://query1.finance.yahoo.com/v8/finance/chart/{symbol}``
"""

from __future__ import annotations

import urllib.parse
from datetime import UTC, datetime

from jplh.data.http import DataError, get_json
from jplh.models import Candle

BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"

# Welke periode we opvragen per interval (Yahoo staat 1h maar ~730 dagen terug toe).
_RANGE = {"1h": "60d", "1d": "5y"}


def parse_chart(payload: dict) -> list[Candle]:
    chart = payload.get("chart", {})
    if chart.get("error"):
        raise DataError(f"Yahoo-fout: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        return []
    res = results[0]
    stamps = res.get("timestamp") or []
    quote = (res.get("indicators", {}).get("quote") or [{}])[0]
    out = []
    for i, ts in enumerate(stamps):
        o, h, l, c = (quote.get(k, [None] * len(stamps))[i] for k in ("open", "high", "low", "close"))
        if None in (o, h, l, c):
            continue  # Yahoo geeft lege rijen voor uren zonder handel
        v = (quote.get("volume") or [0] * len(stamps))[i] or 0
        out.append(Candle(datetime.fromtimestamp(ts, tz=UTC), float(o), float(h), float(l), float(c), float(v)))
    return out


class Yahoo:
    name = "yahoo"

    def __init__(self, base_url: str = BASE_URL) -> None:
        self.base_url = base_url

    def candles(self, symbol: str, interval: str = "1h", limit: int = 200) -> list[Candle]:
        rng = "1mo" if interval == "1d" and limit <= 20 else _RANGE.get(interval, "60d")
        q = urllib.parse.urlencode({"interval": interval, "range": rng})
        url = f"{self.base_url}/{urllib.parse.quote(symbol)}?{q}"
        candles = parse_chart(get_json(url))
        # De laatste rij is vaak de lopende, nog niet gesloten periode: die laten we weg.
        if candles and interval == "1h":
            now = datetime.now(tz=UTC)
            if (now - candles[-1].ts).total_seconds() < 3600:
                candles = candles[:-1]
        return candles[-limit:]

    def ping(self) -> str:
        n = len(self.candles("EURUSD=X", "1d", 5))
        return f"{n} dagkoersen EUR/USD ontvangen"

"""Koersen verzamelen voor alle afdelingen en opslaan."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from jplh.config import HoldingConfig
from jplh.data import CandleSource, DataError, DexScreener, ECB
from jplh.store import Store

RADAR_QUERIES = ("PEPE", "BONK", "WIF", "DOGE")


@dataclass
class CollectResult:
    symbol: str
    ok: bool
    new: int = 0
    error: str = ""


def collect_candles(config: HoldingConfig, store: Store, sources: dict[str, CandleSource],
                    interval: str = "1h", limit: int = 200, now: datetime | None = None) -> list[CollectResult]:
    now = now or datetime.now(tz=UTC)
    results = []
    for inst in config.instruments:
        src = sources.get(inst.source)
        if src is None:
            results.append(CollectResult(inst.symbol, False, error=f"onbekende bron {inst.source}"))
            continue
        try:
            candles = src.candles(inst.symbol, interval, limit)
            # Nooit een candle opslaan die op dit moment nog niet gesloten was.
            candles = [c for c in candles if c.ts < now]
            n = store.save_candles(inst.symbol, interval, candles, src.name, now)
            results.append(CollectResult(inst.symbol, True, n))
        except (DataError, KeyError, ValueError, TypeError) as exc:
            results.append(CollectResult(inst.symbol, False, error=str(exc)))
    return results


def collect_fx_reference(config: HoldingConfig, store: Store, ecb: ECB | None = None,
                         now: datetime | None = None) -> list[CollectResult]:
    ecb = ecb or ECB()
    now = now or datetime.now(tz=UTC)
    out = []
    for cur in sorted({i.currency for i in config.instruments if i.asset_class.value == "fx"}):
        try:
            rows = ecb.rates(cur, 30)
            store.save_fx_reference(cur, rows, now)
            out.append(CollectResult(f"ECB {cur}", True, len(rows)))
        except DataError as exc:
            out.append(CollectResult(f"ECB {cur}", False, error=str(exc)))
    return out


def collect_radar(store: Store, dex: DexScreener | None = None, queries=RADAR_QUERIES,
                  now: datetime | None = None) -> list[CollectResult]:
    dex = dex or DexScreener()
    now = now or datetime.now(tz=UTC)
    out = []
    for q in queries:
        try:
            snaps = dex.search(q)[:10]
            store.save_radar(snaps, now)
            out.append(CollectResult(f"radar {q}", True, len(snaps)))
        except DataError as exc:
            out.append(CollectResult(f"radar {q}", False, error=str(exc)))
    return out

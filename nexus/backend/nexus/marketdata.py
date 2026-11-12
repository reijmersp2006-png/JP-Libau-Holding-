"""Marktdata-laag: één interface voor alle bronnen, met bij elke reeks de bron, het tijdstip,
de munt, de versheid, de marktsessie en een kwaliteitsoordeel.

Echte adapters nu: Bitvavo (crypto, memecoins) en Yahoo Finance (aandelen, metalen, valuta;
onofficieel). Andere bronnen staan in het register met hun status, zodat duidelijk is wat
gekoppeld is en wat niet. Faalt een bron, dan krijg je ``UNAVAILABLE`` met de foutmelding,
nooit een vervangende of verzonnen koers.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from jplh.config import HoldingConfig
from jplh.models import Candle

from nexus.provenance import DataLabel, market_label

INTERVAL = {"1h": timedelta(hours=1), "1d": timedelta(days=1)}


class Provider(Protocol):
    name: str

    def candles(self, symbol: str, interval: str = "1h", limit: int = 200) -> list[Candle]: ...


@dataclass(frozen=True)
class ProviderInfo:
    name: str
    asset_classes: tuple[str, ...]
    status: str            # connected | not_configured | planned
    licence: str
    note: str = ""


REGISTRY: list[ProviderInfo] = [
    ProviderInfo("bitvavo", ("crypto", "meme"), "connected", "publieke API, geen sleutel, rate-limit per IP"),
    ProviderInfo("yahoo", ("stocks", "metals", "fx"), "connected", "onofficieel endpoint, niet voor commercieel gebruik",
                 "vervangen door een gelicentieerde bron vóór commerciële release"),
    ProviderInfo("ecb", ("fx",), "connected", "ECB Data Portal, gratis", "alleen dagelijkse referentiekoersen"),
    ProviderInfo("dexscreener", ("meme",), "connected", "gratis, alleen kijken", "radar, geen handelsbron"),
    ProviderInfo("coingecko", ("crypto", "meme"), "not_configured", "gratis demo-sleutel of betaald plan"),
    ProviderInfo("polygon", ("stocks", "fx"), "not_configured", "betaald", "keuze aandelenbron staat open"),
    ProviderInfo("fmp", ("stocks",), "not_configured", "betaald", "jaarcijfers en winstkalender"),
    ProviderInfo("fred", ("macro",), "not_configured", "gratis sleutel"),
    ProviderInfo("goplus", ("meme",), "planned", "gratis met limieten", "contract- en honeypotchecks"),
]


@dataclass
class MarketSeries:
    symbol: str
    asset_class: str
    source: str
    currency: str
    interval: str
    fetched_at: str
    label: str
    session: str
    quality: str
    issues: list[str] = field(default_factory=list)
    last_ts: str | None = None
    last_close: float | None = None
    bars: list[dict] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# ── Marktsessies ───────────────────────────────────────────────────────────────────────────
AMS, NY = ZoneInfo("Europe/Amsterdam"), ZoneInfo("America/New_York")


def _within(now: datetime, tz: ZoneInfo, start: tuple[int, int], end: tuple[int, int]) -> bool:
    local = now.astimezone(tz)
    if local.weekday() >= 5:
        return False
    minutes = local.hour * 60 + local.minute
    return start[0] * 60 + start[1] <= minutes < end[0] * 60 + end[1]


def session(symbol: str, asset_class: str, now: datetime) -> str:
    """``24/7``, ``open`` of ``closed``. Feestdagen worden (nog) niet meegenomen."""
    if asset_class in ("crypto", "meme"):
        return "24/7"
    if asset_class == "fx":
        u = now.astimezone(UTC)
        closed = (u.weekday() == 4 and u.hour >= 22) or u.weekday() == 5 or (u.weekday() == 6 and u.hour < 22)
        return "closed" if closed else "open"
    if symbol.endswith("=F"):                     # CME-futures: zo-vr, dagelijkse pauze 17-18 uur New York
        local = now.astimezone(NY)
        if local.weekday() == 5 or (local.weekday() == 4 and local.hour >= 17) or (local.weekday() == 6 and local.hour < 18):
            return "closed"
        return "closed" if local.hour == 17 else "open"
    if symbol.endswith(".AS"):
        return "open" if _within(now, AMS, (9, 0), (17, 30)) else "closed"
    return "open" if _within(now, NY, (9, 30), (16, 0)) else "closed"


# ── Kwaliteit ──────────────────────────────────────────────────────────────────────────────
def assess(bars: list[Candle], interval: str, now: datetime, max_age: timedelta, continuous: bool) -> tuple[str, list[str]]:
    """Kwaliteitsoordeel: ``ok``, ``gaps``, ``stale``, ``invalid`` of ``missing`` (ergste wint)."""
    if not bars:
        return "missing", ["geen koersen ontvangen"]
    issues: list[str] = []
    bad = [b for b in bars if min(b.open, b.high, b.low, b.close) <= 0
           or b.high < max(b.open, b.close) - 1e-12 or b.low > min(b.open, b.close) + 1e-12]
    if bad:
        issues.append(f"{len(bad)} candles met onmogelijke OHLC-waarden")
    stamps = [b.ts for b in bars]
    if len(set(stamps)) != len(stamps):
        issues.append("dubbele tijdstempels")
    if any(b2 <= b1 for b1, b2 in zip(stamps, stamps[1:])):
        issues.append("tijdstempels niet oplopend")
    if bad or "dubbele tijdstempels" in issues or "tijdstempels niet oplopend" in issues:
        return "invalid", issues
    step = INTERVAL.get(interval)
    if continuous and step:
        missing = sum(int((b2 - b1) / step) - 1 for b1, b2 in zip(stamps, stamps[1:]) if b2 - b1 > step)
        if missing:
            issues.append(f"{missing} ontbrekende perioden")
    if now - stamps[-1] > max_age + (step or timedelta(0)):
        issues.append(f"laatste koers {(now - stamps[-1]).total_seconds() / 3600:.1f} uur oud")
        return "stale", issues
    return ("gaps" if issues else "ok"), issues


class MarketData:
    """Haalt reeksen op bij de juiste bron, met een korte cache. Nooit een vervangende bron."""

    def __init__(self, config: HoldingConfig, providers: dict[str, Provider] | None = None,
                 cache_seconds: float = 60.0) -> None:
        if providers is None:
            from jplh.data import Bitvavo, Yahoo
            providers = {"bitvavo": Bitvavo(), "yahoo": Yahoo()}
        self.config = config
        self.providers = providers
        self.cache_seconds = cache_seconds
        self._cache: dict[tuple, tuple[float, MarketSeries]] = {}
        self._lock = threading.Lock()

    def series(self, symbol: str, interval: str = "1h", limit: int = 200, now: datetime | None = None) -> MarketSeries:
        key = (symbol, interval, limit)
        with self._lock:
            hit = self._cache.get(key)
            if hit and time.monotonic() - hit[0] < self.cache_seconds:
                return hit[1]
        s = self._fetch(symbol, interval, limit, now or datetime.now(tz=UTC))
        with self._lock:
            self._cache[key] = (time.monotonic(), s)
        return s

    def _fetch(self, symbol: str, interval: str, limit: int, now: datetime) -> MarketSeries:
        try:
            inst = self.config.instrument(symbol)
        except KeyError:
            raise KeyError(f"onbekend instrument {symbol}") from None
        cls = inst.asset_class.value
        base = dict(symbol=symbol, asset_class=cls, source=inst.source, currency=inst.currency, interval=interval,
                    fetched_at=now.isoformat(), session=session(symbol, cls, now))
        provider = self.providers.get(inst.source)
        if provider is None:
            return MarketSeries(**base, label=DataLabel.UNAVAILABLE.value, quality="missing",
                                error=f"bron {inst.source} niet gekoppeld")
        try:
            bars = provider.candles(symbol, interval, limit)
        except Exception as e:                      # bron plat: eerlijk melden, niets invullen
            return MarketSeries(**base, label=DataLabel.UNAVAILABLE.value, quality="missing",
                                issues=["bron gaf een fout"], error=str(e)[:300])
        max_age = timedelta(hours=self.config.risk.max_data_age_hours)
        quality, issues = assess(bars, interval, now, max_age, continuous=cls in ("crypto", "meme"))
        if not bars or quality == "invalid":
            return MarketSeries(**base, label=DataLabel.UNAVAILABLE.value, quality=quality, issues=issues)
        last = bars[-1]
        label = market_label(last.ts, now, max_age)
        return MarketSeries(**base, label=label.value, quality=quality, issues=issues, last_ts=last.ts.isoformat(),
                            last_close=last.close,
                            bars=[{"t": int(b.ts.timestamp()), "o": b.open, "h": b.high, "l": b.low, "c": b.close,
                                   "v": b.volume} for b in bars])

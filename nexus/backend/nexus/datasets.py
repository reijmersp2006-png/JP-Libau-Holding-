"""Koersdata voor onderzoek: welke instrumenten, welke tijdschalen, in welke munt.

- Tijdschalen zijn instelbaar: 5m, 15m, 1h, 4h en 1d. 4h wordt samengesteld uit 1h als de bron
  het niet levert. Alleen volledige perioden tellen; een lopende periode wordt nooit gebruikt.
- Bronnen en hun diepte: Bitvavo levert alle tijdschalen met terugbladeren (crypto in euro);
  Yahoo levert 5m/15m maar ~60 dagen terug, 1h ~730 dagen en 1d jaren (openbaar, ongedocumenteerd
  endpoint, zie DATA-SOURCES.md). Te weinig geschiedenis = geen oordeel, nooit opvullen.
- Munt: een belegger in euro verdient in euro. Koersen in dollar worden omgerekend met de
  EUR/USD-slotkoers die op dat moment al bekend was (nooit een latere koers).
- Onderzoeksdata staat in een eigen database (``NEXUS_RESEARCH_DB``), zodat NEXUS de opslag van
  de holding-bots niet verandert. Lezen gebeurt eerst daar, dan in de opslag van de holding.
"""

from __future__ import annotations

import bisect
import urllib.parse
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jplh.config import HoldingConfig
from jplh.models import AssetClass, Candle, Instrument
from jplh.store import Store

STEP = {"5m": timedelta(minutes=5), "15m": timedelta(minutes=15), "1h": timedelta(hours=1),
        "4h": timedelta(hours=4), "1d": timedelta(days=1)}

# Handelsperioden per jaar per tijdschaal en klasse (voor jaarrendement en Sharpe).
_TRADING_HOURS = {"crypto": 24 * 365, "meme": 24 * 365, "stocks": 252 * 8.5, "metals": 252 * 23, "fx": 260 * 24}
_DAYS = {"crypto": 365, "meme": 365, "stocks": 252, "metals": 252, "fx": 260}


def periods_per_year(interval: str, asset_class: str) -> int:
    if interval == "1d":
        return _DAYS[asset_class]
    return int(_TRADING_HOURS[asset_class] * 3600 / STEP[interval].total_seconds())


# Hoeveel geschiedenis een bron per tijdschaal maximaal levert (None = jaren).
SOURCE_DEPTH = {
    "bitvavo": {"5m": None, "15m": None, "1h": None, "4h": None, "1d": None},
    "yahoo": {"5m": timedelta(days=59), "15m": timedelta(days=59), "1h": timedelta(days=729), "4h": None,
              "1d": None},
}
YAHOO_RANGE = {"5m": "60d", "15m": "60d", "1h": "730d", "1d": "10y"}

# Defensieve en spreidingsbeleggingen (schaduw-afdelingen van de holding, alleen papier).
DEFENSIVE = {"XEON.DE": "geldmarkt", "IEAG.AS": "euro-obligaties"}


@dataclass(frozen=True)
class Dataset:
    inst: Instrument
    interval: str
    candles: list[Candle]
    source: str
    currency: str
    notes: tuple[str, ...] = ()

    @property
    def ppy(self) -> int:
        return periods_per_year(self.interval, self.inst.asset_class.value)


def universe(config: HoldingConfig) -> list[Instrument]:
    """Handelbare instrumenten plus de schaduw-ETF's (in euro, Euronext/Xetra)."""
    out = list(config.instruments)
    seen = {i.symbol for i in out}
    for s in config.shadow:
        if s.symbol not in seen:
            out.append(Instrument(s.symbol, AssetClass.STOCKS, s.source, "EUR"))
    return out


def resample(candles: list[Candle], interval: str) -> list[Candle]:
    """Voegt kleinere candles samen tot ``interval`` (UTC-grenzen). Onvolledige blokken vallen weg."""
    step = STEP[interval]
    secs = int(step.total_seconds())
    buckets: dict[int, list[Candle]] = {}
    for c in candles:
        key = int(c.ts.timestamp()) // secs * secs
        buckets.setdefault(key, []).append(c)
    if not candles:
        return []
    src_step = min((b.ts - a.ts for a, b in zip(candles, candles[1:])), default=step)
    need = max(1, int(step / src_step)) if src_step.total_seconds() > 0 else 1
    out = []
    for key in sorted(buckets):
        g = buckets[key]
        if len(g) < need:
            continue
        out.append(Candle(datetime.fromtimestamp(key, tz=UTC), g[0].open, max(c.high for c in g),
                          min(c.low for c in g), g[-1].close, sum(c.volume for c in g)))
    return out


def to_eur(candles: list[Candle], eurusd: list[Candle]) -> list[Candle]:
    """USD-koersen naar euro. Per candle de laatste EUR/USD-slotkoers die bij het BEGIN van die
    candle al vaststond (een FX-dagkoers staat vast op zijn tijdstempel + 1 dag). Zo gebruikt de
    omrekening nooit een koers die op het besluitmoment nog niet bekend was."""
    known = [(fx.ts + timedelta(days=1), fx.close) for fx in eurusd]
    stamps = [k for k, _ in known]
    out = []
    for c in candles:
        j = bisect.bisect_right(stamps, c.ts) - 1
        if j < 0:
            continue
        r = known[j][1]
        out.append(Candle(c.ts, c.open / r, c.high / r, c.low / r, c.close / r, c.volume))
    return out


class ResearchData:
    def __init__(self, config: HoldingConfig, holding_db: Path | None, research_db: Path | None = None) -> None:
        self.config = config
        self.holding_db = holding_db
        self.research_db = research_db

    def _read(self, path: Path | None, symbol: str, interval: str) -> list[Candle]:
        if path is None or not Path(path).exists():
            return []
        st = Store(path)
        try:
            return st.candles(symbol, interval)
        finally:
            st.close()

    def raw(self, symbol: str, interval: str) -> list[Candle]:
        own = self._read(self.research_db, symbol, interval)
        held = self._read(self.holding_db, symbol, interval)
        if len(own) >= len(held):
            return own
        return held

    def load(self, inst: Instrument, interval: str, eur: bool = True) -> Dataset:
        notes = []
        candles = self.raw(inst.symbol, interval)
        if not candles and interval == "4h":
            candles = resample(self.raw(inst.symbol, "1h"), "4h")
            if candles:
                notes.append("4h samengesteld uit 1h")
        currency = inst.currency
        if inst.asset_class is AssetClass.FX:
            from jplh.backtest import unit_prices
            candles = unit_prices(candles, inst)
            notes.append("valuta: rendement van de vreemde munt in euro (1/koers)")
            currency = "EUR"
        elif eur and inst.currency == "USD" and candles:
            fx = self.raw("EURUSD=X", "1d")
            if fx:
                candles = to_eur(candles, fx)
                currency = "EUR"
                notes.append("omgerekend naar euro met de EUR/USD-slotkoers die al bekend was")
            else:
                notes.append("GEEN wisselkoers: rendement in dollar, valutarisico niet meegenomen")
        elif inst.currency not in ("EUR", "USD"):
            notes.append(f"rendement in {inst.currency}, niet omgerekend")
        return Dataset(inst, interval, candles, inst.source, currency, tuple(notes))

    def save(self, symbol: str, interval: str, candles: list[Candle], source: str) -> int:
        if self.research_db is None:
            raise RuntimeError("geen onderzoeksdatabase ingesteld (NEXUS_RESEARCH_DB)")
        st = Store(self.research_db)
        try:
            return st.save_candles(symbol, interval, candles, source, datetime.now(tz=UTC))
        finally:
            st.close()


def fetch_history(inst: Instrument, interval: str, bars: int) -> list[Candle]:
    """Haalt geschiedenis op bij de echte bron. Fouten gaan door naar de aanroeper: geen vervanging.
    De laatste, mogelijk nog lopende candle wordt weggelaten."""
    now = datetime.now(tz=UTC)
    step = STEP[interval]
    if inst.source == "bitvavo":
        from jplh.data.bitvavo import Bitvavo
        candles = Bitvavo().candles(inst.symbol, interval, bars)
    elif inst.source == "yahoo":
        from jplh.data.http import get_json
        from jplh.data.yahoo import BASE_URL, parse_chart
        if interval == "4h":
            return resample(fetch_history(inst, "1h", bars * 4), "4h")[-bars:]
        q = urllib.parse.urlencode({"interval": interval, "range": YAHOO_RANGE[interval]})
        candles = parse_chart(get_json(f"{BASE_URL}/{urllib.parse.quote(inst.symbol)}?{q}"))
    else:
        raise ValueError(f"onbekende bron {inst.source}")
    return [c for c in candles if c.ts + step <= now][-bars:]

"""Gedeelde datatypes voor alle afdelingen."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class AssetClass(str, Enum):
    CRYPTO = "crypto"
    MEME = "meme"
    STOCKS = "stocks"
    METALS = "metals"
    FX = "fx"


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class Instrument:
    symbol: str
    asset_class: AssetClass
    source: str
    currency: str = "EUR"


@dataclass(frozen=True)
class Shadow:
    """Een instrument van een schaduw-afdeling: draait alleen op papier mee in de arena.
    Er wordt nooit op gehandeld; Phil beslist of een schaduw-afdeling ooit echt mag."""

    symbol: str
    name: str
    desk: str
    source: str = "yahoo"
    currency: str = "EUR"


@dataclass(frozen=True)
class Watch:
    """Iets wat de verkenners alleen volgen (indexen, olie, rente, extra munten). Nooit handelen."""

    symbol: str
    name: str
    source: str
    kind: str = "markt"


@dataclass(frozen=True)
class Candle:
    """Eén gesloten koersperiode. ``ts`` is het begin van de periode (UTC)."""

    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(frozen=True)
class Signal:
    """Wat een afdeling wil. Een afdeling ziet nooit geld of sleutels; de risico-afdeling beslist."""

    instrument: str
    side: Side
    strategy: str
    reason: str
    size_eur: float | None = None  # None: risico-afdeling bepaalt de grootte (sell: alles)


@dataclass(frozen=True)
class Fill:
    instrument: str
    side: Side
    quantity: float
    price_eur: float        # gevulde prijs per eenheid, in euro
    fee_eur: float
    ts: datetime
    strategy: str = ""


@dataclass
class Check:
    rule: str
    passed: bool
    detail: str


@dataclass
class Decision:
    signal: Signal
    approved: bool
    reason: str
    size_eur: float = 0.0
    quantity: float = 0.0
    checks: list[Check] = field(default_factory=list)

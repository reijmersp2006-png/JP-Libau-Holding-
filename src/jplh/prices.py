"""Prijzen omrekenen naar euro, de munt van de holding."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from jplh.models import AssetClass, Instrument


class PriceError(KeyError):
    pass


@dataclass
class PriceBook:
    """Laatst bekende slotkoers per symbool, met tijdstip."""

    instruments: dict[str, Instrument]
    closes: dict[str, tuple[datetime, float]] = field(default_factory=dict)

    def update(self, symbol: str, ts: datetime, close: float) -> None:
        self.closes[symbol] = (ts, close)

    def ts(self, symbol: str) -> datetime | None:
        item = self.closes.get(symbol)
        return item[0] if item else None

    def eur_per_unit(self, currency: str) -> float:
        """Wat 1 eenheid ``currency`` in euro kost, via het valuta-instrument EUR{currency}."""
        if currency == "EUR":
            return 1.0
        for inst in self.instruments.values():
            if inst.asset_class is AssetClass.FX and inst.currency == currency and inst.symbol in self.closes:
                return 1.0 / self.closes[inst.symbol][1]
        raise PriceError(f"geen wisselkoers voor {currency}")

    def price_eur(self, symbol: str) -> float:
        inst = self.instruments[symbol]
        if inst.asset_class is AssetClass.FX:
            # Een valuta-positie = de vreemde munt zelf aanhouden.
            return self.eur_per_unit(inst.currency)
        if symbol not in self.closes:
            raise PriceError(f"geen koers voor {symbol}")
        return self.closes[symbol][1] * self.eur_per_unit(inst.currency)

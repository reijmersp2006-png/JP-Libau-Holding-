"""Boekhouding in euro: cash, posities, vermogen, top en dagstart."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from jplh.models import Fill, Side
from jplh.prices import PriceBook


@dataclass
class Position:
    quantity: float
    avg_price_eur: float

    @property
    def cost_eur(self) -> float:
        return self.quantity * self.avg_price_eur


@dataclass
class Portfolio:
    cash_eur: float
    positions: dict[str, Position] = field(default_factory=dict)
    realized_pnl_eur: float = 0.0
    fees_eur: float = 0.0

    def apply(self, fill: Fill) -> None:
        if fill.side is Side.BUY:
            cost = fill.quantity * fill.price_eur + fill.fee_eur
            if cost > self.cash_eur + 1e-9:
                raise ValueError(f"onvoldoende cash voor {fill.instrument}: €{cost:.2f} > €{self.cash_eur:.2f}")
            self.cash_eur -= cost
            pos = self.positions.get(fill.instrument)
            if pos is None:
                self.positions[fill.instrument] = Position(fill.quantity, fill.price_eur)
            else:
                qty = pos.quantity + fill.quantity
                pos.avg_price_eur = (pos.cost_eur + fill.quantity * fill.price_eur) / qty
                pos.quantity = qty
        else:
            pos = self.positions.get(fill.instrument)
            if pos is None or fill.quantity > pos.quantity * (1 + 1e-9):
                raise ValueError(f"kan niet meer {fill.instrument} verkopen dan je hebt")
            proceeds = fill.quantity * fill.price_eur - fill.fee_eur
            self.cash_eur += proceeds
            self.realized_pnl_eur += fill.quantity * (fill.price_eur - pos.avg_price_eur) - fill.fee_eur
            pos.quantity -= fill.quantity
            if pos.quantity <= fill.quantity * 1e-9:  # (vrijwel) alles verkocht
                del self.positions[fill.instrument]
        self.fees_eur += fill.fee_eur

    def value_of(self, symbol: str, prices: PriceBook) -> float:
        pos = self.positions.get(symbol)
        return 0.0 if pos is None else pos.quantity * prices.price_eur(symbol)

    def invested_eur(self, prices: PriceBook) -> float:
        return sum(self.value_of(s, prices) for s in self.positions)

    def equity_eur(self, prices: PriceBook) -> float:
        return self.cash_eur + self.invested_eur(prices)

    def class_exposure_eur(self, prices: PriceBook) -> dict[str, float]:
        out: dict[str, float] = {}
        for sym in self.positions:
            cls = prices.instruments[sym].asset_class.value
            out[cls] = out.get(cls, 0.0) + self.value_of(sym, prices)
        return out

    def to_dict(self) -> dict:
        return {"cash_eur": self.cash_eur, "realized_pnl_eur": self.realized_pnl_eur,
                "fees_eur": self.fees_eur, "positions": {k: asdict(v) for k, v in self.positions.items()}}

    @classmethod
    def from_dict(cls, d: dict) -> "Portfolio":
        return cls(d["cash_eur"], {k: Position(**v) for k, v in d.get("positions", {}).items()},
                   d.get("realized_pnl_eur", 0.0), d.get("fees_eur", 0.0))

"""Paper-broker: vult orders tegen de laatste koers met fee en slippage. Geen echt geld.

Een live-broker bestaat bewust niet in deze versie. Die komt pas na de demofase en
alleen met jouw expliciete akkoord.
"""

from __future__ import annotations

from datetime import datetime

from jplh.config import CostModel, HoldingConfig
from jplh.models import Decision, Fill, Side


class PaperBroker:
    live = False

    def __init__(self, config: HoldingConfig) -> None:
        self.config = config

    def cost_model(self, symbol: str) -> CostModel:
        return self.config.costs[self.config.instrument(symbol).asset_class.value]

    def execute(self, decision: Decision, price_eur: float, now: datetime) -> Fill:
        if not decision.approved:
            raise ValueError("alleen goedgekeurde beslissingen kunnen worden uitgevoerd")
        sig = decision.signal
        cost = self.cost_model(sig.instrument)
        if sig.side is Side.BUY:
            fill_price = price_eur * (1 + cost.slippage_pct)
            fee = max(cost.min_fee_eur, decision.size_eur * cost.fee_pct)
            qty = (decision.size_eur - fee) / fill_price
            if qty <= 0:
                raise ValueError("order te klein voor de kosten")
        else:
            fill_price = price_eur * (1 - cost.slippage_pct)
            qty = decision.quantity
            fee = max(cost.min_fee_eur, qty * fill_price * cost.fee_pct)
        return Fill(sig.instrument, sig.side, qty, fill_price, fee, now, sig.strategy)

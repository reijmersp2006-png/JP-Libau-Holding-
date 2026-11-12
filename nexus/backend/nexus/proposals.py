"""Het verplichte formaat van een handelsvoorstel. Een voorstel zonder tegenargumenten,
redenen om het niet te doen of een risico-exit wordt niet eens aangenomen."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

AssetClass = Literal["crypto", "meme", "stocks", "metals", "fx"]


class Confidence(BaseModel):
    value: float | None = Field(None, ge=0, le=1)
    calibrated: bool = False          # alleen True als het statistisch gevalideerd is (method + bewijs)
    method: str = "geen"              # bijv. "walk-forward hit-rate 2019-2025, n=412"

    @model_validator(mode="after")
    def _calibrated_needs_method(self):
        if self.calibrated and self.method.strip().lower() in ("", "geen", "llm"):
            raise ValueError("een gekalibreerde zekerheid moet een statistische methode noemen")
        return self


class TradeProposalIn(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    source: str = Field("manual", max_length=64)
    symbol: str = Field(min_length=1, max_length=64)
    asset_class: AssetClass
    direction: Literal["buy", "sell"]                 # geen short, geen hefboom
    strategy_id: str = Field(min_length=1, max_length=64)
    entry_conditions: str = Field(min_length=3)
    entry_price: float = Field(gt=0)
    size_eur: float = Field(gt=0)
    stop_loss: float | None = Field(None, gt=0)
    alternative_exit: str | None = None
    take_profit: str = Field(min_length=3)
    holding_period: str = Field(min_length=1)
    est_fee_pct: float = Field(ge=0, le=0.1)
    est_slippage_pct: float = Field(ge=0, le=0.2)
    spread_pct: float = Field(ge=0, le=0.5)
    available_liquidity_eur: float | None = Field(None, ge=0)
    liquidity_notes: str = ""
    evidence: list[str] = Field(min_length=1)
    counterarguments: list[str] = Field(min_length=1)
    reasons_to_avoid: list[str] = Field(min_length=1)
    confidence: Confidence = Confidence()
    max_modeled_loss_eur: float = Field(ge=0)
    scenario_risks: list[str] = Field(min_length=1)
    input_data_label: Literal["LIVE", "DELAYED", "HISTORICAL", "SIMULATED", "UNAVAILABLE"]
    security_checks_passed: bool | None = None       # verplicht True voor memecoins

    @model_validator(mode="after")
    def _needs_exit(self):
        if self.direction == "buy" and self.stop_loss is None and not (self.alternative_exit or "").strip():
            raise ValueError("een koopvoorstel heeft een stop-loss of een andere risico-exit nodig")
        return self

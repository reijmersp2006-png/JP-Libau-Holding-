"""Instellingen laden. Gebruikersconfig mag risicogrenzen alleen strenger maken."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from jplh.models import AssetClass, Instrument


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class RiskLimits:
    max_drawdown_pct: float = 0.15
    daily_loss_limit_pct: float = 0.03
    max_position_pct: float = 0.25
    max_invested_pct: float = 0.90
    max_trades_per_day: int = 10
    min_order_eur: float = 10.0
    max_data_age_hours: float = 3.0
    max_class_pct: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class CostModel:
    fee_pct: float
    slippage_pct: float
    min_fee_eur: float = 0.0


@dataclass(frozen=True)
class HoldingConfig:
    name: str
    base_currency: str
    start_capital_eur: float
    mode: str
    instruments: tuple[Instrument, ...]
    risk: RiskLimits
    costs: dict[str, CostModel]
    desks: dict[str, float] = field(default_factory=dict)

    def instrument(self, symbol: str) -> Instrument:
        for inst in self.instruments:
            if inst.symbol == symbol:
                return inst
        raise KeyError(symbol)


# Hoger = ruimer. Voor deze velden is een hogere waarde dan de standaard niet toegestaan.
_LOOSER_IF_HIGHER = (
    "max_drawdown_pct", "daily_loss_limit_pct", "max_position_pct", "max_invested_pct",
    "max_trades_per_day", "max_data_age_hours",
)


def _default_raw() -> dict:
    text = resources.files("jplh").joinpath("default_config.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)


def _merge_risk(default: dict, user: dict) -> dict:
    merged = dict(default)
    for key, value in user.items():
        if key == "max_class_pct":
            classes = dict(default.get("max_class_pct", {}))
            for cls, pct in value.items():
                if cls in classes and pct > classes[cls]:
                    raise ConfigError(f"risk.max_class_pct.{cls} mag niet ruimer dan {classes[cls]}")
                classes[cls] = pct
            merged["max_class_pct"] = classes
            continue
        if key in _LOOSER_IF_HIGHER and value > default[key]:
            raise ConfigError(f"risk.{key} = {value} is ruimer dan de vaste grens {default[key]}")
        if key == "min_order_eur" and value < default[key]:
            raise ConfigError(f"risk.min_order_eur mag niet lager dan {default[key]}")
        merged[key] = value
    return merged


def load_config(path: Path | None = None) -> HoldingConfig:
    raw = _default_raw()
    if path is not None and path.exists():
        user = tomllib.loads(path.read_text(encoding="utf-8"))
        raw["holding"] = {**raw["holding"], **user.get("holding", {})}
        raw["risk"] = _merge_risk(raw["risk"], user.get("risk", {}))
        if "instrument" in user:
            raw["instrument"] = user["instrument"]
        if "desks" in user:
            raw["desks"] = {**raw.get("desks", {}), **user["desks"]}
        for cls, cost in user.get("costs", {}).items():
            raw["costs"][cls] = {**raw["costs"].get(cls, {}), **cost}

    holding = raw["holding"]
    if holding.get("mode") != "paper":
        raise ConfigError("alleen mode = \"paper\" is toegestaan; live bestaat nog niet")

    instruments = []
    seen = set()
    for item in raw["instrument"]:
        sym = item["symbol"]
        if sym in seen:
            raise ConfigError(f"instrument {sym} staat dubbel in de config")
        seen.add(sym)
        instruments.append(Instrument(sym, AssetClass(item["asset_class"]), item["source"],
                                      item.get("currency", "EUR")))

    costs = {cls: CostModel(**vals) for cls, vals in raw["costs"].items()}
    missing = {i.asset_class.value for i in instruments} - set(costs)
    if missing:
        raise ConfigError(f"geen kostenmodel voor: {', '.join(sorted(missing))}")

    # Een afdeling krijgt nooit meer dan haar risicogrens per afdeling.
    desks = {k: min(float(v), raw["risk"]["max_class_pct"].get(k, 0.0)) for k, v in raw.get("desks", {}).items()}
    if sum(desks.values()) > 1.0 + 1e-9:
        raise ConfigError("desks: samen meer dan 100% van het startkapitaal")

    return HoldingConfig(
        name=holding["name"],
        base_currency=holding["base_currency"],
        start_capital_eur=float(holding["start_capital_eur"]),
        mode=holding["mode"],
        instruments=tuple(instruments),
        risk=RiskLimits(**raw["risk"]),
        costs=costs,
        desks=desks,
    )

"""Risk Guardian: onafhankelijk vetorecht over elk handelsvoorstel.

Geen agent, strategie of gebruiker kan hier omheen: een voorstel zonder goedgekeurd oordeel
kan nergens uitgevoerd worden. De grenzen zijn conservatief, altijd zichtbaar, en kunnen
via omgevingsvariabelen alleen strenger gemaakt worden (``NEXUS_RISK_<NAAM>``).
De Guardian kan en mag altijd "geen trade" kiezen.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, fields, replace

from nexus.controls import Mode


@dataclass(frozen=True)
class RiskLimits:
    max_risk_per_trade_pct: float = 0.01        # verlies tot de stop, als deel van het vermogen
    max_daily_loss_pct: float = 0.03
    max_drawdown_pct: float = 0.15
    max_position_pct: float = 0.10
    max_correlated_pct: float = 0.40            # crypto + memecoins samen (bewegen sterk samen)
    max_meme_pct: float = 0.05
    max_spread_pct: float = 0.005
    max_slippage_pct: float = 0.01
    min_liquidity_eur: float = 1_000_000.0      # 24-uurs volume of aantoonbare diepte
    max_order_vs_liquidity: float = 0.001       # order hooguit 0,1% van die liquiditeit
    max_open_positions: int = 20

    # Bij "min_" is groter strenger, bij de rest kleiner.
    def tightened(self, **overrides) -> "RiskLimits":
        ok = {}
        for name, value in overrides.items():
            current = getattr(self, name)
            stricter = value >= current if name.startswith("min_") else value <= current
            if not stricter:
                raise ValueError(f"{name}={value} is ruimer dan de standaard {current}; alleen strenger mag")
            if value < 0:
                raise ValueError(f"{name} mag niet negatief zijn")
            ok[name] = type(current)(value)
        return replace(self, **ok)

    def describe(self) -> list[dict]:
        labels = {
            "max_risk_per_trade_pct": "Max. risico per trade", "max_daily_loss_pct": "Max. dagverlies",
            "max_drawdown_pct": "Max. daling vanaf top", "max_position_pct": "Max. per positie",
            "max_correlated_pct": "Max. crypto + memes samen", "max_meme_pct": "Max. memecoins",
            "max_spread_pct": "Max. spread", "max_slippage_pct": "Max. slippage",
            "min_liquidity_eur": "Min. liquiditeit (24u)", "max_order_vs_liquidity": "Max. order t.o.v. liquiditeit",
            "max_open_positions": "Max. open posities",
        }
        return [{"key": k, "label": labels[k], "value": v} for k, v in asdict(self).items()]


def limits_from_env(env: dict[str, str] | None = None) -> RiskLimits:
    env = os.environ if env is None else env
    base = RiskLimits()
    overrides = {}
    for f in fields(RiskLimits):
        raw = env.get(f"NEXUS_RISK_{f.name.upper()}")
        if raw is not None:
            overrides[f.name] = float(raw)
    return base.tightened(**overrides) if overrides else base


@dataclass(frozen=True)
class PortfolioView:
    """Wat de Guardian over de portefeuille moet weten. Komt uit de echte (paper) boekhouding."""

    equity_eur: float
    position_value: dict[str, float]          # symbool -> waarde in euro
    class_exposure: dict[str, float]          # afdeling/asset-klasse -> waarde in euro
    day_pnl_pct: float
    drawdown: float
    paused: bool = False


@dataclass
class Check:
    rule: str
    passed: bool
    detail: str


@dataclass
class Verdict:
    approved: bool
    reason: str
    checks: list[Check]

    def to_dict(self) -> dict:
        return {"approved": self.approved, "reason": self.reason, "checks": [asdict(c) for c in self.checks]}


CORRELATED = ("crypto", "meme")


class RiskGuardian:
    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or RiskLimits()

    def evaluate(self, p, view: PortfolioView | None, mode: Mode, kill_engaged: bool) -> Verdict:
        """``p`` is een ``TradeProposalIn``. Elke check wordt teruggegeven, ook de geslaagde."""
        lim = self.limits
        c: list[Check] = []
        c.append(Check("noodstop", not kill_engaged, "noodstop staat AAN" if kill_engaged else "uit"))
        c.append(Check("modus", mode is not Mode.LIVE, f"modus {mode.value}; live bestaat niet in deze versie"))
        c.append(Check("data_beschikbaar", p.input_data_label in ("LIVE", "DELAYED", "SIMULATED"),
                       f"invoerdata is {p.input_data_label}"))
        if view is None:
            c.append(Check("portefeuille_bekend", False, "geen portefeuillegegevens: zonder weet de Guardian niets, dus nee"))
            return self._finish(c)
        equity = view.equity_eur
        held = view.position_value.get(p.symbol, 0.0)

        if p.direction == "sell":
            # Verkopen verkleint risico. Short gaan bestaat niet: er moet een positie zijn.
            c.append(Check("positie_aanwezig", held > 0, f"positie €{held:.2f}"))
            c.append(Check("ordergrootte", p.size_eur <= held * 1.001 + 0.01,
                           f"€{p.size_eur:.2f} van €{held:.2f} in bezit (geen short)"))
            return self._finish(c)

        c.append(Check("niet_gepauzeerd", not view.paused, "afdeling gepauzeerd" if view.paused else "actief"))
        c.append(Check("max_drawdown", view.drawdown < lim.max_drawdown_pct,
                       f"{view.drawdown:.1%} onder de top (grens {lim.max_drawdown_pct:.0%})"))
        c.append(Check("dagverlies", view.day_pnl_pct > -lim.max_daily_loss_pct,
                       f"vandaag {view.day_pnl_pct:+.2%} (grens -{lim.max_daily_loss_pct:.0%})"))

        if p.stop_loss is not None:
            risk_eur = p.size_eur * max(0.0, (p.entry_price - p.stop_loss) / p.entry_price)
            c.append(Check("stop_onder_instap", p.stop_loss < p.entry_price,
                           f"stop {p.stop_loss:g} t.o.v. instap {p.entry_price:g}"))
        else:
            risk_eur = p.max_modeled_loss_eur
        risk_eur = max(risk_eur, p.max_modeled_loss_eur)
        c.append(Check("risico_per_trade", equity > 0 and risk_eur / equity <= lim.max_risk_per_trade_pct,
                       f"max. verlies €{risk_eur:.2f} = {risk_eur / equity if equity else 1:.2%} van €{equity:.2f} "
                       f"(grens {lim.max_risk_per_trade_pct:.1%})"))

        new_pos = held + p.size_eur
        c.append(Check("concentratie", new_pos <= lim.max_position_pct * equity,
                       f"positie wordt €{new_pos:.2f} (grens {lim.max_position_pct:.0%} = €{lim.max_position_pct * equity:.2f})"))
        if p.asset_class in CORRELATED:
            corr = sum(view.class_exposure.get(k, 0.0) for k in CORRELATED) + p.size_eur
            c.append(Check("gecorreleerd", corr <= lim.max_correlated_pct * equity,
                           f"crypto + memes wordt €{corr:.2f} (grens {lim.max_correlated_pct:.0%})"))
        if p.asset_class == "meme":
            meme = view.class_exposure.get("meme", 0.0) + p.size_eur
            c.append(Check("memecoin_limiet", meme <= lim.max_meme_pct * equity,
                           f"memes wordt €{meme:.2f} (grens {lim.max_meme_pct:.0%})"))
        n_open = sum(1 for v in view.position_value.values() if v > 0)
        if held <= 0:
            c.append(Check("aantal_posities", n_open < lim.max_open_positions,
                           f"{n_open} open (max {lim.max_open_positions})"))
        c.append(Check("spread", p.spread_pct <= lim.max_spread_pct,
                       f"{p.spread_pct:.2%} (max {lim.max_spread_pct:.2%})"))
        c.append(Check("slippage", p.est_slippage_pct <= lim.max_slippage_pct,
                       f"{p.est_slippage_pct:.2%} (max {lim.max_slippage_pct:.2%})"))
        liq = p.available_liquidity_eur
        c.append(Check("liquiditeit", liq is not None and liq >= lim.min_liquidity_eur,
                       "onbekend" if liq is None else f"€{liq:,.0f} (min €{lim.min_liquidity_eur:,.0f})"))
        if liq:
            c.append(Check("order_vs_liquiditeit", p.size_eur <= lim.max_order_vs_liquidity * liq,
                           f"order is {p.size_eur / liq:.4%} van de liquiditeit (max {lim.max_order_vs_liquidity:.2%})"))
        if p.asset_class == "meme":
            c.append(Check("meme_veiligheid", p.security_checks_passed is True,
                           "contract-, honeypot- en liquiditeitschecks geslaagd" if p.security_checks_passed
                           else "verplichte veiligheidschecks ontbreken of faalden"))
        return self._finish(c)

    @staticmethod
    def _finish(checks: list[Check]) -> Verdict:
        failed = [c for c in checks if not c.passed]
        if failed:
            return Verdict(False, "veto: " + "; ".join(f"{c.rule} ({c.detail})" for c in failed), checks)
        return Verdict(True, "goedgekeurd door de Risk Guardian (nog niet uitgevoerd)", checks)

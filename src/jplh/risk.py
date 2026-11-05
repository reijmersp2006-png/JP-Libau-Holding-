"""Risico-afdeling met vetorecht. Elk signaal gaat hierlangs en elke check wordt gelogd.

Vaste regels, ook niet aan te passen door het zelflerende systeem:
- de noodstop (bestand ``KILL``) blokkeert elke order, ook verkopen;
- geen handel op verouderde koersen;
- nooit bijkopen in een positie die verlies staat (geen martingale);
- nooit meer kopen dan de beschikbare cash, nooit met geleend geld;
- grenzen voor drawdown, dagverlies, positiegrootte, afdeling en totaal belegd.
Verkopen verkleint risico en mag daarom altijd, behalve bij noodstop of verouderde koers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from jplh.config import HoldingConfig
from jplh.ledger import Portfolio
from jplh.models import Check, Decision, Side, Signal
from jplh.prices import PriceBook, PriceError


@dataclass
class RiskContext:
    now: datetime
    portfolio: Portfolio
    prices: PriceBook
    day_start_equity: float
    peak_equity: float
    trades_today: int
    paused_reason: str | None = None


class RiskEngine:
    def __init__(self, config: HoldingConfig, base_dir: Path | None = Path(".")) -> None:
        """``base_dir=None`` (backtest): geen KILL-bestand om naar te kijken."""
        self.config = config
        self.limits = config.risk
        self.base_dir = base_dir

    def kill_switch_on(self) -> bool:
        return self.base_dir is not None and (self.base_dir / "KILL").exists()

    def evaluate(self, signal: Signal, ctx: RiskContext) -> Decision:
        lim = self.limits
        sym = signal.instrument
        checks: list[Check] = []

        try:
            inst = self.config.instrument(sym)
        except KeyError:
            return Decision(signal, False, f"onbekend instrument {sym}")

        killed = self.kill_switch_on()
        checks.append(Check("noodstop", not killed, "KILL-bestand aanwezig" if killed else "uit"))

        try:
            price = ctx.prices.price_eur(sym)
            ts = ctx.prices.ts(sym)
            # Voor valuta komt de koers van het instrument zelf, voor de rest moet ook de
            # wisselkoers vers zijn.
            stamps = [ts]
            if inst.currency != "EUR" and inst.asset_class.value != "fx":
                fx_sym = next(i.symbol for i in self.config.instruments
                              if i.asset_class.value == "fx" and i.currency == inst.currency)
                stamps.append(ctx.prices.ts(fx_sym))
            oldest = min(s for s in stamps if s is not None) if all(stamps) else None
        except (PriceError, StopIteration):
            price, oldest = None, None
        if price is None or oldest is None:
            checks.append(Check("koers_vers", False, "geen koers of wisselkoers beschikbaar"))
            return self._finish(signal, checks)
        age = ctx.now - oldest
        max_age = timedelta(hours=lim.max_data_age_hours)
        checks.append(Check("koers_vers", age <= max_age,
                            f"koers {age.total_seconds() / 3600:.1f} uur oud (max {lim.max_data_age_hours:g})"))

        pos = ctx.portfolio.positions.get(sym)
        if signal.side is Side.SELL:
            if pos is None:
                return Decision(signal, False, "geen positie om te verkopen")
            qty = pos.quantity
            if signal.size_eur is not None:
                qty = min(qty, signal.size_eur / price)
            return self._finish(signal, checks, size_eur=qty * price, quantity=qty)

        equity = ctx.portfolio.equity_eur(ctx.prices)
        dd = 0.0 if ctx.peak_equity <= 0 else 1 - equity / ctx.peak_equity
        day = 0.0 if ctx.day_start_equity <= 0 else equity / ctx.day_start_equity - 1

        checks.append(Check("niet_gepauzeerd", ctx.paused_reason is None, ctx.paused_reason or "actief"))
        checks.append(Check("max_drawdown", dd < lim.max_drawdown_pct,
                            f"{dd:.1%} onder de top (grens {lim.max_drawdown_pct:.0%})"))
        checks.append(Check("dagverlies", day > -lim.daily_loss_limit_pct,
                            f"vandaag {day:+.2%} (grens -{lim.daily_loss_limit_pct:.0%})"))
        checks.append(Check("trades_per_dag", ctx.trades_today < lim.max_trades_per_day,
                            f"{ctx.trades_today} van max {lim.max_trades_per_day}"))
        if pos is not None:
            in_loss = price < pos.avg_price_eur
            checks.append(Check("geen_bijkopen_bij_verlies", not in_loss,
                                "positie staat verlies" if in_loss else "positie staat winst"))

        cls = inst.asset_class.value
        held = ctx.portfolio.value_of(sym, ctx.prices)
        class_held = ctx.portfolio.class_exposure_eur(ctx.prices).get(cls, 0.0)
        room_position = lim.max_position_pct * equity - held
        room_class = lim.max_class_pct.get(cls, 0.0) * equity - class_held
        room_total = lim.max_invested_pct * equity - ctx.portfolio.invested_eur(ctx.prices)
        room_cash = ctx.portfolio.cash_eur * 0.995  # marge voor kosten
        wanted = signal.size_eur if signal.size_eur is not None else room_position
        size = max(0.0, min(wanted, room_position, room_class, room_total, room_cash))
        checks.append(Check(
            "ordergrootte", size >= lim.min_order_eur,
            f"€{size:.2f} (gevraagd €{wanted:.2f}; ruimte positie €{room_position:.2f}, "
            f"afdeling {cls} €{room_class:.2f}, totaal €{room_total:.2f}, cash €{room_cash:.2f}; "
            f"minimum €{lim.min_order_eur:.2f})"))
        return self._finish(signal, checks, size_eur=size, quantity=size / price)

    @staticmethod
    def _finish(signal: Signal, checks: list[Check], size_eur: float = 0.0, quantity: float = 0.0) -> Decision:
        failed = [c for c in checks if not c.passed]
        if failed:
            why = "; ".join(f"{c.rule}: {c.detail}" for c in failed)
            return Decision(signal, False, f"geweigerd door risico ({why})", checks=checks)
        verb = "kopen" if signal.side is Side.BUY else "verkopen"
        return Decision(signal, True, f"goedgekeurd: {verb} voor ca. €{size_eur:.2f}", size_eur, quantity, checks)

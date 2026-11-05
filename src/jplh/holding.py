"""De holding als geheel: houdt de staat bij en laat een signaal de hele keten doorlopen
(risico -> paper-broker -> boekhouding -> logboek). Afdelingen en het leerlab (fase 2-5)
bouwen hierop voort."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from jplh.broker import PaperBroker
from jplh.config import HoldingConfig
from jplh.journal import Journal
from jplh.ledger import Portfolio
from jplh.models import Decision, Signal
from jplh.prices import PriceBook
from jplh.risk import RiskContext, RiskEngine
from jplh.store import Store


class Holding:
    def __init__(self, config: HoldingConfig, store: Store, base_dir: Path | None = Path("."),
                 log_dir: Path | None = Path("logs"), interval: str = "1h", market: Store | None = None) -> None:
        """``store`` bewaart boekhouding en logboek; ``market`` de koersen (standaard dezelfde)."""
        self.config = config
        self.store = store
        self.market = market or store
        self.interval = interval
        self.risk = RiskEngine(config, base_dir)
        self.broker = PaperBroker(config)
        self.journal = Journal(store, log_dir)
        saved = store.get_state("portfolio")
        self.portfolio = Portfolio.from_dict(saved) if saved else Portfolio(config.start_capital_eur)
        self.meta = store.get_state("meta", {"peak_equity": config.start_capital_eur,
                                             "day": None, "day_start_equity": config.start_capital_eur,
                                             "paused_reason": None})

    def prices(self, now: datetime | None = None) -> PriceBook:
        """Laatst bekende koersen; met ``now`` alleen wat op dat moment al opgehaald was."""
        book = PriceBook({i.symbol: i for i in self.config.instruments})
        for inst in self.config.instruments:
            last = self.market.latest_close(inst.symbol, self.interval, known_at=now)
            if last:
                book.update(inst.symbol, *last)
        return book

    def mark(self, now: datetime, prices: PriceBook) -> float:
        """Vermogen bijwerken: top, dagstart en automatische pauze bij te grote daling."""
        equity = self.portfolio.equity_eur(prices)
        today = now.astimezone(UTC).date().isoformat()
        if self.meta["day"] != today:
            self.meta["day"] = today
            self.meta["day_start_equity"] = equity
        self.meta["peak_equity"] = max(self.meta["peak_equity"], equity)
        dd = 1 - equity / self.meta["peak_equity"]
        if dd >= self.config.risk.max_drawdown_pct and not self.meta["paused_reason"]:
            self.meta["paused_reason"] = f"drawdown {dd:.1%}: gepauzeerd tot jij 'jplh resume' doet"
            self.journal.write(now, "pause", {"reason": self.meta["paused_reason"]})
        self.store.add_equity(now, equity)
        self._save()
        return equity

    def submit(self, signal: Signal, now: datetime | None = None) -> Decision:
        now = now or datetime.now(tz=UTC)
        prices = self.prices(now)
        self.mark(now, prices)
        ctx = RiskContext(now, self.portfolio, prices, self.meta["day_start_equity"],
                          self.meta["peak_equity"], self.store.fills_on(now.astimezone(UTC).date()),
                          self.meta["paused_reason"])
        decision = self.risk.evaluate(signal, ctx)
        self.journal.decision(now, decision)
        if decision.approved:
            fill = self.broker.execute(decision, prices.price_eur(signal.instrument), now)
            self.portfolio.apply(fill)
            self.journal.fill(fill)
            self.mark(now, prices)
        return decision

    def resume(self, now: datetime | None = None) -> None:
        now = now or datetime.now(tz=UTC)
        self.meta["paused_reason"] = None
        self.meta["peak_equity"] = self.portfolio.equity_eur(self.prices())
        self.journal.write(now, "resume", {"by": "eigenaar"})
        self._save()

    def _save(self) -> None:
        self.store.set_state("portfolio", self.portfolio.to_dict())
        self.store.set_state("meta", self.meta)

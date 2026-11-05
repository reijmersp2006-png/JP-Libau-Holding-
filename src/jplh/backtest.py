"""Backtest-lab: strategieën testen op historische koersen, met echte kosten en zonder
in de toekomst te kijken.

Regels:
- een beslissing op de slotkoers van periode i wordt uitgevoerd op de OPENING van i+1;
- elke order betaalt fee en slippage uit het kostenmodel van de afdeling (zelfde als paper);
- walk-forward: instellingen worden gekozen op oudere data en daarna getest op data die
  de keuze niet heeft gezien. Alleen dat laatste deel telt in het oordeel.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from jplh.config import CostModel
from jplh.models import AssetClass, Candle, Instrument
from jplh.strategies import FAMILIES, BuyHold, Strategy

# Aantal koersperioden per jaar, voor jaarrendement en Sharpe.
PERIODS_PER_YEAR = {
    ("1d", "crypto"): 365, ("1d", "meme"): 365,
    ("1d", "stocks"): 252, ("1d", "metals"): 252, ("1d", "fx"): 260,
    ("1h", "crypto"): 8760, ("1h", "meme"): 8760,
    ("1h", "stocks"): 252 * 7, ("1h", "metals"): 252 * 23, ("1h", "fx"): 260 * 24,
}


def unit_prices(candles: list[Candle], inst: Instrument) -> list[Candle]:
    """Voor valuta houden we de vreemde munt aan: de prijs in euro is 1/koers."""
    if inst.asset_class is not AssetClass.FX:
        return candles
    return [Candle(c.ts, 1 / c.open, 1 / c.low, 1 / c.high, 1 / c.close, c.volume) for c in candles]


@dataclass
class Metrics:
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe: float
    trades: int
    exposure: float
    fees: float

    def as_row(self) -> dict:
        return {"rendement": self.total_return, "per_jaar": self.annual_return, "max_daling": self.max_drawdown,
                "sharpe": self.sharpe, "trades": self.trades, "in_markt": self.exposure, "kosten": self.fees}


@dataclass
class RunResult:
    strategy: str
    returns: list[float]          # rendement per periode, vanaf ``start``
    trades: int
    fees: float
    in_market: int
    equity: list[float] = field(default_factory=list)


def simulate(strategy: Strategy, candles: list[Candle], cost: CostModel, start: int = 0,
             end: int | None = None, capital: float = 1000.0) -> RunResult:
    """Handel van ``start`` tot ``end``. Data vóór ``start`` dient alleen als opwarmtijd."""
    end = len(candles) if end is None else end
    targets = strategy.targets(candles[:end])
    cash, qty = capital, 0.0
    prev_equity = capital
    returns, equity = [], []
    trades = in_market = 0
    fees = 0.0
    for i in range(start, end):
        c = candles[i]
        # Besluit op de slotkoers van i-1, uitgevoerd op de opening van i.
        want = targets[i - 1] if i >= 1 else 0
        if want and qty == 0:
            price = c.open * (1 + cost.slippage_pct)
            fee = max(cost.min_fee_eur, cash * cost.fee_pct)
            if cash > fee:
                qty = (cash - fee) / price
                cash, fees, trades = 0.0, fees + fee, trades + 1
        elif not want and qty > 0:
            price = c.open * (1 - cost.slippage_pct)
            gross = qty * price
            fee = max(cost.min_fee_eur, gross * cost.fee_pct)
            cash, qty, fees = gross - fee, 0.0, fees + fee
        value = cash + qty * c.close
        in_market += qty > 0
        returns.append(value / prev_equity - 1 if prev_equity > 0 else 0.0)
        equity.append(value)
        prev_equity = value
    return RunResult(strategy.label, returns, trades, fees, in_market, equity)


def metrics(returns: list[float], trades: int, fees: float, in_market: int, periods_per_year: int) -> Metrics:
    n = len(returns)
    if n == 0:
        return Metrics(0, 0, 0, 0, trades, 0, fees)
    eq, peak, mdd = 1.0, 1.0, 0.0
    for r in returns:
        eq *= 1 + r
        peak = max(peak, eq)
        mdd = max(mdd, 1 - eq / peak)
    years = n / periods_per_year
    annual = eq ** (1 / years) - 1 if years > 0 and eq > 0 else -1.0
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1) if n > 1 else 0.0
    sharpe = mean / math.sqrt(var) * math.sqrt(periods_per_year) if var > 0 else 0.0
    return Metrics(eq - 1, annual, mdd, sharpe, trades, in_market / n, fees)


@dataclass
class Fold:
    train_start: int
    test_start: int
    test_end: int
    chosen: str


@dataclass
class WalkForwardResult:
    family: str
    instrument: str
    oos: Metrics
    benchmark: Metrics
    folds: list[Fold]

    @property
    def beats_benchmark(self) -> bool:
        """Strenge toets: beter voor risico (Sharpe) EN geen diepere daling dan koop-en-houd,
        met genoeg trades om iets te zeggen."""
        return (self.oos.sharpe > self.benchmark.sharpe and self.oos.max_drawdown <= self.benchmark.max_drawdown
                and self.oos.trades >= 5)


def walk_forward(family: str, candidates: list[Strategy], candles: list[Candle], inst: Instrument,
                 cost: CostModel, interval: str = "1d", train: int = 500, test: int = 125) -> WalkForwardResult | None:
    ppy = PERIODS_PER_YEAR[(interval, inst.asset_class.value)]
    candles = unit_prices(candles, inst)
    if len(candles) < train + test:
        return None
    oos_returns: list[float] = []
    trades = in_market = 0
    fees = 0.0
    folds = []
    for test_start in range(train, len(candles) - test + 1, test):
        test_end = test_start + test
        # 1. Kies de instelling met de beste Sharpe op de trainingsperiode.
        best, best_sharpe = None, -math.inf
        for strat in candidates:
            run = simulate(strat, candles, cost, start=test_start - train + min(strat.warmup, train // 2),
                           end=test_start)
            m = metrics(run.returns, run.trades, run.fees, run.in_market, ppy)
            if m.sharpe > best_sharpe:
                best, best_sharpe = strat, m.sharpe
        # 2. Test die keuze op de volgende, ongeziene periode.
        run = simulate(best, candles, cost, start=test_start, end=test_end)
        oos_returns += run.returns
        trades += run.trades
        fees += run.fees
        in_market += run.in_market
        folds.append(Fold(test_start - train, test_start, test_end, best.label))
    # Maatlat over exact dezelfde periode, één keer kopen aan het begin.
    bench = simulate(BuyHold(), candles, cost, start=train, end=folds[-1].test_end)
    return WalkForwardResult(
        family, inst.symbol,
        metrics(oos_returns, trades, fees, in_market, ppy),
        metrics(bench.returns, bench.trades, bench.fees, bench.in_market, ppy),
        folds)


def run_lab(instruments: list[Instrument], candles_of: dict[str, list[Candle]], costs: dict[str, CostModel],
            interval: str = "1d", train: int = 500, test: int = 125,
            families: dict[str, list[Strategy]] | None = None) -> list[WalkForwardResult]:
    families = families or FAMILIES
    out = []
    for inst in instruments:
        candles = candles_of.get(inst.symbol, [])
        for fam, cands in families.items():
            res = walk_forward(fam, cands, candles, inst, costs[inst.asset_class.value], interval, train, test)
            if res:
                out.append(res)
    return out

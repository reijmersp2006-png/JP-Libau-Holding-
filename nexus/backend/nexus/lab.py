"""Strategy Lab: geversioneerde, deterministische strategieën en een realistische backtest.

De signalen komen uit de geteste strategieën van de holding (``jplh.strategies``), die
alleen kijken naar koersen tot en met de huidige periode. De backtest hier voegt toe wat
een strategie-onderzoek nodig heeft: handel-voor-handel resultaten (win rate, profit factor,
verwachting per trade), spread, liquiditeitsgrens, in-sample tegenover out-of-sample,
stabiliteit per vak (walk-forward) en per marktregime, en een vergelijking met koop-en-houd.

Uitvoering: een besluit op de slotkoers van dag i wordt uitgevoerd op de OPENING van dag i+1,
tegen opening ± halve spread ± slippage, plus kosten. Er wordt nooit geoptimaliseerd op het
out-of-sample deel; parameters liggen per versie vast.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from jplh.backtest import PERIODS_PER_YEAR, unit_prices
from jplh.config import CostModel
from jplh.models import Candle, Instrument
from jplh.strategies import Breakout, MeanReversion, Momentum, Strategy, TrendSMA


class VolatilityFilter(Strategy):
    """Trend volgen, maar alleen als de beweeglijkheid (20 dagen, jaarbasis) niet hoger is dan
    haar eigen mediaan van het afgelopen jaar. Die mediaan gebruikt alleen verleden data."""

    def __init__(self, fast: int = 50, slow: int = 200, vol_window: int = 20, lookback: int = 252) -> None:
        super().__init__("volfilter", {"fast": fast, "slow": slow, "vol_window": vol_window, "lookback": lookback})

    @property
    def warmup(self):
        return max(self.params["slow"], self.params["lookback"] + self.params["vol_window"])

    def targets(self, candles):
        p = self.params
        trend = TrendSMA(p["fast"], p["slow"], 0.01).targets(candles)
        closes = [c.close for c in candles]
        rets = [0.0] + [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
        vols: list[float | None] = []
        for i in range(len(closes)):
            w = rets[max(1, i - p["vol_window"] + 1): i + 1]
            if len(w) < p["vol_window"]:
                vols.append(None)
                continue
            m = sum(w) / len(w)
            vols.append(math.sqrt(sum((r - m) ** 2 for r in w) / (len(w) - 1)))
        out = []
        for i, v in enumerate(vols):
            hist = [x for x in vols[max(0, i - p["lookback"]): i] if x is not None]
            if v is None or len(hist) < p["lookback"] // 2:
                out.append(0)
                continue
            med = sorted(hist)[len(hist) // 2]
            out.append(trend[i] if v <= med else 0)
        return out


@dataclass(frozen=True)
class StrategySpec:
    key: str
    version: int
    name: str
    family: str
    params: dict
    required_data: str
    entry: str
    exit: str
    sizing: str
    risk: str
    status: str = "research"

    def build(self) -> Strategy:
        return FACTORIES[self.family](**self.params)

    def to_dict(self) -> dict:
        return asdict(self)


FACTORIES = {"trend": TrendSMA, "momentum": Momentum, "terugkeer": MeanReversion, "uitbraak": Breakout,
             "volfilter": VolatilityFilter}

SIZING = "100% van het toegewezen kapitaal per instrument; in het portfolio begrensd door de Risk Guardian"
SPECS: list[StrategySpec] = [
    StrategySpec("trend_sma", 1, "Trend (gemiddelden)", "trend", {"fast": 50, "slow": 200, "band": 0.01},
                 "dagkoersen, minstens 200 dagen",
                 "50-daags gemiddelde stijgt meer dan 1% boven het 200-daagse",
                 "50-daags gemiddelde zakt meer dan 1% onder het 200-daagse", SIZING,
                 "geen hefboom, geen short; marge van 1% tegen heen-en-weer"),
    StrategySpec("momentum", 1, "Momentum", "momentum", {"lookback": 90, "threshold": 0.0},
                 "dagkoersen, minstens 90 dagen", "slotkoers hoger dan 90 dagen geleden",
                 "slotkoers lager dan 90 dagen geleden", SIZING, "geen hefboom, geen short"),
    StrategySpec("mean_reversion", 1, "Terugkeer naar gemiddelde", "terugkeer", {"period": 14, "low": 30, "high": 55},
                 "dagkoersen, minstens 14 dagen", "RSI(14) onder 30 (overdreven daling)",
                 "RSI(14) boven 55 (herstel)", SIZING, "geen hefboom; vangt geen vallend mes af zonder stop"),
    StrategySpec("breakout", 1, "Uitbraak", "uitbraak", {"entry": 55, "exit": 20},
                 "dagkoersen, minstens 55 dagen", "slotkoers boven het hoogste punt van 55 dagen",
                 "slotkoers onder het laagste punt van 20 dagen", SIZING, "geen hefboom, geen short"),
    StrategySpec("volatility_filter", 1, "Trend met volatiliteitsfilter", "volfilter",
                 {"fast": 50, "slow": 200, "vol_window": 20, "lookback": 252},
                 "dagkoersen, minstens ~270 dagen",
                 "trend omhoog én 20-daagse beweeglijkheid niet boven de mediaan van het afgelopen jaar",
                 "trend omlaag of beweeglijkheid boven die mediaan", SIZING, "geen hefboom; minder in de markt bij onrust"),
]


def spec(key: str, version: int | None = None) -> StrategySpec:
    for s in SPECS:
        if s.key == key and (version is None or s.version == version):
            return s
    raise KeyError(f"onbekende strategie {key} v{version}")


# ── Simulatie ──────────────────────────────────────────────────────────────────────────────
@dataclass
class Trade:
    entry_ts: str
    exit_ts: str | None
    entry_price: float
    exit_price: float | None
    pnl_eur: float
    ret: float
    costs_eur: float
    bars: int


@dataclass
class Sim:
    equity: list[float]
    returns: list[float]
    trades: list[Trade]
    costs: float
    in_market: int
    turnover_eur: float
    capped_orders: int = 0


def simulate(targets: list[int], candles: list[Candle], cost: CostModel, spread_pct: float, start: int, end: int,
             capital: float = 1000.0, max_volume_share: float | None = 0.01) -> Sim:
    """Volgt ``targets`` (0/1) van ``start`` tot ``end``. ``max_volume_share``: een order mag niet
    groter zijn dan dit deel van de omzet van die dag (anders wordt hij kleiner gemaakt)."""
    cash, qty = capital, 0.0
    equity, returns, trades = [], [], []
    costs = turnover = 0.0
    in_market = capped = 0
    prev = capital
    open_trade: dict | None = None
    half = spread_pct / 2
    for i in range(start, end):
        c = candles[i]
        want = targets[i - 1] if i >= 1 else 0
        if want and qty == 0 and cash > 0:
            px = c.open * (1 + half + cost.slippage_pct)
            budget = cash
            if max_volume_share is not None and c.volume > 0:
                cap = c.volume * c.open * max_volume_share
                if budget > cap:
                    budget, capped = cap, capped + 1
            fee = max(cost.min_fee_eur, budget * cost.fee_pct)
            if budget > fee:
                qty = (budget - fee) / px
                cash -= budget
                spread_cost = qty * (px - c.open)
                costs += fee + spread_cost
                turnover += budget
                open_trade = {"i": i, "ts": c.ts, "px": px, "cost": budget, "fees": fee + spread_cost}
        elif not want and qty > 0:
            px = c.open * (1 - half - cost.slippage_pct)
            gross = qty * px
            fee = max(cost.min_fee_eur, gross * cost.fee_pct)
            spread_cost = qty * (c.open - px)
            cash += gross - fee
            costs += fee + spread_cost
            turnover += gross
            ot = open_trade or {}
            pnl = gross - fee - ot.get("cost", 0.0)
            trades.append(Trade(ot["ts"].isoformat(), c.ts.isoformat(), ot["px"], px, pnl,
                                pnl / ot["cost"] if ot.get("cost") else 0.0, ot["fees"] + fee + spread_cost, i - ot["i"]))
            qty, open_trade = 0.0, None
        value = cash + qty * c.close
        in_market += qty > 0
        returns.append(value / prev - 1 if prev > 0 else 0.0)
        equity.append(value)
        prev = value
    if open_trade is not None and qty > 0:          # open positie: tegen de laatste slotkoers, als open gemarkeerd
        last = candles[end - 1]
        val = qty * last.close * (1 - half - cost.slippage_pct)
        pnl = val - open_trade["cost"]
        trades.append(Trade(open_trade["ts"].isoformat(), None, open_trade["px"], None, pnl,
                            pnl / open_trade["cost"], open_trade["fees"], end - 1 - open_trade["i"]))
    return Sim(equity, returns, trades, costs, in_market, turnover, capped)


def metrics(sim: Sim, ppy: int, capital: float) -> dict:
    r = sim.returns
    n = len(r)
    if n == 0:
        return {"periods": 0}
    eq, peak, mdd = 1.0, 1.0, 0.0
    for x in r:
        eq *= 1 + x
        peak = max(peak, eq)
        mdd = max(mdd, 1 - eq / peak)
    years = n / ppy
    mean = sum(r) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in r) / (n - 1)) if n > 1 else 0.0
    downside = [min(0.0, x) for x in r]
    dd = math.sqrt(sum(x * x for x in downside) / n) if n else 0.0
    closed = [t for t in sim.trades if t.exit_ts is not None]
    wins = [t for t in closed if t.pnl_eur > 0]
    losses = [t for t in closed if t.pnl_eur <= 0]
    gross_win = sum(t.pnl_eur for t in wins)
    gross_loss = -sum(t.pnl_eur for t in losses)
    sharpe = mean / sd * math.sqrt(ppy) if sd > 0 else 0.0
    # Onzekerheid van de Sharpe (Lo, 2002, benadering voor iid rendementen).
    se = math.sqrt((1 + 0.5 * (sharpe / math.sqrt(ppy)) ** 2) / n) * math.sqrt(ppy) if n > 1 else None
    return {
        "periods": n, "years": years, "net_return": eq - 1,
        "annual_return": eq ** (1 / years) - 1 if years > 0 and eq > 0 else -1.0,
        "max_drawdown": mdd, "sharpe": sharpe,
        "sharpe_ci95": [sharpe - 1.96 * se, sharpe + 1.96 * se] if se else None,
        "sortino": mean / dd * math.sqrt(ppy) if dd > 0 else None,
        "trades": len(closed), "open_trade": len(sim.trades) > len(closed),
        "win_rate": len(wins) / len(closed) if closed else None,
        "profit_factor": gross_win / gross_loss if gross_loss > 0 else None,
        "expectancy_eur": sum(t.pnl_eur for t in closed) / len(closed) if closed else None,
        "avg_win_eur": gross_win / len(wins) if wins else None,
        "avg_loss_eur": -gross_loss / len(losses) if losses else None,
        "exposure": sim.in_market / n, "costs_eur": sim.costs, "costs_pct_capital": sim.costs / capital,
        "turnover": sim.turnover_eur / capital / years if years > 0 else None,
        "liquidity_capped_orders": sim.capped_orders,
    }


def regimes(candles: list[Candle], start: int, end: int, window: int = 200) -> list[str]:
    """Per periode: 'bull' als de slotkoers van de vorige dag boven zijn 200-dagengemiddelde lag."""
    closes = [c.close for c in candles]
    out = []
    for i in range(start, end):
        j = i - 1
        if j < window - 1:
            out.append("onbekend")
            continue
        sma = sum(closes[j - window + 1: j + 1]) / window
        out.append("bull" if closes[j] > sma else "bear")
    return out


def run_backtest(s: StrategySpec, inst: Instrument, candles: list[Candle], cost: CostModel, interval: str = "1d",
                 spread_pct: float = 0.001, capital: float = 1000.0, oos_fraction: float = 0.3,
                 folds: int = 5) -> dict:
    """Volledige backtest van één versie op één instrument. Geeft alles terug wat het lab toont."""
    ppy = PERIODS_PER_YEAR[(interval, inst.asset_class.value)]
    candles = unit_prices(candles, inst)
    strat = s.build()
    warm = strat.warmup + 1
    if len(candles) < warm + 60:
        raise ValueError(f"te weinig koersen: {len(candles)} (minstens {warm + 60} nodig)")
    targets = strat.targets(candles)
    n = len(candles)
    split = warm + int((n - warm) * (1 - oos_fraction))
    full = simulate(targets, candles, cost, spread_pct, warm, n, capital)
    ins = simulate(targets, candles, cost, spread_pct, warm, split, capital)
    oos = simulate(targets, candles, cost, spread_pct, split, n, capital)
    hold = [1] * n
    bench_full = simulate(hold, candles, cost, spread_pct, warm, n, capital, max_volume_share=None)
    bench_oos = simulate(hold, candles, cost, spread_pct, split, n, capital, max_volume_share=None)

    # Walk-forward-vakken: zelfde vaste parameters, opeenvolgende stukken. Stabiliteit = spreiding.
    size = (n - warm) // folds
    fold_rows = []
    for k in range(folds):
        a, b = warm + k * size, (warm + (k + 1) * size) if k < folds - 1 else n
        f = simulate(targets, candles, cost, spread_pct, a, b, capital)
        fb = simulate(hold, candles, cost, spread_pct, a, b, capital, max_volume_share=None)
        mf, mb = metrics(f, ppy, capital), metrics(fb, ppy, capital)
        fold_rows.append({"start": candles[a].ts.date().isoformat(), "end": candles[b - 1].ts.date().isoformat(),
                          "net_return": mf["net_return"], "sharpe": mf["sharpe"], "max_drawdown": mf["max_drawdown"],
                          "benchmark_return": mb["net_return"]})

    reg = regimes(candles, warm, n)
    by_regime = {}
    for name in ("bull", "bear"):
        rs = [r for r, g in zip(full.returns, reg) if g == name]
        bs = [r for r, g in zip(bench_full.returns, reg) if g == name]
        if len(rs) > 1:
            m = sum(rs) / len(rs)
            sd = math.sqrt(sum((x - m) ** 2 for x in rs) / (len(rs) - 1))
            by_regime[name] = {"periods": len(rs), "mean_return": m, "benchmark_mean_return": sum(bs) / len(bs),
                               "sharpe": m / sd * math.sqrt(ppy) if sd > 0 else 0.0}

    m_full, m_oos = metrics(full, ppy, capital), metrics(oos, ppy, capital)
    b_full, b_oos = metrics(bench_full, ppy, capital), metrics(bench_oos, ppy, capital)
    fold_sharpes = [f["sharpe"] for f in fold_rows]
    verdict = []
    if m_oos.get("sharpe", 0) <= b_oos.get("sharpe", 0):
        verdict.append("out-of-sample niet beter voor risico dan koop-en-houd")
    if m_oos.get("trades", 0) < 5:
        verdict.append("te weinig trades out-of-sample om iets te zeggen")
    if sum(1 for x in fold_sharpes if x > 0) < math.ceil(folds * 0.6):
        verdict.append("niet stabiel: in minder dan 60% van de vakken een positieve Sharpe")
    ci = m_oos.get("sharpe_ci95")
    if ci and ci[0] <= 0:
        verdict.append("95%-interval van de out-of-sample Sharpe bevat nul")
    return {
        "strategy": s.to_dict(), "symbol": inst.symbol, "asset_class": inst.asset_class.value, "interval": interval,
        "data": {"first": candles[0].ts.isoformat(), "last": candles[-1].ts.isoformat(), "bars": n,
                 "warmup": warm, "oos_start": candles[split].ts.isoformat()},
        "assumptions": {"fee_pct": cost.fee_pct, "min_fee_eur": cost.min_fee_eur, "slippage_pct": cost.slippage_pct,
                        "spread_pct": spread_pct, "max_volume_share": 0.01, "capital_eur": capital,
                        "execution": "besluit op slotkoers, uitvoering op de volgende opening",
                        "not_modeled": ["feestdagen", "dividend en splitsingen (Yahoo-koersen zijn niet aangepast)",
                                        "survivorship: universum is de huidige instrumentenlijst"]},
        "full": m_full, "in_sample": metrics(ins, ppy, capital), "out_of_sample": m_oos,
        "benchmark": {"full": b_full, "out_of_sample": b_oos},
        "benchmark_relative_return": m_full["net_return"] - b_full["net_return"],
        "folds": fold_rows, "regimes": by_regime,
        "trades": [asdict(t) for t in full.trades[-50:]],
        "equity": [[candles[warm + i].ts.date().isoformat(), round(e, 2)] for i, e in enumerate(full.equity)][::max(1, len(full.equity) // 400)],
        "benchmark_equity": [[candles[warm + i].ts.date().isoformat(), round(e, 2)] for i, e in enumerate(bench_full.equity)][::max(1, len(bench_full.equity) // 400)],
        "passes": not verdict, "verdict": verdict or ["voldoet aan de minimale toets; volgende stap: paper-periode"],
    }

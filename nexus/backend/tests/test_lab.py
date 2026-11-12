import math
from datetime import UTC, datetime, timedelta

import pytest
from jplh.config import CostModel, load_config
from jplh.models import Candle

from nexus.lab import SPECS, Sim, Trade, metrics, run_backtest, simulate


def series(n=900, seed=3):
    """Deterministische nep-reeks voor tests (sinus + trend), nooit getoond als marktdata."""
    out, px = [], 100.0
    t0 = datetime(2022, 1, 1, tzinfo=UTC)
    for i in range(n):
        o = px
        px = px * (1 + 0.0004 + 0.02 * math.sin(i / 17 + seed) * 0.5)
        out.append(Candle(t0 + timedelta(days=i), o, max(o, px) * 1.005, min(o, px) * 0.995, px, 1e9))
    return out


@pytest.mark.parametrize("sp", SPECS, ids=lambda s: s.key)
def test_no_look_ahead(sp):
    """Een signaal op dag i mag niet veranderen als de toekomst verandert."""
    c = series()
    a = sp.build().targets(c)
    future = c[:600] + [Candle(x.ts, x.open * 3, x.high * 3, x.low * 3, x.close * 3, x.volume) for x in c[600:]]
    b = sp.build().targets(future)
    assert a[:600] == b[:600]


@pytest.mark.parametrize("sp", SPECS, ids=lambda s: s.key)
def test_deterministic_and_complete(sp):
    cfg = load_config()
    inst = cfg.instrument("BTC-EUR")
    r1 = run_backtest(sp, inst, series(), cfg.costs["crypto"])
    r2 = run_backtest(sp, inst, series(), cfg.costs["crypto"])
    assert r1 == r2
    for k in ("net_return", "sharpe", "sortino", "max_drawdown", "win_rate", "profit_factor", "expectancy_eur",
              "exposure", "costs_eur"):
        assert k in r1["out_of_sample"]
    assert len(r1["folds"]) == 5 and r1["data"]["oos_start"] > r1["data"]["first"]
    assert r1["benchmark_relative_return"] == pytest.approx(r1["full"]["net_return"] - r1["benchmark"]["full"]["net_return"])
    assert isinstance(r1["passes"], bool) and r1["verdict"]


def test_costs_and_spread_lower_returns():
    c = series()
    tg = SPECS[1].build().targets(c)
    free = simulate(tg, c, CostModel(0, 0, 0), 0.0, 100, len(c))
    paid = simulate(tg, c, CostModel(0.0025, 0.001, 0), 0.002, 100, len(c))
    assert paid.equity[-1] < free.equity[-1] and paid.costs > 0 and free.costs == 0


def test_liquidity_cap_shrinks_orders():
    c = [Candle(x.ts, x.open, x.high, x.low, x.close, 1.0) for x in series(300)]   # bijna geen omzet
    s = simulate([1] * 300, c, CostModel(0, 0, 0), 0.0, 10, 300, capital=1000.0)
    assert s.capped_orders == 1 and s.equity[0] < 1000.0 + 1e-9


def test_trade_metrics():
    sim = Sim([1000, 1100, 1050], [0.0, 0.1, -0.045], [
        Trade("a", "b", 1, 1.1, 100.0, 0.1, 1.0, 2), Trade("c", "d", 1, 0.95, -50.0, -0.05, 1.0, 2)], 2.0, 3, 2000)
    m = metrics(sim, 365, 1000.0)
    assert m["win_rate"] == 0.5 and m["profit_factor"] == 2.0 and m["expectancy_eur"] == 25.0

from datetime import UTC, datetime, timedelta

import pytest

from jplh.backtest import metrics, simulate, unit_prices, walk_forward
from jplh.config import CostModel
from jplh.data.demo import Demo
from jplh.models import AssetClass, Candle, Instrument
from jplh.strategies import FAMILIES, BuyHold, Breakout, MeanReversion, Momentum, Strategy, TrendSMA

FREE = CostModel(0.0, 0.0, 0.0)
T0 = datetime(2022, 1, 1, tzinfo=UTC)


def series(closes, opens=None):
    opens = opens or closes
    return [Candle(T0 + timedelta(days=i), o, max(o, c), min(o, c), c) for i, (o, c) in enumerate(zip(opens, closes))]


def demo(n=900, sym="BTC-EUR"):
    return Demo({sym: "crypto"}, end=T0 + timedelta(days=n)).candles(sym, "1d", n)


ALL = [BuyHold()] + [s for fam in FAMILIES.values() for s in fam]


@pytest.mark.parametrize("strat", ALL, ids=lambda s: s.label)
def test_no_lookahead(strat):
    """Een beslissing mag niet veranderen als je toekomstige koersen weghaalt."""
    candles = demo(400)
    full = strat.targets(candles)
    for cut in (150, 250, 399):
        assert strat.targets(candles[:cut]) == full[:cut]


def test_trade_executes_on_next_open():
    class OnAtTwo(Strategy):
        def __init__(self):
            super().__init__("test")

        def targets(self, candles):
            return [int(i >= 2) for i in range(len(candles))]

    candles = series([10, 10, 10, 20, 20], opens=[10, 10, 10, 15, 20])
    run = simulate(OnAtTwo(), candles, FREE)
    # Besluit op slot van dag 2, kopen op opening dag 3 (15), slot dag 3 = 20.
    assert run.equity[2] == pytest.approx(1000)
    assert run.equity[3] == pytest.approx(1000 * 20 / 15)
    assert run.trades == 1


def test_costs_lower_returns():
    candles = demo(600)
    strat = TrendSMA(10, 50)
    free = simulate(strat, candles, FREE)
    paid = simulate(strat, candles, CostModel(0.0025, 0.001, 0.0))
    assert paid.equity[-1] < free.equity[-1]
    assert paid.fees > 0


def test_min_fee_applies():
    run = simulate(BuyHold(), series([10] * 5), CostModel(0.0, 0.0, 2.0))
    assert run.fees == pytest.approx(2.0)
    assert run.equity[-1] == pytest.approx(998.0)


def test_metrics_known_values():
    m = metrics([0.1, -0.5, 0.0], trades=1, fees=0, in_market=3, periods_per_year=365)
    assert m.total_return == pytest.approx(1.1 * 0.5 - 1)
    assert m.max_drawdown == pytest.approx(0.5)


def test_fx_uses_inverse_price():
    inst = Instrument("EURUSD=X", AssetClass.FX, "yahoo", "USD")
    c = unit_prices(series([1.25]), inst)[0]
    assert c.close == pytest.approx(0.8)


def test_walk_forward_only_counts_unseen_periods():
    inst = Instrument("BTC-EUR", AssetClass.CRYPTO, "bitvavo")
    candles = demo(900)
    res = walk_forward("trend", FAMILIES["trend"], candles, inst, FREE, train=500, test=100)
    assert len(res.folds) == 4
    assert all(f.test_start >= 500 for f in res.folds)
    labels = {s.label for s in FAMILIES["trend"]}
    assert all(f.chosen in labels for f in res.folds)
    # Koop-en-houd over dezelfde 400 dagen.
    bh = candles[-1].close / candles[500].open - 1
    assert res.benchmark.total_return == pytest.approx(bh, rel=1e-6)


def test_walk_forward_needs_enough_data():
    inst = Instrument("BTC-EUR", AssetClass.CRYPTO, "bitvavo")
    assert walk_forward("trend", FAMILIES["trend"], demo(300), inst, FREE) is None


def test_indicators_behave():
    up = series([float(i) for i in range(1, 300)])
    assert TrendSMA(10, 50).targets(up)[-1] == 1
    assert Momentum(30).targets(up)[-1] == 1
    assert Breakout(20, 10).targets(up)[-1] == 1
    down = series([float(i) for i in range(300, 1, -1)])
    assert TrendSMA(10, 50).targets(down)[-1] == 0
    assert MeanReversion(14, 30, 55).targets(down)[-1] == 1  # overdreven daling: kopen

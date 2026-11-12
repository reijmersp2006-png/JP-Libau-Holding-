import math
from datetime import UTC, datetime, timedelta

import pytest
from jplh.config import load_config
from jplh.models import Candle
from jplh.strategies import Strategy

from nexus import audit, datasets, lab, stats
from test_lab import series


def test_attribution_components_sum_exactly():
    c = series(900)
    cfg = load_config()
    sp = lab.spec("volatility_filter")
    strat = sp.build()
    t = strat.targets(c)
    a = audit.attribution(t, c, cfg.costs["stocks"], 0.001, 400, 900, causes=audit.volfilter_causes(strat, c))
    assert abs(a["check_sum"]) < 1e-12
    assert math.log1p(a["strategy_return"]) - math.log1p(a["benchmark_return"]) == pytest.approx(a["log_excess_total"])
    out = a["components_log"].get("buiten de markt", 0.0)
    assert sum(a["out_of_market_by_cause_log"].values()) == pytest.approx(out)
    assert sum(a["out_of_market_by_regime_log"].values()) == pytest.approx(out)


def test_audit_report_complete_and_original_preserved():
    cfg = load_config()
    inst = cfg.instrument("IWDA.AS")
    c = series(900)
    sp = lab.spec("volatility_filter")
    before = lab.run_backtest(sp, inst, c, cfg.costs["stocks"])
    a = audit.audit_backtest(sp, inst, c, cfg.costs["stocks"])
    assert a["original_result"]["out_of_sample"] == before["out_of_sample"]
    assert sp.params == {"fast": 50, "slow": 200, "vol_window": 20, "lookback": 252}   # ongewijzigd
    assert a["causality"]["ok"] and a["data_quality"]["ok"]
    assert a["uncertainty"]["available"] and a["sensitivity"]["trials"] == 9
    md = audit.markdown(a)
    for word in ("Attributie", "Sharpe", "Sortino", "Profit factor", "Win rate", "Transactiekosten", "90%-interval"):
        assert word in md


class Peeker(Strategy):
    """Kijkt bewust één dag vooruit: de audit moet dat vinden."""

    def __init__(self):
        super().__init__("spiek")

    def targets(self, candles):
        return [int(i + 1 < len(candles) and candles[i + 1].close > candles[i].close) for i in range(len(candles))]


def test_causality_check_catches_look_ahead():
    r = audit.causality_check(Peeker(), series(400))
    assert not r["ok"] and r["mismatches"]


def test_data_quality_flags_bad_bars():
    c = series(50)
    bad = c[:10] + [Candle(c[10].ts, 10, 9, 11, 10, 1)] + c[11:20] + [Candle(c[20].ts, c[20].open, c[20].high * 3,
                                                                              c[20].low, c[20].close * 2, 1)] + c[21:]
    q = audit.data_quality(bad)
    assert not q["ok"] and q["invalid_bars"] and q["jumps"]


def test_stats_bootstrap_deterministic_and_psr():
    up = [0.001 + 0.01 * math.sin(i) for i in range(500)]
    flat = [0.01 * math.sin(i) for i in range(500)]
    assert stats.block_bootstrap(up, stats.mean, 50) == stats.block_bootstrap(up, stats.mean, 50)
    assert stats.probabilistic_sharpe(up) > 0.95 > stats.probabilistic_sharpe(flat)
    assert stats.deflated_sharpe(up, 1000) < stats.probabilistic_sharpe(up)
    u = stats.excess_uncertainty(up, flat, 252)
    assert u["p_excess_annual_positive"] > 0.9 and u["excess_annual_ci90"][0] < u["excess_annual"] < u["excess_annual_ci90"][1]


def test_expected_value_formula():
    ev = stats.expected_value([10, 10, -5, -5], [1, 1, 1, 1])
    assert ev["expected_value"] == pytest.approx(0.5 * 10 - 0.5 * 5 - 1)


def test_to_eur_uses_only_known_fx():
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    fx = [Candle(t0 + timedelta(days=i), 1, 1, 1, 1.0 + i, 0) for i in range(5)]       # koers 1,2,3,...
    px = [Candle(t0 + timedelta(days=i, hours=14), 10, 10, 10, 10, 1) for i in range(5)]
    eur = datasets.to_eur(px, fx)
    # Dag i (14:00) kent alleen de slotkoers van dag i-1 (vast om middernacht); dag 0 kent er nog geen.
    assert [c.ts for c in eur] == [c.ts for c in px[1:]]
    assert [c.close for c in eur] == pytest.approx([10 / 1, 10 / 2, 10 / 3, 10 / 4])


def test_resample_drops_incomplete_blocks():
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    h = [Candle(t0 + timedelta(hours=i), i, i + 1, i - 1, i + 0.5, 1) for i in range(10)]
    four = datasets.resample(h, "4h")
    assert len(four) == 2 and four[0].open == 0 and four[0].close == 3.5 and four[0].volume == 4
    assert four[1].high == 8


def test_periods_per_year():
    assert datasets.periods_per_year("1d", "crypto") == 365
    assert datasets.periods_per_year("1h", "crypto") == 8760
    assert datasets.periods_per_year("4h", "crypto") == 2190
    assert datasets.periods_per_year("5m", "crypto") == 105120

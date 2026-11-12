import json
import math
from datetime import UTC, datetime, timedelta

import pytest
from jplh.config import CostModel, load_config
from jplh.models import Candle

from nexus import alpha, datasets
from tests.test_lab import series

ZERO = (CostModel(0, 0, 0), 0.0)


def panel_of(*syms, n=900):
    return {s: series(n, seed=k) for k, s in enumerate(syms)}


@pytest.mark.parametrize("fam", [f for f in alpha.FAMILIES if f.kind == "single"], ids=lambda f: f.key)
def test_single_families_are_causal_and_bounded(fam):
    c = series(900)
    for p in fam.combos()[:3]:
        a = fam.fn(c, 252, **p)
        changed = c[:600] + [Candle(x.ts, x.open * 2, x.high * 2, x.low * 2, x.close * 2, x.volume * 5) for x in c[600:]]
        b = fam.fn(changed, 252, **p)
        assert a[:600] == b[:600]
        assert all(0.0 <= w <= 1.0 for w in a) and len(a) == len(c)


@pytest.mark.parametrize("key", ["dual_momentum", "risk_parity", "regime_switch"])
def test_portfolio_families_are_causal_and_fully_invested_at_most(key):
    fam = alpha.family(key)
    syms = ["IWDA.AS", "IEAG.AS", "XEON.DE", "ASML.AS"]
    pnl = panel_of(*syms)
    p = {**alpha.fam_static(fam, syms), **fam.combos()[0]}
    a = fam.fn(pnl, 252, **p)
    pnl2 = {s: v[:600] + [Candle(x.ts, x.open * 3, x.high * 3, x.low * 3, x.close * 3, x.volume) for x in v[600:]]
            for s, v in pnl.items()}
    assert fam.fn(pnl2, 252, **p)[:600] == a[:600]
    assert all(sum(w.values()) <= 1 + 1e-9 for w in a)


def test_full_weight_without_costs_equals_buy_and_hold():
    c = series(400)
    s = alpha.simulate_weights({"X": c}, [{"X": 1.0}] * 400, {"X": ZERO}, 10, 400)
    assert s.equity[-1] == pytest.approx(1000 * c[-1].close / c[10].open)
    assert s.costs == 0 and s.orders == 1


def test_costs_are_charged_and_band_limits_trading():
    c = series(400)
    w = [{"X": 0.5 + 0.02 * math.sin(i)} for i in range(400)]          # schommelt binnen de band
    cm = {"X": (CostModel(0.001, 0.0005, 1.0), 0.002)}
    s = alpha.simulate_weights({"X": c}, w, cm, 10, 400, band=0.05)
    assert s.costs > 1.0
    s2 = alpha.simulate_weights({"X": c}, w, cm, 10, 400, band=0.0)
    assert s2.orders > 5 * s.orders and s2.costs > s.costs


def test_round_trip_pnl_matches_equity_change():
    c = series(300)
    w = [{"X": 1.0 if 50 <= i < 120 else 0.0} for i in range(300)]
    s = alpha.simulate_weights({"X": c}, w, {"X": (CostModel(0.001, 0.001, 1.0), 0.002)}, 10, 300)
    assert len(s.trips) == 1 and s.trips[0].exit_ts is not None
    assert s.trips[0].pnl_eur == pytest.approx(s.equity[-1] - 1000.0)


def test_cash_never_negative_with_min_fee():
    c = series(200)
    w = [{"X": 1.0}] * 200
    s = alpha.simulate_weights({"X": c}, w, {"X": (CostModel(0.01, 0.01, 5.0), 0.01)}, 5, 200, capital=50.0)
    assert min(s.equity) > 0


def test_split_keeps_holdout_after_folds():
    sp = alpha.make_split(1500, 260)
    assert sp.folds[-1][1] == sp.dev_end < sp.n and sp.folds[0][0] > sp.warm
    assert alpha.make_split(500, 260) is None


def test_holdout_ledger_counts_uses(tmp_path):
    led = alpha.HoldoutLedger(tmp_path / "l.jsonl")
    assert led.record("IWDA.AS@1d", "2025-07-01", "vol_target", {"a": 1}, "r1") == 1
    assert led.record("IWDA.AS@1d", "2025-07-01", "tsmom", {}, "r2") == 2
    assert led.uses("IWDA.AS@1d", "2025-07-01") == 2 and led.uses("BTC@1d", "2025-07-01") == 0


def test_discover_on_synthetic_store(tmp_path, demo_home):
    cfg = load_config()
    data = datasets.ResearchData(cfg, demo_home / "data" / "holding.sqlite3")
    rep = alpha.discover(data, "1d", ["BTC-EUR"], families=["vol_target", "funding_oi"],
                         ledger=alpha.HoldoutLedger(tmp_path / "l.jsonl"))
    assert rep["summary"]["trials_total"] == len(alpha.family("vol_target").combos())
    assert {u["family"] for u in rep["unavailable"]} == {"funding_oi"}
    # De demo heeft maar enkele dagen: geen oordeel, geen verzonnen uitkomst.
    assert all(r["status"] == "insufficient_history" for r in rep["results"])
    assert "Alpha Research Engine" in alpha.markdown(rep)
    json.dumps(rep, default=str)

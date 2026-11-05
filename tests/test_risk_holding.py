from datetime import timedelta

import pytest

from conftest import NOW, flat, seed_prices

from jplh.holding import Holding
from jplh.models import Side, Signal


def buy(sym, size=None):
    return Signal(sym, Side.BUY, "test", "test", size)


def failed(d):
    return {c.rule for c in d.checks if not c.passed}


def test_buy_capped_at_position_limit(holding):
    d = holding.submit(buy("BTC-EUR", 900.0), NOW)
    assert d.approved
    assert d.size_eur == pytest.approx(250.0)


def test_meme_capped_at_five_percent(holding):
    d = holding.submit(buy("DOGE-EUR"), NOW)
    assert d.approved
    assert d.size_eur == pytest.approx(50.0)
    d2 = holding.submit(buy("PEPE-EUR"), NOW)
    assert not d2.approved and "ordergrootte" in failed(d2)


def test_kill_switch_blocks_everything(holding, tmp_path):
    assert holding.submit(buy("BTC-EUR"), NOW).approved
    (tmp_path / "KILL").write_text("x")
    d = holding.submit(Signal("BTC-EUR", Side.SELL, "test", "uit"), NOW)
    assert not d.approved and "noodstop" in failed(d)


def test_stale_price_refused(holding):
    d = holding.submit(buy("BTC-EUR"), NOW + timedelta(hours=10))
    assert not d.approved and "koers_vers" in failed(d)


def test_stale_fx_blocks_usd_stock(config, store, tmp_path):
    seed_prices(store, config, {})
    h = Holding(config, store, base_dir=tmp_path, log_dir=None)
    # Koers AAPL vers, wisselkoers 10 uur oud.
    store.save_candles("AAPL", "1h", flat(200.0, n=1, end=NOW + timedelta(hours=10)), "t", NOW)
    d = h.submit(buy("AAPL"), NOW + timedelta(hours=10))
    assert not d.approved and "koers_vers" in failed(d)


def test_no_averaging_down(holding, store, config):
    assert holding.submit(buy("ETH-EUR", 100.0), NOW).approved
    seed_prices(store, config, {"ETH-EUR": 80.0}, end=NOW + timedelta(hours=1))
    d = holding.submit(buy("ETH-EUR", 50.0), NOW + timedelta(hours=1))
    assert not d.approved and "geen_bijkopen_bij_verlies" in failed(d)


def test_drawdown_pauses_and_resume(config, store, tmp_path):
    seed_prices(store, config, {})
    h = Holding(config, store, base_dir=tmp_path, log_dir=None)
    for sym in ("BTC-EUR", "IWDA.AS", "ASML.AS"):
        assert h.submit(buy(sym), NOW).approved
    later = NOW + timedelta(hours=1)
    seed_prices(store, config, {"BTC-EUR": 30.0, "IWDA.AS": 30.0, "ASML.AS": 30.0}, end=later)
    d = h.submit(buy("GC=F"), later)
    assert not d.approved
    assert {"niet_gepauzeerd", "max_drawdown"} <= failed(d)
    # Verkopen mag altijd om risico af te bouwen.
    assert h.submit(Signal("BTC-EUR", Side.SELL, "test", "afbouwen"), later).approved
    h.resume(later)
    assert h.meta["paused_reason"] is None


def test_daily_trade_limit(holding, config):
    syms = [i.symbol for i in config.instruments]
    approved = 0
    for i in range(12):
        sym = syms[i % len(syms)]
        if holding.submit(buy(sym, 10.0), NOW).approved:
            approved += 1
    assert approved == config.risk.max_trades_per_day


def test_state_survives_restart(holding, config, store, tmp_path):
    holding.submit(buy("BTC-EUR", 100.0), NOW)
    again = Holding(config, store, base_dir=tmp_path, log_dir=None)
    assert "BTC-EUR" in again.portfolio.positions
    assert again.portfolio.cash_eur == pytest.approx(holding.portfolio.cash_eur)


def test_every_decision_journaled(holding, tmp_path):
    holding.submit(buy("BTC-EUR"), NOW)
    holding.submit(buy("NOPE"), NOW)
    kinds = [k for _, k, _ in holding.store.events()]
    assert kinds.count("decision") == 2 and "fill" in kinds
    assert list((tmp_path / "logs").glob("journal-*.jsonl"))


def test_paper_costs_applied(holding):
    d = holding.submit(buy("BTC-EUR", 100.0), NOW)
    pos = holding.portfolio.positions["BTC-EUR"]
    assert pos.avg_price_eur == pytest.approx(100.0 * 1.001)
    assert holding.portfolio.fees_eur == pytest.approx(0.25)
    assert d.approved

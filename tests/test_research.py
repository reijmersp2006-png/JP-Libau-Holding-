import math
from datetime import UTC, datetime, timedelta

from jplh.config import CostModel, load_config
from jplh.desks import ALL_CANDIDATES, Desk, choose_strategy
from jplh.models import AssetClass, Candle, Fill, Instrument, Side
from jplh.research import adjustments, review, round_trips, track_record
from jplh.scouts import recent, scan
from jplh.store import Store
from jplh.strategies import BuyHold, Breakout, MeanReversion, Momentum, TrendSMA

NOW = datetime(2026, 11, 5, 12, 5, tzinfo=UTC)
INST = Instrument("BTC-EUR", AssetClass.CRYPTO, "bitvavo")
COST = CostModel(0.0025, 0.001)


def daily(prices, end=NOW):
    start = (end - timedelta(days=len(prices))).replace(hour=0, minute=0)
    return [Candle(start + timedelta(days=i), p, p * 1.01, p * 0.99, p, 1.0) for i, p in enumerate(prices)]


def fill(side, day, price, qty=1.0, strategy="trend(fast=20, slow=100, band=0.01)"):
    return Fill("BTC-EUR", side, qty, price, 0.25, NOW - timedelta(days=day), strategy)


def test_round_trips_pairs_buy_and_sell():
    trips = round_trips([fill(Side.BUY, 20, 100), fill(Side.SELL, 10, 110), fill(Side.BUY, 5, 120)])
    assert len(trips) == 1
    t = trips[0]
    assert t.entry_price == 100 and t.exit_price == 110
    assert t.pnl_pct == (110 - 0.5) / 100 - 1


def test_review_sees_early_exit_and_better_hold():
    # 300 dagen vlak, dan stijgt de koers door, ook na onze verkoop.
    prices = [100.0] * 300 + [100 + i for i in range(30)]
    candles = daily(prices)
    entry, exit_ = candles[300].ts + timedelta(hours=1), candles[310].ts + timedelta(hours=1)
    trip = round_trips([Fill("BTC-EUR", Side.BUY, 1, 100.0, 0.25, entry, "momentum(lookback=30, threshold=0.0)"),
                        Fill("BTC-EUR", Side.SELL, 1, 110.0, 0.25, exit_, "momentum(lookback=30, threshold=0.0)")])[0]
    r = review(trip, candles, INST, COST, ALL_CANDIDATES, NOW)
    assert r is not None
    assert r["verdict"] == "winst"
    assert r["after_exit_pct"] > 0.03
    assert any("te vroeg verkocht" in l for l in r["lessons"])
    assert r["hold_pct"] > r["pnl_pct"]
    assert any("vasthouden was beter" in l for l in r["lessons"])


def test_review_waits_a_week_of_data():
    candles = daily([100.0] * 300)
    trip = round_trips([Fill("BTC-EUR", Side.BUY, 1, 100.0, 0.0, NOW - timedelta(days=5), "x"),
                        Fill("BTC-EUR", Side.SELL, 1, 100.0, 0.0, NOW - timedelta(days=2), "x")])[0]
    assert review(trip, candles, INST, COST, ALL_CANDIDATES, NOW) is None


def test_track_record_penalises_losers_only_after_enough_trades():
    lose = {"strategy": "trend(a)", "pnl_pct": -0.02, "edge_vs_hold": -0.03}
    win = {"strategy": "uitbraak(b)", "pnl_pct": 0.05, "edge_vs_hold": 0.04}
    hold = {"strategy": "koop_en_houd", "pnl_pct": -0.1, "edge_vs_hold": -0.01}
    assert adjustments(track_record([lose, lose])) == {}
    adj = adjustments(track_record([lose] * 3 + [win] * 3 + [hold] * 3))
    assert adj["trend(a)"] < 0 < adj["uitbraak(b)"]
    assert "koop_en_houd" not in adj
    assert abs(adj["trend(a)"]) > adj["uitbraak(b)"]   # straf weegt zwaarder dan bonus


def test_penalty_changes_the_weekly_choice():
    import random
    rng = random.Random(4)
    p, prices = 100.0, []
    for _ in range(600):
        p *= math.exp(rng.gauss(0.001, 0.03))
        prices.append(p)
    candles = daily(prices)
    config = load_config(None)
    best, _ = choose_strategy(candles, INST, config)
    forced, _ = choose_strategy(candles, INST, config, adjust={best: -10.0})
    assert forced != best


def test_every_strategy_explains_with_numbers():
    candles = daily([100 + 10 * math.sin(i / 15) + i * 0.05 for i in range(300)])
    for s in [BuyHold(), TrendSMA(20, 100), Momentum(90), Breakout(55, 20), MeanReversion(14, 30, 55)]:
        text = s.explain(candles)
        assert len(text) > 20
        if not isinstance(s, BuyHold):
            assert any(ch.isdigit() for ch in text), text


def test_desk_learns_once_from_closed_trade(tmp_path):
    config = load_config(None)
    market = Store(tmp_path / "m.sqlite3")
    candles = daily([100.0] * 300 + [100 + i for i in range(30)])
    market.save_observed("BTC-EUR", "1d", candles, "test", timedelta(days=1))
    desk = Desk("crypto", config, market, Store(tmp_path / "c.sqlite3"), None, tmp_path / "logs")
    desk.holding.journal.fill(Fill("BTC-EUR", Side.BUY, 1, 100.0, 0.25, candles[300].ts + timedelta(hours=1), "koop_en_houd"))
    desk.holding.journal.fill(Fill("BTC-EUR", Side.SELL, 1, 110.0, 0.25, candles[310].ts + timedelta(hours=1), "koop_en_houd"))
    notes = desk.learn(NOW)
    assert len(notes) == 1 and "terugblik BTC-EUR" in notes[0]
    assert desk.learn(NOW) == []
    assert len(desk.reflections()) == 1


def test_scouts_spot_a_spike_once(tmp_path):
    market = Store(tmp_path / "m.sqlite3")
    import random
    rng = random.Random(1)
    p, hourly = 100.0, []
    end = NOW.replace(minute=0)
    for i in range(24 * 20):
        p *= math.exp(rng.gauss(0, 0.002))
        hourly.append(Candle(end - timedelta(hours=24 * 20 - i), p, p, p, p, 100.0))
    last = hourly[-1]
    hourly[-1] = Candle(last.ts, p, p * 1.05, p, p * 1.05, 5000.0)   # +5% en 50x volume in één uur
    market.save_observed("BTC-EUR", "1h", hourly, "test", timedelta(hours=1))
    found = scan(market, [("BTC-EUR", "Bitcoin")], NOW)
    kinds = {a.kind for a in found}
    assert "sprong" in kinds and "volume" in kinds
    assert scan(market, [("BTC-EUR", "Bitcoin")], NOW + timedelta(hours=1)) == []
    assert recent(market)[0]["symbol"] == "BTC-EUR"


def test_scouts_ignore_calm_markets(tmp_path):
    market = Store(tmp_path / "m.sqlite3")
    end = NOW.replace(minute=0)
    hourly = [Candle(end - timedelta(hours=400 - i), 100 + (i % 2) * 0.1, 101, 99, 100 + (i % 2) * 0.1, 100.0)
              for i in range(400)]
    market.save_observed("BTC-EUR", "1h", hourly, "test", timedelta(hours=1))
    assert scan(market, [("BTC-EUR", "Bitcoin")], NOW) == []


def test_watchlist_is_loaded_and_never_traded():
    config = load_config(None)
    assert any(w.symbol == "^GSPC" for w in config.watch)
    traded = {i.symbol for i in config.instruments}
    assert not traded & {w.symbol for w in config.watch}

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from jplh.lessons import lessons, record_backtests, review_entries, review_refusals, summary
from jplh.models import Candle, Fill, Side
from jplh.store import Store

T0 = datetime(2026, 11, 1, 12, tzinfo=UTC)


def _desk(prices):
    """Een nep-afdeling: genoeg om het lessenboek te testen. ``prices`` = koers per uur vanaf T0."""
    market, book = Store(":memory:"), Store(":memory:")
    candles = [Candle(T0 + timedelta(hours=h), p, p, p, p) for h, p in enumerate(prices)]
    market.save_candles("ASML.AS", "1h", candles, "test", T0)
    holding = SimpleNamespace(store=book, _save=lambda: None)
    return SimpleNamespace(cls="stocks", meta={}, market=market, holding=holding)


def _refuse(desk, ts, rule="kostenwacht"):
    desk.holding.store.add_event(ts, "decision", {
        "instrument": "ASML.AS", "side": "buy", "approved": False, "reason": "geweigerd",
        "checks": [{"rule": rule, "passed": False, "detail": ""}, {"rule": "koers_vers", "passed": True, "detail": ""}]})


def test_a_refusal_is_judged_a_week_later_once_per_day_and_only_with_known_prices():
    desk = _desk([100.0] * 24 + [90.0] * 24 * 20)          # na een dag zakt de koers 10%
    _refuse(desk, T0 + timedelta(hours=2))
    _refuse(desk, T0 + timedelta(hours=3))                   # dezelfde weigering een uur later: telt niet dubbel
    assert review_refusals(desk, desk.market, T0 + timedelta(days=3)) == []      # nog geen week: niet oordelen
    got = review_refusals(desk, desk.market, T0 + timedelta(days=8))
    assert len(got) == 1 and got[0]["move"] < 0 and "bespaarde geld" in got[0]["text"]
    assert review_refusals(desk, desk.market, T0 + timedelta(days=9)) == []      # al beoordeeld
    s = summary(lessons(desk.market))
    assert s["rules"][0]["rule"] == "kostenwacht" and s["rules"][0]["saved"] == 1


def test_entries_show_if_a_desk_buys_too_expensive():
    desk = _desk([100.0] * 2 + [95.0] * 24 * 20)
    desk.holding.store.add_fill(Fill("ASML.AS", Side.BUY, 1.0, 100.2, 1.25, T0 + timedelta(hours=1, minutes=30)))
    assert review_entries(desk, desk.market, T0 + timedelta(days=10)) == []
    got = review_entries(desk, desk.market, T0 + timedelta(days=16))
    assert len(got) == 1 and got[0]["gap"] > 0.04 and "duurder" in got[0]["text"]
    assert summary(lessons(desk.market))["entry"]["n"] == 1


def test_backtests_go_in_the_book_once_a_week_with_the_change():
    market = Store(":memory:")
    risk = {"backtest": {"base": {"return": 0.65, "sharpe": 1.13, "max_dd": 0.237}, "wins": True}}
    arena = {"desks": {"crypto": {"name": "Crypto Lab", "board": [{"name": "trend", "live": False}]}}}
    first = record_backtests(market, T0, arena, risk)
    assert first and "Sharpe 1,13" in first["text"] and "Crypto Lab: trend" in first["text"]
    assert record_backtests(market, T0 + timedelta(days=2), arena, risk) is None
    risk["backtest"]["base"]["sharpe"] = 1.20
    later = record_backtests(market, T0 + timedelta(days=7), arena, risk)
    assert "vorige week 1,13, beter" in later["text"]

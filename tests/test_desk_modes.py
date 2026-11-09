import dataclasses
from datetime import UTC, datetime, timedelta

import pytest

from jplh.config import ConfigError, load_config
from jplh.desks import Desk, SWITCH_MARGIN
from jplh.models import Candle, Fill, Side
from jplh.store import Store

NOW = datetime(2026, 11, 5, 12, 5, tzinfo=UTC)


def _daily(sym_prices, end=NOW):
    start = (end - timedelta(days=len(sym_prices))).replace(hour=0, minute=0)
    return [Candle(start + timedelta(days=i), p, p, p, p, 1.0) for i, p in enumerate(sym_prices)]


def _market(tmp_path, trend_up=True, symbols=("BTC-EUR", "ETH-EUR", "SOL-EUR", "XRP-EUR")):
    m = Store(tmp_path / "m.sqlite3")
    for k, sym in enumerate(symbols):
        prices = [100 * (1.002 if trend_up else 0.998) ** i * (1 + 0.01 * k) for i in range(400)]
        m.save_observed(sym, "1d", _daily(prices), "t", timedelta(days=1))
        last = prices[-1]
        h = [Candle(NOW.replace(minute=0) - timedelta(hours=5 - i), last, last, last, last, 1.0) for i in range(5)]
        m.save_observed(sym, "1h", h, "t", timedelta(hours=1))
    return m


def _cfg(**modes):
    c = load_config(None)
    return dataclasses.replace(c, desk_modes={**c.desk_modes, **modes})


def test_default_modes_are_core_and_hunt():
    c = load_config(None)
    assert c.desk_modes == {"crypto": "vasthouden_marktweer", "meme": "actief", "stocks": "vasthouden",
                            "metals": "vasthouden", "fx": "vasthouden"}


def test_unknown_mode_is_refused(tmp_path):
    p = tmp_path / "h.toml"
    p.write_text('[desk_mode]\ncrypto = "yolo"\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(p)


def test_hold_desk_selects_hold_for_everything_and_buys(tmp_path):
    desk = Desk("crypto", _cfg(crypto="vasthouden"), _market(tmp_path), Store(tmp_path / "c.sqlite3"), None, None)
    rnd = desk.run(NOW)
    assert set(desk.selection().values()) == {"koop_en_houd"}
    assert {d.signal.instrument for d in rnd.decisions if d.approved} == {"BTC-EUR", "ETH-EUR", "SOL-EUR", "XRP-EUR"}


def test_weather_brake_keeps_crypto_out_in_a_falling_market(tmp_path):
    desk = Desk("crypto", _cfg(), _market(tmp_path, trend_up=False), Store(tmp_path / "c.sqlite3"), None, None)
    rnd = desk.run(NOW)
    assert desk.mode == "vasthouden_marktweer"
    assert not [d for d in rnd.decisions if d.approved]
    ok, text = desk.regime(NOW)
    assert ok is False and "200-dagengemiddelde" in text


def test_weather_brake_sells_when_weather_turns(tmp_path):
    desk = Desk("crypto", _cfg(), _market(tmp_path, trend_up=False), Store(tmp_path / "c.sqlite3"), None, None)
    fill = Fill("BTC-EUR", Side.BUY, 0.1, 50.0, 0.1, NOW - timedelta(days=3), "koop_en_houd")
    desk.holding.portfolio.apply(fill)
    desk.holding.journal.fill(fill)
    rnd = desk.run(NOW)
    sells = [d for d in rnd.decisions if d.signal.side is Side.SELL]
    assert sells and sells[0].approved
    assert "noodrem" in sells[0].signal.reason


def test_rebalance_trims_the_winner_after_a_quarter(tmp_path):
    market = _market(tmp_path)
    desk = Desk("crypto", _cfg(crypto="vasthouden"), market, Store(tmp_path / "c.sqlite3"), None, None)
    desk.run(NOW)
    assert len(desk.holding.portfolio.positions) == 4
    later = NOW + timedelta(days=100)
    t = later.replace(minute=0) - timedelta(hours=1)
    for sym in ("BTC-EUR", "ETH-EUR", "SOL-EUR", "XRP-EUR"):
        c = market.candles(sym, "1h", limit=1)[-1].close * (2 if sym == "BTC-EUR" else 1)
        market.save_observed(sym, "1h", [Candle(t, c, c, c, c, 1.0)], "t", timedelta(hours=1))
    trims = desk.maybe_rebalance(later)
    btc = [d for d in trims if d.signal.instrument == "BTC-EUR"]
    assert btc and btc[0].signal.side is Side.SELL and btc[0].approved
    assert "herverdeling" in btc[0].signal.reason
    assert desk.maybe_rebalance(later + timedelta(days=1)) == []


def test_mode_change_triggers_new_selection(tmp_path):
    market = _market(tmp_path)
    book = Store(tmp_path / "c.sqlite3")
    d1 = Desk("crypto", _cfg(crypto="actief"), market, book, None, None)
    d1.maybe_reselect(NOW)
    d2 = Desk("crypto", _cfg(crypto="vasthouden"), market, book, None, None)
    d2.maybe_reselect(NOW + timedelta(hours=1))
    assert set(d2.selection().values()) == {"koop_en_houd"}


def test_switch_margin_is_meaningful():
    assert SWITCH_MARGIN >= 0.2


def test_weather_brake_waits_for_the_margin(tmp_path):
    m = Store(tmp_path / "m.sqlite3")
    m.save_observed("BTC-EUR", "1d", _daily([100.0] * 399 + [98.0]), "t", timedelta(days=1))  # 2% onder het gemiddelde
    desk = Desk("crypto", _cfg(), m, Store(tmp_path / "c.sqlite3"), None, None)
    desk.meta["regime_bull"] = True
    ok, text = desk.regime(NOW)
    assert ok is True and "marge" in text           # binnen 5%: vorige (goede) stand blijft
    desk.meta.pop("regime_bull")
    ok, _ = desk.regime(NOW)
    assert ok is False                              # zonder vorige stand telt de kant van de lijn


def test_desks_are_rebalanced_back_to_their_share_each_quarter(tmp_path):
    from jplh.desks import open_desks, rebalance_desks
    m = _market(tmp_path, symbols=("BTC-EUR", "ETH-EUR", "SOL-EUR", "XRP-EUR", "IWDA.AS", "AAPL"))
    cfg = dataclasses.replace(_cfg(), desks={"crypto": 0.5, "stocks": 0.5})
    desks = open_desks(cfg, tmp_path, m, use_kill_file=False)
    start = NOW - timedelta(days=100)
    for d in desks.values():
        d.meta["started_at"] = start.isoformat()
    desks["crypto"].holding.portfolio.cash_eur += 400.0      # crypto is flink gegroeid
    total = sum(d.holding.portfolio.equity_eur(d.holding.prices(NOW)) for d in desks.values())
    notes = rebalance_desks(desks, m, NOW)
    assert notes and "Crypto Lab geeft" in notes[0]
    eq = {c: d.holding.portfolio.equity_eur(d.holding.prices(NOW)) for c, d in desks.items()}
    assert abs(eq["crypto"] - eq["stocks"]) < 1.0
    assert abs(sum(eq.values()) - total) < 1e-6              # er verdwijnt geen geld
    assert desks["crypto"].meta["transfers_eur"] < 0 < desks["stocks"].meta["transfers_eur"]
    assert rebalance_desks(desks, m, NOW + timedelta(days=1)) == []   # pas weer na een kwartaal

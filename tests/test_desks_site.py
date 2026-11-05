import json
from datetime import UTC, datetime, timedelta

import pytest

from jplh.config import load_config
from jplh.data.demo import Demo
from jplh.desks import Desk, desk_config, open_desks
from jplh.paper import build_demo
from jplh.site import build_state, write_site
from jplh.store import Store

NOW = datetime(2026, 11, 5, 12, 5, tzinfo=UTC)


@pytest.fixture
def world(tmp_path):
    config = load_config(None)
    market = Store(tmp_path / "data" / "holding.sqlite3")
    kinds = {i.symbol: i.asset_class.value for i in config.instruments}
    for inst in config.instruments:
        market.save_observed(inst.symbol, "1h", Demo(kinds, end=NOW).candles(inst.symbol, "1h", 72), "demo",
                             timedelta(hours=1))
        market.save_observed(inst.symbol, "1d", Demo(kinds, seed=3, end=NOW).candles(inst.symbol, "1d", 600), "demo",
                             timedelta(days=1))
    return config, market, tmp_path


def test_desk_capital_and_limits(world):
    config = world[0]
    caps = {c: desk_config(config, c).start_capital_eur for c in config.desks}
    assert sum(caps.values()) == pytest.approx(config.start_capital_eur)
    assert caps["meme"] == pytest.approx(50.0)
    metals = desk_config(config, "metals").risk
    assert metals.max_position_pct == pytest.approx(0.5)
    assert metals.max_class_pct["metals"] == 1.0 and metals.max_class_pct["crypto"] == 0.0


def test_desks_are_separate(world):
    config, market, home = world
    desks = open_desks(config, home, market)
    for d in desks.values():
        d.run(NOW)
    for cls, d in desks.items():
        held = set(d.holding.portfolio.positions)
        own = {i.symbol for i in d.instruments}
        assert held <= own, f"{cls} handelt buiten zijn afdeling"
        assert (home / "data" / "desks" / f"{cls}.sqlite3").exists()
        assert d.selection(), f"{cls} heeft geen strategie gekozen"


def test_reselect_weekly(world):
    config, market, home = world
    desk = Desk("crypto", config, market, Store(home / "c.sqlite3"), None, None)
    assert desk.maybe_reselect(NOW) or desk.selection()
    assert desk.maybe_reselect(NOW + timedelta(days=1)) == []
    first = desk.meta["selected_at"]
    desk.maybe_reselect(NOW + timedelta(days=8))
    assert desk.meta["selected_at"] != first


def test_desk_never_uses_future_prices(world):
    config, market, home = world
    desk = Desk("crypto", config, market, Store(home / "c.sqlite3"), None, None)
    past = NOW - timedelta(hours=30)
    prices = desk.holding.prices(past)
    for inst in desk.instruments:
        assert prices.ts(inst.symbol) <= past


def test_state_and_site(world, tmp_path):
    config, market, home = world
    desks = open_desks(config, home, market)
    for i in range(3, -1, -1):
        for d in desks.values():
            d.run(NOW - timedelta(hours=i))
    state = build_state(config, desks, market, home, NOW)
    assert {d["id"] for d in state["desks"]} == set(config.desks)
    assert state["total"]["capital_eur"] == pytest.approx(1000.0)
    assert len(state["total"]["equity_curve"]) == 4
    assert [m["id"] for m in state["missions"]][-1] == "live"
    index = write_site(state, tmp_path / "site")
    assert index.exists()
    assert json.loads((tmp_path / "site" / "state.json").read_text())["name"] == config.name


def test_demo_world(tmp_path):
    site = build_demo(load_config(None), tmp_path / "demo", hours=6, now=NOW)
    state = json.loads((site / "state.json").read_text())
    assert state["demo"] is True
    assert (site / "index.html").read_text().count("JP-libau") >= 1

from datetime import UTC, datetime

import pytest
from jplh.config import load_config

from nexus.db import Database
from nexus.paper import PaperEngine, Quote


class Feed:
    def __init__(self):
        self.px = {"BTC-EUR": 60000.0, "IWDA.AS": 100.0}
        self.vol = {"BTC-EUR": 1e9, "IWDA.AS": 1e9}
        self.label = "DELAYED"

    def __call__(self, sym):
        return Quote(sym, self.px.get(sym), datetime.now(tz=UTC), self.label, self.vol.get(sym))


@pytest.fixture
def env():
    db = Database("sqlite:///:memory:")
    feed, killed = Feed(), {"on": False}
    eng = PaperEngine(db, load_config(), feed, lambda: killed["on"])
    return eng, feed, killed


def buy(eng, key, sym="BTC-EUR", size=100.0, cls="crypto"):
    return eng.submit(proposal_id=None, evaluation_id=1, key=key, symbol=sym, asset_class=cls, side="buy", size_eur=size)


def test_buy_fill_fees_slippage_and_reconcile(env):
    eng, feed, _ = env
    o = buy(eng, "k1")
    fills = eng.step()
    assert fills[0]["status"] == "filled"
    cost = eng.config.costs["crypto"]
    assert fills[0]["price_eur"] == pytest.approx(60000 * (1 + 0.0005 + cost.slippage_pct))
    assert fills[0]["fee_eur"] == pytest.approx(100 * cost.fee_pct)
    v = eng.valuation()
    assert v["cash_eur"] == pytest.approx(900.0)
    assert v["cash_eur"] + v["positions_value_eur"] == pytest.approx(v["equity_eur"])
    assert v["equity_eur"] < 1000.0                       # kosten en spread zijn echt betaald
    assert eng.reconcile()["ok"]
    assert buy(eng, "k1")["duplicate"] is True and buy(eng, "k1")["order_id"] == o["order_id"]


def test_partial_fills_over_several_rounds(env):
    eng, feed, _ = env
    feed.vol["IWDA.AS"] = 4000.0                          # 1% = €40 per ronde
    buy(eng, "k2", "IWDA.AS", 100.0, "stocks")
    s1 = eng.step()[0]
    assert s1["status"] == "partially_filled"
    eng.step()
    s3 = eng.step()[0]
    assert s3["status"] == "filled"
    assert eng.orders()[0]["filled_notional_eur"] == pytest.approx(100.0)
    assert eng.reconcile()["ok"]


def test_sell_realizes_pnl_and_closes_position(env):
    eng, feed, _ = env
    buy(eng, "k3")
    eng.step()
    feed.px["BTC-EUR"] = 66000.0
    eng.submit(proposal_id=None, evaluation_id=1, key="k3s", symbol="BTC-EUR", asset_class="crypto", side="sell",
               size_eur=10_000)
    eng.step()
    v = eng.valuation()
    assert v["positions"] == [] and v["realized_eur"] > 5.0
    assert v["equity_eur"] == pytest.approx(v["cash_eur"])
    assert eng.reconcile()["ok"]
    with pytest.raises(ValueError):
        eng.submit(proposal_id=None, evaluation_id=1, key="k3x", symbol="BTC-EUR", asset_class="crypto", side="sell",
                   size_eur=10)


def test_kill_switch_and_stale_quotes_stop_fills(env):
    eng, feed, killed = env
    buy(eng, "k4")
    killed["on"] = True
    assert eng.step() == []
    with pytest.raises(PermissionError):
        buy(eng, "k5")
    killed["on"] = False
    feed.label = "HISTORICAL"
    assert eng.step() == []                               # geen gok op een oude koers
    feed.label = "DELAYED"
    assert eng.step()[0]["status"] == "filled"


def test_reconcile_detects_tampering(env):
    eng, _, _ = env
    buy(eng, "k6")
    eng.step()
    from nexus.db import Account
    with eng.db.session.begin() as s:
        s.get(Account, eng.account_id()).cash += 5
    r = eng.reconcile()
    assert not r["ok"] and "kas" in r["differences"][0]

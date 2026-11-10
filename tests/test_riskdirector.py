import random
from datetime import UTC, date, datetime, timedelta

from jplh.config import load_config
from jplh.desks import open_desks
from jplh.notify import messages
from jplh.paper import build_demo
from jplh.riskdirector import MIN_EXPOSURE, STEP, assess, next_exposure, simulate, wanted
from jplh.store import Store

NOW = datetime(2026, 11, 9, 16, 5, tzinfo=UTC)
SHARES = {"crypto": 0.3, "meme": 0.05, "stocks": 0.35, "metals": 0.15, "fx": 0.15}


def _result(wild_from: int, n: int = 400) -> dict:
    """Nep-afdelingen: rustig, en vanaf dag ``wild_from`` gaan crypto en memes heel wild."""
    rnd = random.Random(3)
    out = {}
    for c in SHARES:
        v, curve = 100.0, []
        for k in range(n):
            sd = 0.06 if c in ("crypto", "meme") and k >= wild_from else 0.008
            v *= 1 + rnd.gauss(0.0003, sd)
            curve.append((date(2024, 1, 1) + timedelta(days=k), v))
        out[c] = {"gekozen (live)": {"curve": curve}}
    return out


def test_wanted_is_full_when_calm_and_less_when_wild_but_never_below_the_floor():
    assert wanted([0.001, -0.001] * 40) == 1.0
    wild = wanted([0.05, -0.05] * 40)
    assert MIN_EXPOSURE <= wild < 0.5
    assert wanted([0.5, -0.5] * 40) == MIN_EXPOSURE
    assert wanted([]) == 1.0                       # te weinig gegevens: niets doen


def test_small_changes_are_ignored_to_save_costs():
    assert next_exposure(1.0, 1.0 - STEP / 2) == 1.0
    assert next_exposure(1.0, 0.7) == 0.7
    assert next_exposure(0.95, 1.0) == 1.0         # terug naar volledig mag altijd


def test_director_only_reacts_after_the_storm_started_never_before():
    res = _result(wild_from=300)
    d = simulate(res, SHARES)
    stand = dict(d["stand"])
    start = min(stand)
    assert all(e == 1.0 for day, e in stand.items() if (day - start).days <= 300)   # geen blik vooruit
    assert min(stand.values()) < 1.0                                             # daarna wel minder


def test_assess_follows_the_backtest_and_only_trades_when_it_wins():
    res = _result(wild_from=300)
    r = assess(res, SHARES, None, NOW)
    assert r["wing"] == ["crypto", "meme"] and r["vol"] > 0.4
    if r["backtest"]["wins"]:
        assert r["exposure"] < 1.0
    else:
        assert r["exposure"] == 1.0
    calm = assess(_result(wild_from=10_000), SHARES, None, NOW)
    assert calm["exposure"] == 1.0 and not calm["changed"]


def test_desks_follow_the_director_only_in_the_risk_wing(tmp_path):
    home = tmp_path / "h"
    cfg = load_config(None)
    build_demo(cfg, home, hours=4, history_days=3, now=NOW)
    market = Store(home / "data" / "holding.sqlite3")
    market.set_state("risk", {"exposure": 0.5})
    desks = open_desks(cfg, home, market, use_kill_file=False)
    assert desks["crypto"].exposure() == 0.5 and desks["meme"].exposure() == 0.5
    assert desks["stocks"].exposure() == 1.0
    crypto = desks["crypto"]
    before = dict(crypto.holding.portfolio.positions)
    decisions = crypto.follow_director(NOW, 0.5)
    if before:
        assert decisions and all(d.signal.side.value == "sell" for d in decisions)
        assert all("Risicodirecteur" in d.signal.reason for d in decisions)
    assert crypto.meta["risk_exposure"] == 0.5
    assert crypto.follow_director(NOW, 0.5) == []   # zelfde stand: niets te doen


def test_jarvis_tells_when_the_director_moves():
    st = {"total": {"equity_eur": 1000, "pnl_pct": 0, "day_pnl_pct": 0}, "desks": [], "feed": [],
          "risk": {"exposure": 0.6, "vol": 0.66, "target": 0.4}}
    memory = {"briefing_day": NOW.date().isoformat(), "risk_exposure": 1.0}
    msgs = messages(st, memory, NOW)
    assert any("Risicodirecteur" in m and "60%" in m for m in msgs)
    assert not any("Risicodirecteur" in m for m in messages(st, memory, NOW))

from datetime import date, timedelta

from jplh.config import load_config
from jplh.desks import open_desks
from jplh.paper import build_demo
from jplh.store import Store
from jplh.stress import run, worst_windows
from test_riskdirector import NOW

D0 = date(2024, 1, 1)


def test_worst_window_finds_the_real_drop_and_cash_softens_it():
    a = {D0 + timedelta(days=k): 100.0 if k < 100 or k > 130 else 70.0 for k in range(300)}   # 30% eraf
    full = worst_windows({"A": 1000.0}, 0.0, {"A": a}, 30)
    assert round(full["return"], 2) == -0.30 and full["from"] < (D0 + timedelta(days=101)).isoformat()
    half = worst_windows({"A": 500.0}, 500.0, {"A": a}, 30)
    assert round(half["return"], 2) == -0.15                     # de helft cash: half zo erg
    assert worst_windows({"A": 1000.0}, 0.0, {"A": dict(list(a.items())[:40])}, 30) is None   # te kort


def test_stress_test_runs_on_the_holding_and_names_desks_that_would_pause(tmp_path):
    home = tmp_path / "h"
    cfg = load_config(None)
    build_demo(cfg, home, hours=4, history_days=3, now=NOW)
    market = Store(home / "data" / "holding.sqlite3")
    t = run(cfg, open_desks(cfg, home, market, use_kill_file=False), market, NOW)
    assert t["equity_eur"] > 0 and len(t["scenarios"]) == 4
    crash = next(s for s in t["scenarios"] if s["name"] == "Bankencrisis")
    assert crash["return"] < 0 and crash["after_eur"] < t["equity_eur"]

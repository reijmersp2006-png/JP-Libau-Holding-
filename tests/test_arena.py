from datetime import UTC, datetime, timedelta

from jplh.arena import LIVE, maybe_run_arena, run_arena
from jplh.config import load_config
from jplh.desks import open_desks
from jplh.notify import messages
from jplh.paper import build_demo
from jplh.store import Store

NOW = datetime(2026, 11, 9, 16, 5, tzinfo=UTC)


def test_arena_only_counts_days_since_the_start_and_has_the_live_rules(tmp_path):
    home = tmp_path / "h"
    cfg = load_config(None)
    build_demo(cfg, home, hours=6, history_days=12, now=NOW)
    market = Store(home / "data" / "holding.sqlite3")
    a = market.get_state("arena")
    assert a and a["desks"]["crypto"]["live_rank"] >= 1
    start = datetime.fromisoformat(a["start"]).date()
    assert (NOW.date() - start).days <= 13
    for d in a["desks"].values():
        assert sum(r["live"] for r in d["board"]) == 1
        assert all(r["days"] <= 14 for r in d["board"])          # alleen vooruit gekeken
        assert not any(r["promote"] for r in d["board"])         # te kort voor een trofee
    # 'gewoon vasthouden' is precies de live-regel bij aandelen: dan geen dubbele uitdager
    assert not any(r["variant"] == "vasthouden (maatlat)" for r in a["desks"]["stocks"]["board"])


def test_arena_runs_once_a_day(tmp_path):
    home = tmp_path / "h"
    cfg = load_config(None)
    build_demo(cfg, home, hours=6, history_days=5, now=NOW)
    market = Store(home / "data" / "holding.sqlite3")
    books = [d.holding.store for d in open_desks(cfg, home, market).values()]
    first = market.get_state("arena")
    later = maybe_run_arena(cfg, market, books, NOW + timedelta(hours=1), log=lambda *_: None)
    assert later["computed_at"] == first["computed_at"]
    fresh = run_arena(cfg, market, datetime.fromisoformat(first["start"]).date(), NOW)
    assert set(fresh["desks"]) == set(first["desks"])


def test_jarvis_announces_a_promotion_once():
    board = [{"name": "rotatie", "variant": "8 rotatie top 2 (6 mnd)", "live": False, "return": 0.2, "sharpe": 1.5,
              "days": 95, "promote": True},
             {"name": "huidige regels (live)", "variant": LIVE, "live": True, "return": 0.1, "sharpe": 1.0,
              "days": 95, "promote": False}]
    st = {"total": {"equity_eur": 1000, "pnl_pct": 0, "day_pnl_pct": 0}, "desks": [], "feed": [],
          "arena": {"desks": {"meme": {"name": "Meme Arcade", "board": board}}}}
    memory = {"briefing_day": NOW.date().isoformat()}
    msgs = messages(st, memory, NOW)
    assert any("Schaduw-arena" in m and "Meme Arcade" in m for m in msgs)
    assert not any("Schaduw-arena" in m for m in messages(st, memory, NOW))


def test_whatif_series_start_at_one_and_compare_with_holding(tmp_path):
    home = tmp_path / "h"
    build_demo(load_config(None), home, hours=6, history_days=5, now=NOW)
    w = Store(home / "data" / "holding.sqlite3").get_state("whatif")
    assert "Hele holding" in w["series"] and "Crypto Lab" in w["series"]
    for pts in w["series"].values():
        assert pts[0][1:] == [1.0, 1.0] and len(pts) >= 30
        assert [p[0] for p in pts] == sorted(p[0] for p in pts)

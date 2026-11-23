"""Master Prompt 9.0: Command Center-gegevens (jplh.overmind/v1) en de gegronde Jarvis-antwoorden."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from jplh import overmind
from jplh.commands import answer
from jplh.config import load_config
from jplh.desks import open_desks
from jplh.paper import build_demo
from jplh.site import build_overmind, build_state
from jplh.store import Store

NOW = datetime(2026, 11, 23, 15, tzinfo=UTC)
EDGE_TYPES = {"DESK_TRADES_ASSET", "ASSET_USES_STRATEGY", "DEPARTMENT_MADE_DECISION", "DECISION_CONCERNS_ASSET",
              "DECISION_USED_STRATEGY", "RISK_ASSESSMENT_CONCERNS_DEPARTMENT", "FINDING_CONCERNS_STRATEGY",
              "FINDING_CONCERNS_DEPARTMENT", "RULE_CONCERNS_DEPARTMENT", "RULE_LINKS_DEPARTMENTS",
              "CHALLENGER_COMPETES_IN_DEPARTMENT", "EVENT_AFFECTS_ASSET", "RESEARCH_REFERENCES_SOURCE",
              "RESEARCH_CONCERNS_DEPARTMENT"}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    home = tmp_path_factory.mktemp("om") / "home"
    cfg = load_config(None)
    build_demo(cfg, home, hours=30, now=NOW, history_days=12)
    market = Store(home / "data" / "holding.sqlite3")
    # geheimen die nooit publiek mogen: zoals de echte Telegram-staat
    market.set_state("telegram", {"chat": "1234567890", "seen_ts": NOW.isoformat()})
    desks = open_desks(cfg, home, market)
    # een echte risicopauze, zoals de holding hem vastlegt
    crypto = desks["crypto"].holding
    crypto.meta["paused_reason"] = "drawdown 15.6%: gepauzeerd tot jij 'jplh resume' doet"
    crypto.journal.write(NOW - timedelta(hours=2), "pause", {"reason": crypto.meta["paused_reason"]})
    crypto._save()
    state = json.loads(json.dumps(build_state(cfg, desks, market, home, NOW), default=str))
    ov = overmind.build(state, cfg, desks, market, NOW, home)
    return cfg, home, market, desks, state, ov


def test_export_is_versioned_public_safe_and_readonly(world):
    cfg, home, market, desks, state, ov = world
    text = json.dumps(ov, default=str)
    assert ov["schema"] == "jplh.overmind/v1" and ov["live_trading"] is False
    assert overmind.forbidden_keys(json.loads(text)) == set()
    assert "1234567890" not in text and str(home) not in text and "logs/" not in text


def test_paused_desk_is_critical_and_a_ceo_decision_with_replay(world):
    *_, state, ov = world
    crit = [a for a in ov["attention"] if a["level"] == "critical"]
    assert any("Crypto Lab staat stil" in a["title"] for a in crit)
    dec = next(d for d in ov["decisions"] if d["id"] == "resume:crypto")
    assert "jplh resume" in dec["how"] and dec["replay"]
    pause = next(r for r in ov["replay"] if r["id"] == dec["replay"])
    assert pause["kind"] == "pause" and "15.6%" in pause["recorded"]["reason"]
    assert {"recorded", "reconstructed", "post_event"} <= set(pause)


def test_replay_never_uses_data_from_after_the_decision(world):
    *_, ov = world
    decisions = [r for r in ov["replay"] if r["kind"] == "decision"]
    assert decisions
    for r in decisions:
        rc = r["reconstructed"]
        if rc["price_ts"]:
            assert datetime.fromisoformat(rc["price_ts"]) <= datetime.fromisoformat(r["ts"])
        assert r["recorded"]["signal_reason"] is not None or r["recorded"]["reason"]


def test_radar_scores_are_transparent_or_not_rated(world):
    *_, ov = world
    assert ov["radar"]
    for r in ov["radar"]:
        c = r["components"]
        if r["rated"]:
            assert r["score"] == round(100 * c["evidence"] * c["confirmation"] * c["freshness"])
        else:
            assert r["score"] is None and r["missing"]
        assert "koop" not in r["question"].lower() or "signaal" not in r["question"].lower()


def test_graph_only_contains_typed_edges_between_known_nodes(world):
    *_, ov = world
    g = ov["graph"]
    ids = {n["id"] for n in g["nodes"]}
    assert len(ids) == len(g["nodes"])
    for e in g["edges"]:
        assert e["type"] in EDGE_TYPES and e["source"] in ids and e["target"] in ids
        assert e["nature"] in ("observed", "recorded", "hypothesis") and e["provenance"]
        if e["type"].startswith("RULE_"):
            assert (e["nature"] == "observed") == (e.get("verdict") == "klopt")
    assert any(e["type"] == "RISK_ASSESSMENT_CONCERNS_DEPARTMENT" for e in g["edges"])
    assert g["missing"]                                  # NEXUS niet verbonden: dat staat erbij


def test_pulse_turns_stale_without_new_rounds(world):
    cfg, home, market, desks, state, ov = world
    assert next(p for p in ov["pulse"] if p["id"] == "paper_cycle")["status"] == "HEALTHY"
    assert next(p for p in ov["pulse"] if p["id"] == "nexus")["status"] == "BLOCKED"
    assert next(p for p in ov["pulse"] if p["id"] == "jarvis")["status"] == "UNKNOWN"    # geen bewijs = geen groen
    late = overmind.build(state, cfg, desks, market, NOW + timedelta(hours=8), home)
    assert next(p for p in late["pulse"] if p["id"] == "paper_cycle")["status"] == "STALE"
    assert any("verouderd" in a["title"] for a in late["attention"] if a["level"] == "critical")


def test_simulator_inputs_match_the_portfolio(world):
    *_, state, ov = world
    ex = ov["exposure"]
    assert ex["invested_eur"] == pytest.approx(sum(p["value_eur"] for d in state["desks"] for p in d["positions"]))
    assert ex["desk_paused"]["crypto"] is True
    assert {s["id"] for s in ov["scenarios"]} >= {"market", "crypto", "fx", "correlation", "single"}
    assert all(s["assumption"] for s in ov["scenarios"])


def test_jarvis_answers_are_grounded_and_change_nothing(world):
    cfg, home, market, *_ = world
    before = (home / "KILL").exists()
    att = answer("/aandacht", cfg, home, market, NOW)
    assert "Crypto Lab staat stil" in att and "jplh resume" in att and "geen AI" in att
    assert "Afgelopen 24 uur" in answer("/veranderd", cfg, home, market, NOW)
    sysm = answer("/systeem", cfg, home, market, NOW)
    assert "Handelsronde" in sysm and "BLOCKED" in sysm and "UNKNOWN" in sysm
    p = answer("/pauze crypto", cfg, home, market, NOW)
    assert "staat stil" in p and "Hervatten kan alleen jij" in p
    assert "Nu stil: Crypto Lab" in answer("/pauze", cfg, home, market, NOW)
    assert "niet stil" in answer("/pauze fx", cfg, home, market, NOW)
    helptext = answer("/help", cfg, home, market, NOW)
    assert all(c in helptext for c in ("/aandacht", "/veranderd", "/systeem", "/pauze", "/onderzoek"))
    assert (home / "KILL").exists() == before


def test_a_broken_overmind_never_stops_the_dashboard(world):
    cfg, home, market, desks, state, _ = world
    problems: list[str] = []
    assert build_overmind({"desks": []}, cfg, desks, market, home, NOW, problems) is None
    assert problems and problems[0].startswith("overmind:")


def test_demo_site_ships_command_center_city_and_export(tmp_path):
    site = build_demo(load_config(None), tmp_path / "demo", hours=6, now=NOW, history_days=10)
    for f in ("index.html", "stad.html", "factsheet.html", "jarvis.html", "state.json", "snapshot.json", "overmind.json"):
        assert (site / f).exists(), f
    index = (site / "index.html").read_text()
    assert "JP-Libau Holding" in index and "Command Center" in index and 'href="stad.html"' in index
    assert "fetch(" in index and "method: \"POST\"" not in index and "method:'POST'" not in index   # geen schrijfacties
    assert 'href="index.html"' in (site / "stad.html").read_text()
    om = json.loads((site / "overmind.json").read_text())
    assert om["schema"] == "jplh.overmind/v1"


def test_no_duplicate_radar_items_or_edges(world):
    *_, ov = world
    ids = [r["id"] for r in ov["radar"]]
    assert len(ids) == len(set(ids))
    keys = [(e["type"], e["source"], e["target"]) for e in ov["graph"]["edges"]]
    assert len(keys) == len(set(keys))

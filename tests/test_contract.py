"""Master Prompt 8.0: het read-only contract tussen de holding en NEXUS/Jarvis."""

import json
from datetime import UTC, datetime, timedelta

from jplh.commands import answer, intelligence_text
from jplh.config import load_config
from jplh.contract import (RECORDS_SCHEMA, SNAPSHOT_SCHEMA, digest, operational_snapshot,
                           validate_records, validate_snapshot)
from jplh.paper import build_demo
from jplh.store import Store

NOW = datetime(2026, 11, 23, 15, tzinfo=UTC)


def _site(tmp_path):
    return build_demo(load_config(None), tmp_path / "demo", hours=6, now=NOW, history_days=10)


def test_dashboard_publishes_a_valid_snapshot_next_to_the_unchanged_state(tmp_path):
    site = _site(tmp_path)
    state = json.loads((site / "state.json").read_text())
    snap = json.loads((site / "snapshot.json").read_text())
    assert validate_snapshot(snap) == []
    assert snap["schema"] == SNAPSHOT_SCHEMA and snap["live_trading"] is False
    assert snap["source"]["demo"] is True and snap["source"]["authoritative"] is True
    # dezelfde getallen als het dashboard: de holding blijft de enige bron
    assert snap["holding"]["equity_eur"] == state["total"]["equity_eur"]
    assert [d["id"] for d in snap["desks"]] == [d["id"] for d in state["desks"]]
    assert snap["freshness"]["last_round_at"] == state["total"]["equity_curve"][-1][0]
    assert "snapshot" not in state                      # state.json zelf is niet veranderd


def test_snapshot_keeps_pauses_benchmark_and_costs(tmp_path):
    site = _site(tmp_path)
    state = json.loads((site / "state.json").read_text())
    state["desks"][0]["paused_reason"] = "drawdown 15.6%: gepauzeerd tot jij 'jplh resume' doet"
    snap = operational_snapshot(state, NOW)
    d = snap["desks"][0]
    assert d["paused"] is True and "jplh resume" in d["paused_reason"]
    assert d["benchmark_pct"] == state["desks"][0]["benchmark_eur"] / state["desks"][0]["capital_eur"] - 1
    assert "fees_eur" in d and "trades" in d


def test_tampering_unknown_versions_and_secrets_are_rejected(tmp_path):
    snap = json.loads((_site(tmp_path) / "snapshot.json").read_text())
    changed = {**snap, "holding": {**snap["holding"], "equity_eur": 99999.0}}
    assert any("sha256" in e for e in validate_snapshot(changed))
    assert validate_snapshot({**snap, "schema": "jplh.snapshot/v2"})[0].startswith("onbekend schema")
    leaky = {**snap, "source": {**snap["source"], "telegram_token": "x"}}
    leaky["sha256"] = digest(leaky)
    assert any("verboden" in e for e in validate_snapshot(leaky))
    live = {**snap, "live_trading": True}
    live["sha256"] = digest(live)
    assert "live_trading moet false zijn" in validate_snapshot(live)


def test_jarvis_onderzoek_is_honest_without_nexus_and_reads_valid_records(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    assert "NIET VERBONDEN" in intelligence_text(home, NOW)
    (home / "intelligence").mkdir()
    rec = {"trace_id": "ops-1", "subject": "holding", "created_at": NOW.isoformat(), "status": "done",
           "generator": "deterministic:ops-v1", "snapshot_sha256": "ab" * 32, "summary": "Crypto Lab is gepauzeerd.",
           "ai_status": "NOT CONNECTED"}
    (home / "intelligence" / "records.json").write_text(json.dumps(
        {"schema": RECORDS_SCHEMA, "exported_at": NOW.isoformat(), "items": [rec]}))
    text = intelligence_text(home, NOW + timedelta(hours=1))
    assert "vaste code" in text and "Crypto Lab is gepauzeerd." in text and "NOT CONNECTED" in text
    assert "Verouderd" in intelligence_text(home, NOW + timedelta(days=3))
    (home / "intelligence" / "records.json").write_text(json.dumps({"schema": "iets/v9", "items": []}))
    assert "afgekeurd" in intelligence_text(home, NOW)
    assert validate_records({"schema": RECORDS_SCHEMA, "items": [{"trace_id": "x"}]})


def test_onderzoek_command_routes_without_touching_trading(tmp_path):
    home = tmp_path / "h"
    build_demo(load_config(None), home, hours=3, history_days=2, now=NOW)
    market = Store(home / "data" / "holding.sqlite3")
    try:
        assert "NEXUS" in answer("/onderzoek", load_config(None), home, market, NOW)
        assert "/onderzoek" in answer("/help", load_config(None), home, market, NOW)
    finally:
        market.close()
    assert not (home / "KILL").exists()

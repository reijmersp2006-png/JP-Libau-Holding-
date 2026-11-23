"""Master Prompt 8.0: echte, alleen-lezen datastroom holding → NEXUS-onderzoeksrecord → API/Jarvis."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jplh.contract import RECORDS_SCHEMA, validate_records

from nexus import operations
from nexus.app import create_app
from nexus.db import Database
from nexus.ops_cli import main as ops_cli
from nexus.settings import Settings


def _fingerprint(home: Path) -> dict:
    return {str(p.relative_to(home)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(home.rglob("*")) if p.is_file() and "logs" not in p.parts}


@pytest.fixture
def db():
    return Database("sqlite:///:memory:")


def test_snapshot_is_built_read_only_and_leaves_the_holding_untouched(demo_home):
    before = _fingerprint(demo_home)
    snap = operations.load(home=demo_home)
    assert snap["schema"] == "jplh.snapshot/v1" and snap["_origin"] == "holding-db (alleen-lezen)"
    assert snap["source"]["demo"] is True                    # nep-koersen worden herkend en gelabeld
    assert _fingerprint(demo_home) == before
    assert not (demo_home / "KILL").exists()


def test_read_only_store_refuses_writes(demo_home):
    store = operations._ReadOnlyStore(demo_home / "data" / "holding.sqlite3")
    try:
        with pytest.raises(Exception, match="readonly"):
            store.db.execute("DELETE FROM candles")
    finally:
        store.close()


def test_research_record_from_snapshot_is_stored_auditable_and_retrievable(db, demo_home):
    snap = operations.load(home=demo_home)
    rec = operations.run(db, snap, scope="holding", requested_by="test")
    assert rec["generator"] == "deterministic:ops-v1" and rec["data_label"] == "SIMULATED"
    assert rec["ai_status"] in ("NOT CONNECTED", "NOT ENABLED")          # nooit een verzonnen AI-antwoord
    ai = next(s for s in rec["steps"] if s["step"] == "ai_analysis")
    assert ai["status"] == "blocked"
    assert rec["snapshot_sha256"] == snap["sha256"]
    ids = {f["id"] for f in rec["facts"]}
    assert all(set(f["evidence"]) <= ids for f in rec["findings"])        # elke bewering wijst naar een feit
    assert all(f["source"].startswith("jplh.snapshot/v1") and f["ts"] for f in rec["facts"])
    assert operations.get(db, rec["trace_id"])["summary"] == rec["summary"]
    assert db.verify_audit_chain()["ok"]
    assert any(a["action"] == "ops.research" for a in db.audit_entries())
    exp = operations.export(db)
    assert exp["schema"] == RECORDS_SCHEMA and validate_records(exp) == []
    assert "facts" not in exp["items"][0]


def test_paused_desk_is_escalated_never_resumed(db, demo_home):
    snap = operations.load(home=demo_home)
    snap["desks"][0]["paused"], snap["desks"][0]["paused_reason"] = True, "drawdown 15.6%"
    rec = operations.run(db, snap, scope=snap["desks"][0]["id"])
    assert rec["recommendation"] == "escalate_to_ceo"
    assert any(f["kind"] == "risk" and "CEO-besluit" in f["text"] for f in rec["findings"])
    assert rec["subject"] == f"desk:{snap['desks'][0]['id']}"


def test_stale_data_is_labeled_and_lowers_the_status(db, demo_home):
    snap = operations.load(home=demo_home)
    snap["source"] = {**snap["source"], "demo": False}
    late = datetime.fromisoformat(snap["freshness"]["last_round_at"]).replace(tzinfo=UTC).replace(year=2030)
    rec = operations.run(db, snap, max_age_hours=3, now=late)
    assert rec["data_label"] == "STALE" and rec["status"] == "partial"
    assert rec["recommendation"] == "further_research"


def test_tampered_or_unknown_snapshot_blocks_research(tmp_path, demo_home):
    snap = operations.load(home=demo_home)
    snap.pop("_origin")
    snap["holding"]["equity_eur"] = 1e9
    f = tmp_path / "snapshot.json"
    f.write_text(json.dumps(snap))
    with pytest.raises(operations.SnapshotError, match="sha256"):
        operations.load(path=f)
    with pytest.raises(operations.SnapshotError):
        operations.load()


def test_api_reads_snapshot_and_requires_a_token_to_create_research(demo_home, monkeypatch):
    monkeypatch.delenv("NEXUS_HOLDING_SNAPSHOT", raising=False)
    s = Settings(holding_home=demo_home, database_url="sqlite:///:memory:", admin_token="geheim-token-123",
                 cache_seconds=0, worker=False)
    c = TestClient(create_app(s))
    snap = c.get("/api/ops/snapshot").json()
    assert snap["snapshot"]["schema"] == "jplh.snapshot/v1" and snap["freshness"]["label"] == "SIMULATED"
    assert c.post("/api/ops/research", json={"scope": "holding"}).status_code == 401
    assert c.post("/api/ops/research", json={"scope": "nope"},
                  headers={"Authorization": "Bearer geheim-token-123"}).status_code == 422
    r = c.post("/api/ops/research", json={"scope": "crypto"}, headers={"Authorization": "Bearer geheim-token-123"})
    assert r.status_code == 200, r.text
    trace = r.json()["trace_id"]
    assert c.get(f"/api/ops/research/{trace}").json()["trace_id"] == trace
    assert c.get("/api/ops/research").json()["items"][0]["trace_id"] == trace
    assert c.get("/api/ops/export").json()["schema"] == RECORDS_SCHEMA
    assert c.get("/api/ops/research/ops-bestaat-niet").status_code == 404
    assert c.get("/api/controls").json()["mode"] != "live"
    assert not (demo_home / "KILL").exists()


def test_api_without_a_source_says_not_connected(monkeypatch):
    monkeypatch.delenv("NEXUS_HOLDING_SNAPSHOT", raising=False)
    c = TestClient(create_app(Settings(database_url="sqlite:///:memory:", cache_seconds=0, worker=False)))
    r = c.get("/api/ops/snapshot")
    assert r.status_code == 503 and "NOT CONNECTED" in r.json()["detail"]


def test_cli_full_flow_exports_records_for_jarvis(tmp_path, demo_home):
    out = tmp_path / "records.json"
    url = f"sqlite:///{tmp_path / 'nexus.db'}"
    assert ops_cli(["--db", url, "research", "--home", str(demo_home), "--scope", "holding", "--export", str(out)]) == 0
    data = json.loads(out.read_text())
    assert validate_records(data) == [] and data["items"][0]["generator"] == "deterministic:ops-v1"
    from jplh.commands import intelligence_text
    home = tmp_path / "jarvis-home"
    (home / "intelligence").mkdir(parents=True)
    (home / "intelligence" / "records.json").write_text(out.read_text())
    assert "vaste code" in intelligence_text(home, datetime.now(tz=UTC))
    assert ops_cli(["--db", url, "show", data["items"][0]["trace_id"]]) == 0


def test_scope_limits_facts_and_findings_to_that_desk(db, demo_home):
    snap = operations.load(home=demo_home)
    desk = snap["desks"][0]["id"]
    other = {i["symbol"] for d in snap["desks"][1:] for i in d["instruments"]}
    snap["freshness"] = {**snap["freshness"], "stale_instruments": sorted(other)}
    rec = operations.run(db, snap, scope=desk)
    assert not any(f["id"].startswith("F-desk-") and f["id"] != f"F-desk-{desk}" for f in rec["facts"])
    assert not any(f["kind"] == "data" and "Niet-verse" in f["text"] for f in rec["findings"])

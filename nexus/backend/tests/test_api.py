from fastapi.testclient import TestClient

from conftest import proposal
from nexus.app import create_app
from nexus.settings import Settings

AUTH = {"Authorization": "Bearer geheim-token-123"}


def test_app_starts_and_reports_live_off(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["live_trading"] is False and h["environment"] == "demo"


def test_command_center_is_labeled_and_reconciles(client):
    d = client.get("/api/command-center").json()
    assert d["available"] and d["environment"] == "demo"
    p = d["portfolio"]
    assert p["label"] == "SIMULATED"
    # P&L sluit: gerealiseerd + ongerealiseerd - aankoopkosten = totaal.
    assert abs(p["realized_eur"] + p["unrealized_eur"] - p["buy_fees_eur"] - p["pnl_eur"]) < 0.01
    # Vermogen sluit: cash + posities = totaal.
    pos = sum(x["value_eur"] for x in d["positions"])
    assert abs(p["cash_eur"] + pos - p["equity_eur"]) < 0.01
    assert abs(sum(a["value_eur"] for a in d["allocation"]) - p["equity_eur"]) < 0.01
    # In de demo is alles SIMULATED, nergens LIVE.
    labels = {q["label"] for q in d["market"]} | {x["price_label"] for x in d["positions"]}
    assert labels <= {"SIMULATED"}
    assert d["controls"]["live_enabled"] is False and d["controls"]["mode"] == "paper"


def test_unconfigured_shows_honest_empty_state(tmp_path):
    c = TestClient(create_app(Settings(holding_home=tmp_path / "bestaat-niet", database_url="sqlite:///:memory:")))
    d = c.get("/api/command-center").json()
    assert d["available"] is False and d["portfolio"] is None and d["market"] == []
    assert any(x["label"] == "UNAVAILABLE" for x in d["connections"])


def test_broken_source_does_not_crash(client):
    def boom():
        raise RuntimeError("database weg")
    client.app.state.bridge.snapshot = boom
    d = client.get("/api/command-center")
    assert d.status_code == 200 and d.json()["available"] is False


def test_live_mode_is_refused_and_audited(client):
    r = client.post("/api/controls/mode", json={"mode": "live"}, headers=AUTH)
    assert r.status_code == 403
    assert any(not g["passed"] for g in r.json()["detail"]["gate"])
    assert client.get("/api/controls").json()["mode"] == "paper"
    assert client.get("/api/audit").json()[0]["action"] == "mode_change_refused"


def test_mode_change_needs_token(client):
    assert client.post("/api/controls/mode", json={"mode": "research"}).status_code == 401
    assert client.post("/api/controls/mode", json={"mode": "research"}, headers=AUTH).json()["mode"] == "research"


def test_kill_switch_blocks_proposals_and_needs_token_to_release(client, demo_home):
    r = client.post("/api/controls/kill", json={"reason": "test"})
    assert r.json()["engaged"] and (demo_home / "KILL").exists()     # ook de holding-bot stopt
    v = client.post("/api/proposals", json=proposal(idempotency_key="kill-test-0001")).json()
    assert v["approved"] is False and "noodstop" in v["reason"]
    assert client.post("/api/controls/kill/release", json={"reason": "x"}).status_code == 401
    r = client.post("/api/controls/kill/release", json={"reason": "getest"}, headers=AUTH)
    assert r.json()["engaged"] is False and not (demo_home / "KILL").exists()


def test_release_disabled_without_configured_token(demo_settings):
    from dataclasses import replace
    c = TestClient(create_app(replace(demo_settings, admin_token=None)))
    assert c.post("/api/controls/kill/release", json={"reason": "x"}).status_code == 503


def test_proposals_are_idempotent_recorded_and_never_executed(client):
    first = client.post("/api/proposals", json=proposal(idempotency_key="idem-0001-xyz")).json()
    again = client.post("/api/proposals", json=proposal(idempotency_key="idem-0001-xyz")).json()
    assert again == {"id": first["id"], "duplicate": True, "status": again["status"]}
    assert first["executed"] is False
    rows = client.get("/api/proposals").json()
    assert len([r for r in rows if r["id"] == first["id"]]) == 1
    assert rows[0]["verdict"]["checks"]


def test_invalid_proposal_rejected(client):
    assert client.post("/api/proposals", json=proposal(stop_loss=None)).status_code == 422

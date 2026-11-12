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


def test_proposal_to_paper_execution_flow(client):
    p = proposal(idempotency_key="flow-0001-abc", symbol="BTC-EUR", asset_class="crypto", entry_price=60000.0,
                 stop_loss=57000.0, size_eur=50.0, max_modeled_loss_eur=3.0, input_data_label="SIMULATED")
    v = client.post("/api/proposals", json=p).json()
    assert v["approved"], v["reason"]
    r = client.post(f"/api/proposals/{v['id']}/execute").json()
    assert r["fills"] and r["fills"][0]["side"] == "buy"
    again = client.post(f"/api/proposals/{v['id']}/execute").json()
    assert again["duplicate"] is True                       # geen dubbele order
    paper = client.get("/api/paper").json()
    assert paper["reconciliation"]["ok"] and paper["account"]["label"] == "SIMULATED"
    assert paper["live_enabled"] is False and len(paper["executions"]) == 1


def test_vetoed_proposal_cannot_execute(client):
    v = client.post("/api/proposals", json=proposal(idempotency_key="veto-0001-abc", spread_pct=0.03)).json()
    assert not v["approved"]
    assert client.post(f"/api/proposals/{v['id']}/execute").status_code == 409


def test_execute_only_in_paper_mode(client):
    v = client.post("/api/proposals", json=proposal(idempotency_key="mode-0001-abc", symbol="BTC-EUR",
                    asset_class="crypto", entry_price=60000.0, stop_loss=57000.0, size_eur=50.0,
                    max_modeled_loss_eur=3.0, input_data_label="SIMULATED")).json()
    client.post("/api/controls/mode", json={"mode": "research"}, headers=AUTH)
    assert client.post(f"/api/proposals/{v['id']}/execute").status_code == 409


def test_backtest_endpoint_runs_and_persists(client):
    r = client.post("/api/backtests", json={"strategy": "trend_sma", "symbol": "BTC-EUR"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["data_label"] == "SIMULATED" and "out_of_sample" in d
    runs = client.get("/api/strategies").json()["runs"]
    assert runs[0]["id"] == d["id"]
    assert client.get(f"/api/backtests/{d['id']}").json()["symbol"] == "BTC-EUR"
    assert client.post("/api/backtests", json={"strategy": "bestaat_niet", "symbol": "BTC-EUR"}).status_code == 404


def test_admin_overview_is_honest(client):
    a = client.get("/api/admin/overview").json()
    assert a["mrr_eur"] is None and a["billing_connected"] is False and a["customer_features_enabled"] is False
    assert [p["price_eur"] for p in a["plans"]] == [19.0, 59.0, 149.0]
    assert all(not g["done"] for g in a["legal_gate"])


def test_websocket_says_hello(client):
    with client.websocket_connect("/ws/events") as ws:
        msg = ws.receive_json()
    assert msg["kind"] == "hello" and msg["data"]["mode"] == "paper"


def test_market_providers_listed(client):
    names = {p["name"]: p["status"] for p in client.get("/api/market/providers").json()}
    assert names["bitvavo"] == "connected" and names["polygon"] == "not_configured"

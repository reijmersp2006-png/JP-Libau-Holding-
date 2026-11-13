"""Milestone D: workstation-, pulse- en agentgegevens komen alleen uit opgeslagen data."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from nexus import workflow, workstation
from nexus.db import Database, NewsEvent

NOW = datetime(2026, 11, 13, 12, tzinfo=UTC)


class FakeData:
    def __init__(self, series: dict):
        self.series = series
        self.config = SimpleNamespace(instruments=[], shadow=[])
        self.holding_db = self.research_db = None

    def raw(self, symbol, interval):
        return self.series.get((symbol, interval), [])


def _candles(n, start=100.0, step=1.0, days=True, end=NOW - timedelta(days=1)):
    d = timedelta(days=1) if days else timedelta(hours=1)
    return [SimpleNamespace(ts=end - d * (n - 1 - i), open=start + i * step, high=start + i * step + 1,
                            low=start + i * step - 1, close=start + i * step, volume=10 + i) for i in range(n)]


@pytest.fixture
def data(monkeypatch):
    fd = FakeData({("BTC-EUR", "1d"): _candles(400), ("ETH-EUR", "1d"): _candles(400, 50, -0.05),
                   ("^VIX", "1d"): _candles(100, 15, 0.01)})
    monkeypatch.setattr(workstation, "stored_symbols", lambda d: ["BTC-EUR", "ETH-EUR", "^VIX"])
    return fd


def test_indicators_have_no_lookahead_and_correct_warmup():
    xs = [float(i) for i in range(1, 31)]
    s = workstation.sma(xs, 20)
    assert s[18] is None and s[19] == pytest.approx(10.5) and s[-1] == pytest.approx(20.5)
    r = workstation.rsi(xs, 14)
    assert r[13] is None and r[-1] == 100.0
    assert workstation.max_drawdown([100, 120, 90, 130]) == pytest.approx(-0.25)


def test_asset_only_offers_stored_intervals_and_labels_freshness(data):
    db = Database("sqlite:///:memory:")
    a = workstation.asset(db, data, "BTC-EUR", "1d", 300, now=NOW)
    assert a["intervals"] == ["1d"] and a["label"] == "DELAYED" and len(a["candles"]) == 300
    assert len(a["indicators"]["sma200"]) == 300 and a["stats"]["ret"]["1d"] > 0
    assert "orderboek en spread" in a["quality"]["unavailable"]
    old = workstation.asset(db, data, "BTC-EUR", "1d", now=NOW + timedelta(days=30))
    assert old["label"] == "HISTORICAL"
    with pytest.raises(KeyError):
        workstation.asset(db, data, "NOPE", "1d")
    with pytest.raises(ValueError):
        workstation.asset(db, data, "BTC-EUR", "5m")


def test_asset_links_news_and_labels_fixtures(data):
    db = Database("sqlite:///:memory:")
    with db.session.begin() as s:
        s.add(NewsEvent(source="fixture", source_kind="fixture", url="https://example.invalid/x", title="[FIXTURE] x",
                        published_at=NOW, fetched_at=NOW, category="other", assets=["BTC-EUR"], factuality="fact",
                        content_hash="h", relevance=0.9, facts=[]))
    a = workstation.asset(db, data, "BTC-EUR", now=NOW)
    assert a["news"][0]["simulated"] is True and a["events"][0]["simulated"] is True


def test_overview_classes_correlation_and_regime(data):
    o = workstation.overview(data, now=NOW)
    assert {c["asset_class"] for c in o["classes"]} == {"crypto", "context"}
    assert o["correlation"]["symbols"] and o["correlation"]["days"] == 60
    assert o["vix"] is not None and "VIX" in o["regime"]["summary"]


def test_agent_dossier_and_handoffs_come_from_real_traces(data):
    db = Database("sqlite:///:memory:")
    with db.session.begin() as s:
        e = NewsEvent(source="fed", source_kind="official", url="https://x", title="Fed holds", published_at=NOW,
                      fetched_at=NOW, category="rate_decision", assets=["BTC-EUR"], factuality="fact",
                      content_hash="h2", relevance=0.9, facts=[])
        s.add(e)
        s.flush()
        nid = e.id
    assert workstation.handoffs(db)["edges"] == []
    workflow.run(db, {}, nid, now=NOW)
    h = workstation.handoffs(db)
    assert any(e["from"] == "quant" and e["to"] == "risk" and e["n"] == 1 for e in h["edges"])
    assert all(e["from"] != "crypto" for e in h["edges"])          # overgeslagen AI-stap is geen overdracht
    d = workstation.agent(db, "news")
    assert d["workflow_steps"] and d["cost_usd"] == 0
    with pytest.raises(KeyError):
        workstation.agent(db, "onbekend")


def test_apex_api_is_read_only(client):
    assert client.get("/api/hq/handoffs").status_code == 200
    assert client.get("/api/hq/agents/risk").status_code == 200
    assert client.get("/api/hq/agents/nope").status_code == 404
    assert client.get("/api/workstation/universe").status_code == 200
    assert client.post("/api/workstation/universe").status_code == 405


def test_copilot_routes_the_founder_questions():
    from nexus import copilot
    cases = {
        "What are the AI agents researching?": "agents", "Wat onderzoeken de AI-agenten?": "agents",
        "Which events require my attention?": "approvals", "Welke gebeurtenissen vragen mijn aandacht?": "approvals",
        "Why was this trade rejected?": "rejection", "What are our largest risks?": "risk",
        "Which strategies performed best?": "opportunities", "Which providers are offline?": "providers",
        "What have we learned this week?": "learning", "Welk nieuws vraagt aandacht?": "news",
    }
    for q, topic in cases.items():
        assert copilot.route(q) == topic, q


def test_demo_labels_are_simulated_never_delayed():
    from nexus.apex_api import _simulated
    out = _simulated({"label": "DELAYED", "items": [{"label": "HISTORICAL"}, {"label": "UNAVAILABLE"}]})
    assert out == {"label": "SIMULATED", "items": [{"label": "SIMULATED"}, {"label": "UNAVAILABLE"}]}

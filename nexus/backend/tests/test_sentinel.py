"""Sentinel (4.0): NEXUS Central, News Reactor, Social/on-chain, Copilot en de API. Geen netwerk, geen echte AI."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from conftest import proposal
from nexus import central, copilot, news, social
from nexus.db import Database, ModelVersion, NewsEvent, OrchestratorTask
from test_evolution_lab import RSS, FakeClient
from test_lab import series

AUTH = {"Authorization": "Bearer geheim-token-123"}
NOW = datetime(2025, 11, 6, 13, tzinfo=UTC)


@pytest.fixture
def db():
    return Database("sqlite:///:memory:")


# ── NEXUS Central ───────────────────────────────────────────────────────────────────────────
def test_state_machine_refuses_illegal_transitions(db):
    tid = central.enqueue(db, "news_review", "news", "test", source_ref="news:1", payload={"news_id": 1})
    with db.session.begin() as s:
        t = s.get(OrchestratorTask, tid)
        with pytest.raises(central.InvalidTransition):
            central.move(t, "done")                          # eerst running
        central.move(t, "running")
        central.move(t, "done", "ok")
        with pytest.raises(central.InvalidTransition):
            central.move(t, "running")                       # afgerond blijft afgerond
        assert [h["to"] for h in t.history] == ["queued", "running", "done"]
    assert central.enqueue(db, "news_review", "news", "dubbel", source_ref="news:1") is None


def test_plan_turns_real_events_into_tasks_and_escalates_human_decisions(db):
    news.ingest(db, [news.FEEDS[0]], lambda f: RSS, NOW)
    with db.session.begin() as s:
        s.add(ModelVersion(key="vol_target", version=1, symbols=["IWDA.AS"], interval="1d", params={},
                           status="candidate"))
    made = central.plan(db, {}, now=NOW)
    ts = central.tasks(db)
    kinds = {t["kind"]: t for t in ts}
    assert "news_review" in kinds and kinds["approval"]["status"] == "escalated" and kinds["approval"]["agent"] == "ceo"
    assert central.plan(db, {}, now=NOW) == [] and len(made) == len(ts)    # geen dubbele taken
    ran = central.run(db, {})
    assert all(r["status"] == "done" for r in ran)
    with db.session() as s:
        assert s.scalars(select(NewsEvent).where(NewsEvent.signal_at.is_not(None))).first() is not None
    # De mens promoveert of wijst af buiten Central: de escalatie sluit vanzelf.
    with db.session.begin() as s:
        s.scalars(select(ModelVersion)).first().status = "rejected"
    assert central.resolve_approvals(db) == 1


def test_council_review_is_budgeted_and_capped(db, monkeypatch, tmp_path):
    from jplh.config import load_config

    from nexus import datasets
    monkeypatch.setenv("NEXUS_AI_DAILY_BUDGET_USD", "100")
    data = datasets.ResearchData(load_config(), None, tmp_path / "r.sqlite3")
    data.save("IWDA.AS", "1d", series(300), "synthetic-test")
    for k in range(5):
        with db.session.begin() as s:
            s.add(NewsEvent(source="fed", source_kind="official", url=f"u{k}", title=f"FOMC statement number {k} alpha{k}",
                            published_at=NOW, category="rate_decision", assets=["IWDA.AS"], factuality="fact",
                            content_hash=f"h{k}", relevance=0.9))
    ctx = {"council_symbols": ("IWDA.AS",), "data": data, "council_client": FakeClient()}
    central.plan(db, ctx, now=NOW)
    reviews = [t for t in central.tasks(db) if t["kind"] == "council_review"]
    assert len(reviews) == central.MAX_AI_TASKS_PER_DAY
    out = central.run(db, ctx)
    done = [r for r in out if r["kind"] == "council_review"]
    assert done and all(r["status"] == "done" for r in done)
    t = next(t for t in central.tasks(db) if t["kind"] == "council_review" and t["status"] == "done")
    assert t["result"]["status"] == "done" and t["cost_usd"] > 0


def test_briefing_names_missing_data(db):
    b = central.briefing(db, {}, now=NOW)
    assert b["trading"]["live_trading"] is False
    assert any("paper" in m for m in b["missing"]) and any("nieuws" in m for m in b["missing"])
    assert central.latest_briefing(db)["day"] == "2025-11-06"


def test_organization_has_every_department_and_no_invented_activity(db):
    org = central.organization(db)
    assert {r["department"] for r in org} == set(central.DEPARTMENTS)
    assert all(r["last_activity"] is None for r in org)              # lege database: geen activiteit


# ── News Reactor ────────────────────────────────────────────────────────────────────────────
def test_reactor_clusters_related_reports_and_extracts_facts(db):
    other = RSS.replace("Federal Reserve issues FOMC statement", "FOMC statement issued by Federal Reserve") \
               .replace("https://x/1", "https://y/1")
    news.ingest(db, [news.FEEDS[0]], lambda f: RSS, NOW)
    news.ingest(db, [news.FEEDS[1]], lambda f: other, NOW)
    with db.session() as s:
        fomc = s.scalars(select(NewsEvent).where(NewsEvent.title.like("%FOMC%"))).all()
    assert len(fomc) == 2 and fomc[1].duplicate_of == fomc[0].id and fomc[0].cluster_key == fomc[1].cluster_key
    assert fomc[0].facts and "decided" in fomc[0].facts[-1]["claim"]
    assert fomc[0].relevance >= news.SIGNAL_THRESHOLD
    lat = news.latency(db)
    assert lat["publication_to_ingest"]["n"] == 4 and lat["ingest_to_analysis"]["median_s"] >= 0


def test_speculative_sentences_are_not_facts():
    f = news.extract_facts("Fed may cut rates", "Officials could act. The Committee decided to maintain the rate at 4.25%.")
    assert [x["claim"] for x in f] == ["The Committee decided to maintain the rate at 4.25%"]
    assert f[0]["numbers"]


# ── Social en on-chain ─────────────────────────────────────────────────────────────────────
def _posts(n, dup=0, t0=NOW - timedelta(hours=2)):
    out = []
    for k in range(n):
        txt = "PEPE to the moon $PEPE https://t.co/x" if k < dup else f"thinking about $PEPE liquidity note {k}"
        out.append({"id": str(k), "text": txt, "created_at": (t0 + timedelta(minutes=k)).isoformat(),
                    "author_id": f"a{k % 7}", "public_metrics": {"like_count": 2, "retweet_count": 1}})
    return out


def test_x_without_token_is_not_connected(monkeypatch):
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    assert social.x_status()["connected"] is False
    with pytest.raises(social.SourceUnavailable):
        social.x_search("$PEPE", getter=lambda *a: pytest.fail("geen aanroep zonder token"))


def test_x_search_uses_official_endpoint_and_momentum_flags_coordination(monkeypatch, db):
    monkeypatch.setenv("X_BEARER_TOKEN", "tok")
    seen = {}

    def getter(url, headers=None):
        seen["url"], seen["auth"] = url, headers["Authorization"]
        users = [{"id": f"a{k}", "created_at": (NOW - timedelta(days=5 if k < 4 else 900)).isoformat(),
                  "public_metrics": {"followers_count": 10 if k < 4 else 5000}} for k in range(7)]
        return {"data": _posts(40, dup=20), "includes": {"users": users}}
    d = social.x_search("$PEPE", getter=getter)
    assert seen["url"].startswith("https://api.x.com/2/tweets/search/recent") and seen["auth"] == "Bearer tok"
    m = social.momentum(d["posts"], d["users"], NOW)
    assert m["mentions"] == 40 and m["unique_authors"] == 7 and m["duplicate_text_share"] == 0.5
    assert m["new_account_share"] == pytest.approx(4 / 7) and m["bot_risk"] > 0.4
    b = social.with_baseline(db, "$PEPE", m)
    assert b["baseline"]["available"] is False                        # nog geen geschiedenis


GOOD = {"is_honeypot": "0", "sell_tax": "0", "is_open_source": "1", "transfer_pausable": "0", "hidden_owner": "0",
        "can_take_back_ownership": "0", "holders": [{"address": "0xlp", "percent": "0.4"}, {"address": "0xa", "percent": "0.1"}],
        "lp_holders": [{"address": "0xLP"}]}
DEX = {"pairs": [{"dexId": "uniswap", "priceUsd": "0.00001", "liquidity": {"usd": 30_000_000},
                  "volume": {"h24": 5_000_000}, "pairCreatedAt": int((NOW - timedelta(days=500)).timestamp() * 1000)}]}


def test_token_safety_passes_only_when_every_mandatory_check_passes():
    st, checks, market = social.assess(GOOD, DEX, NOW)
    assert st == "pass" and market["max_order_1pct_impact_usd"] == pytest.approx(150_000)
    st, checks, _ = social.assess({**GOOD, "is_honeypot": "1"}, DEX, NOW)
    assert st == "fail" and next(c for c in checks if c["key"] == "honeypot")["status"] == "fail"
    st, _, _ = social.assess(None, DEX, NOW)
    assert st == "unavailable"                                        # geen data = geen goedkeuring


def test_meme_buy_is_vetoed_without_passing_safety_check(client):
    r = client.post("/api/proposals", json=proposal(idempotency_key="meme-0001-abcdef", symbol="PEPE-EUR",
                                                     asset_class="meme", size_eur=5.0, max_modeled_loss_eur=0.5))
    body = r.json()
    assert body["approved"] is False
    assert any(c["rule"] == "token_safety" and not c["passed"] for c in body["checks"])


def test_check_token_records_unavailable_sources(db):
    def boom(url, headers=None):
        raise social.SourceUnavailable("403 van de proxy")
    tok = social.WATCHLIST[2]
    r = social.check_token(db, tok, getter=boom, now=NOW)
    assert r["status"] == "unavailable" and {s["status"] for s in r["sources"]} == {"unavailable"}
    assert social.tradeable(db, tok.symbol)[0] is False


def test_lead_lag_classifies_social_that_precedes_price():
    import random
    rnd = random.Random(1)
    soc = [rnd.gauss(0, 1) for _ in range(200)]
    ret = [0.0, 0.0] + [0.8 * soc[k - 2] + rnd.gauss(0, 0.3) for k in range(2, 200)]
    r = social.lead_lag(soc, ret)
    assert r["classification"] == "predictive" and r["best"]["lag"] == 2
    assert social.lead_lag(soc[:10], ret[:10])["available"] is False


def test_influencer_reliability_needs_enough_statements():
    c = series(200)
    st = [{"account": "@a", "symbol": "DOGE-EUR", "ts": c[k].ts, "direction": 1} for k in range(0, 150, 10)]
    rows = social.influencer_scores(st, {"DOGE-EUR": c})
    assert rows[0]["n"] == 15 and rows[0]["reliable"] and 0 <= rows[0]["hit_rate"] <= 1


def fresh_rss():
    from email.utils import format_datetime
    d = format_datetime(datetime.now(tz=UTC) - timedelta(hours=1), usegmt=True)
    return (RSS.replace("Wed, 05 Nov 2025 19:00:00 GMT", d).replace("Thu, 06 Nov 2025 12:00:00 GMT", d))


# ── Copilot ─────────────────────────────────────────────────────────────────────────────────
def test_copilot_routes_and_cites_real_records(db, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert copilot.route("Why did we reject Bitcoin?") == "rejection"
    assert copilot.route("Which experiments are awaiting approval?") == "approvals"
    news.ingest(db, [news.FEEDS[0]], lambda f: fresh_rss(), datetime.now(tz=UTC))
    r = copilot.ask(db, "Welk nieuws vraagt aandacht?")
    assert r["mode"] == "deterministic" and r["can_execute"] is False
    assert all(ref.startswith("news:") for ref in r["refs"]) and r["evidence"]
    r2 = copilot.ask(db, "Waarom hebben we Bitcoin afgewezen?")
    assert r2["data_gaps"] and "BTC-EUR" in r2["data_gaps"][0]


def test_copilot_rejects_ai_answers_with_invented_references(db, monkeypatch):
    monkeypatch.setenv("NEXUS_AI_DAILY_BUDGET_USD", "100")
    news.ingest(db, [news.FEEDS[0]], lambda f: fresh_rss(), datetime.now(tz=UTC))

    def client(refs):
        def create(**kw):
            body = {"answer": "antwoord", "refs": refs}
            return SimpleNamespace(usage=SimpleNamespace(input_tokens=10, output_tokens=5), stop_reason="end_turn",
                                   content=[SimpleNamespace(type="text", text=json.dumps(body))])
        return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    bad = copilot.ask(db, "Welk nieuws vraagt aandacht?", client=client(["news:999"]))
    assert bad["mode"] == "deterministic"
    ok_ref = bad["refs"][0]
    good = copilot.ask(db, "Welk nieuws vraagt aandacht?", client=client([ok_ref]))
    assert good["mode"] == "claude" and good["refs"] == [ok_ref] and good["cost_usd"] > 0


# ── API ─────────────────────────────────────────────────────────────────────────────────────
def test_sentinel_api(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    org = client.get("/api/central/org").json()
    assert len(org["roles"]) == len(central.ROLES) and org["live_trading"] is False
    assert client.get("/api/central/briefing").json()["draft"] is True
    assert client.post("/api/central/step").status_code == 401
    assert client.post("/api/central/step", headers=AUTH).status_code == 200
    radar = client.get("/api/social/radar").json()
    assert radar["x"]["connected"] is False and len(radar["tokens"]) == 3
    assert all(t["social"]["status"] == "not_connected" for t in radar["tokens"])
    assert client.get("/api/news/reactor").json()["signal_threshold"] == news.SIGNAL_THRESHOLD
    assert client.get("/api/pulse").status_code == 200
    assert client.get("/api/holdout/status").json()["contamination"]
    assert client.post("/api/copilot/ask", json={"question": "Wat is ons risico?"}).status_code == 401
    a = client.post("/api/copilot/ask", json={"question": "Wat is ons risico?"}, headers=AUTH).json()
    assert a["topic"] == "risk" and a["evidence"]
    client.post("/api/proposals", json=proposal(idempotency_key="tl-0001-abcdef"))
    tl = client.get("/api/central/timeline").json()
    st = {s["stage"]: s for s in tl[0]["stages"]}
    assert tl[0]["kind"] == "proposal" and st["risk_review"]["status"] in ("approved", "vetoed")
    assert client.get("/api/audit/verify").json()["ok"] is True

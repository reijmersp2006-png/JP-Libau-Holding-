"""Evolution Lab: nieuws, Council, externe vergelijking, leerronde, arena, audit-keten, taken en API.

Alle koersen hier zijn synthetisch (sinus + trend) en alleen voor tests; de AI wordt vervangen door een
nep-client, zodat er nooit een echte aanroep of kosten zijn.
"""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from jplh.config import load_config
from sqlalchemy import select

from nexus import champion, council, datasets, evolution, external, jobs, news
from nexus.db import AgentForecast, AuditLog, Database, Hypothesis, JobRun, ModelVersion, NewsEvent
from test_lab import series

AUTH = {"Authorization": "Bearer geheim-token-123"}


@pytest.fixture
def db():
    return Database("sqlite:///:memory:")


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    p = tmp_path_factory.mktemp("research") / "r.sqlite3"
    data = datasets.ResearchData(load_config(), None, p)
    data.save("IWDA.AS", "1d", series(900), "synthetic-test")
    return data


# ── externe vergelijking ───────────────────────────────────────────────────────────────────
def _csv(n, days):
    t0 = datetime(2025, 1, 1, tzinfo=UTC)
    rows = ["Timestamp,Asset,Side,Entry,Exit,Size,Fees"]
    for k in range(n):
        ts = t0 + timedelta(days=k % days, hours=k)
        rows.append(f"{ts.isoformat()},IWDA.AS,long,100,{101 if k % 3 else 99},2,0.1")
    return "\n".join(rows)


def test_external_csv_parse_derives_pnl_and_flags_missing_fees():
    p = external.parse(_csv(5, 5), "csv")
    assert p["completeness"] == "trades" and len(p["trades"]) == 5
    assert p["trades"][0]["pnl_derived"] and abs(p["trades"][1]["pnl"] - (2 * 1 - 0.1)) < 1e-9
    q = external.parse('[{"time": "2025-01-01", "symbol": "BTC", "pnl": 3}]', "json")
    assert any("zonder kosten" in i for i in q["issues"])


def test_external_aggregate_only_is_incomplete_and_gives_no_verdict():
    p = external.parse(json.dumps({"net_pnl": 42, "trades": 7}), "json")
    assert p["completeness"] == "aggregate"
    r = external.compare(p, [], 1000, "NEXUS")
    assert r["status"] == "incomplete" and "Geen oordeel" in r["verdict"]


def test_external_one_day_is_never_judged():
    p = external.parse(_csv(40, 1), "csv")
    r = external.compare(p, [], 1000, "NEXUS", external_capital=1000)
    assert r["status"] == "insufficient" and "Te weinig" in r["verdict"]


def test_external_scales_to_same_capital():
    p = external.parse(_csv(40, 25), "csv")
    nx = [{**t, "pnl": t["pnl"] / 2} for t in p["trades"]]
    r = external.compare(p, nx, 1000, "NEXUS", external_capital=2000)
    assert abs(r["external"]["net_pnl"] - r["nexus"]["net_pnl"]) < 1e-9   # extern geschaald naar €1000
    assert r["status"] == "compared" and r["comparability"]["instrument_overlap"] == ["IWDA.AS"]


def test_trades_from_paper_executions_use_average_cost():
    ex = [{"id": 1, "ts": "2025-01-01T10:00:00+00:00", "symbol": "X", "side": "buy", "quantity": 2, "price_eur": 10, "fee_eur": 1},
          {"id": 2, "ts": "2025-01-02T10:00:00+00:00", "symbol": "X", "side": "buy", "quantity": 2, "price_eur": 20, "fee_eur": 1},
          {"id": 3, "ts": "2025-01-03T10:00:00+00:00", "symbol": "X", "side": "sell", "quantity": 2, "price_eur": 30, "fee_eur": 1}]
    t = external.trades_from_executions(ex)
    assert len(t) == 1 and abs(t[0]["pnl"] - (60 - 1 - 31)) < 1e-9 and t[0]["ts"].tzinfo


# ── nieuws ─────────────────────────────────────────────────────────────────────────────────
RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Federal Reserve issues FOMC statement</title><link>https://x/1</link>
<description>The Committee decided to maintain the target range for the federal funds rate</description>
<pubDate>Wed, 05 Nov 2025 19:00:00 GMT</pubDate></item>
<item><title>Fed officials may consider rate cut</title><link>https://x/2</link><description></description>
<pubDate>Thu, 06 Nov 2025 12:00:00 GMT</pubDate></item>
<item><title>From the future</title><link>https://x/3</link><pubDate>Thu, 06 Nov 2031 12:00:00 GMT</pubDate></item>
</channel></rss>"""
ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>8-K Current report</title>
<link href="https://sec/1"/><updated>2025-11-04T16:30:00-05:00</updated><summary>Item 2.02 Results</summary></entry></feed>"""


def test_news_parses_rss_and_atom_with_utc_times():
    r = news.parse_feed(RSS)
    assert len(r) == 3 and r[0]["published_at"] == datetime(2025, 11, 5, 19, tzinfo=UTC)
    a = news.parse_feed(ATOM)
    assert a[0]["url"] == "https://sec/1" and a[0]["published_at"] == datetime(2025, 11, 4, 21, 30, tzinfo=UTC)


def test_news_ingest_dedupes_skips_future_and_reports_failures(db):
    feeds = [news.FEEDS[0], news.FEEDS[1]]

    def fetcher(feed):
        if feed.key == "ecb":
            raise OSError("403 van de proxy")
        return RSS

    now = datetime(2025, 11, 10, tzinfo=UTC)
    rep = news.ingest(db, feeds, fetcher, now)
    assert rep["fed"] == {"status": "ok", "items": 3, "new": 2}
    assert rep["ecb"]["status"] == "UNAVAILABLE" and "403" in rep["ecb"]["error"]
    assert news.ingest(db, feeds, fetcher, now)["fed"]["new"] == 0
    with db.session() as s:
        evs = {e.title: e for e in s.scalars(select(NewsEvent))}
    assert evs["Federal Reserve issues FOMC statement"].factuality == "fact"
    assert evs["Fed officials may consider rate cut"].factuality == "mixed"     # vooruitblik, geen feit
    assert evs["Federal Reserve issues FOMC statement"].expectation["available"] is False


def test_news_reaction_is_measured_after_publication_only():
    c = series(200)
    at = c[100].ts + timedelta(hours=12)
    r = news.reaction(c, at, {"d1": timedelta(days=1)})
    assert r["base_ts"] == c[99].ts.isoformat()            # laatste dag die vóór publicatie gesloten was
    assert r["d1"] is not None and news.reaction(c, c[-1].ts + timedelta(days=1), {"d1": timedelta(days=1)})["d1"] is None


# ── Council ────────────────────────────────────────────────────────────────────────────────
class FakeClient:
    """Geeft geldige gestructureerde antwoorden; telt aanroepen. Geen netwerk."""

    def __init__(self, action="BUY"):
        self.calls = []
        self.action = action
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        schema = kw["output_config"]["format"]["schema"]
        if "action" in schema["properties"]:
            body = {"action": self.action, "size_fraction": 3.0, "rationale": "r", "weighed": [], "disagreements": [],
                    "why_not_majority": "w", "conditions": [], "invalidation": "i"}
        else:
            body = {"stance": "BUY", "prob_up": 0.7, "horizon_days": 5, "summary": "s", "key_points": [],
                    "evidence": [{"ref": "ret:20d", "claim": "c"}], "counterarguments": [], "limitations": [],
                    "data_gaps": []}
            if "changed_mind" in schema["properties"]:
                body |= {"changed_mind": False, "challenges": []}
        return SimpleNamespace(usage=SimpleNamespace(input_tokens=1000, output_tokens=200), stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text=json.dumps(body))])


def test_council_without_key_is_unavailable_and_costs_nothing(db, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    r = council.convene(db, "IWDA.AS", "stocks", series(300))
    assert r["status"] == "unavailable" and r["decision"] == {} and r["cost_usd"] == 0 and r["independent"] == []


def test_council_respects_daily_budget(db, monkeypatch):
    monkeypatch.setenv("NEXUS_AI_DAILY_BUDGET_USD", "0.01")
    fc = FakeClient()
    r = council.convene(db, "IWDA.AS", "stocks", series(300), client=fc)
    assert r["status"] == "budget" and fc.calls == []


def test_council_debates_and_risk_veto_forces_no_trade(db, monkeypatch):
    monkeypatch.setenv("NEXUS_AI_DAILY_BUDGET_USD", "100")
    fc = FakeClient("BUY")
    veto = {"approved": False, "reason": "positie te groot", "checks": [{"passed": False, "detail": "max 10%"}]}
    c = series(300)
    r = council.convene(db, "IWDA.AS", "stocks", c, guardian_verdict=veto, client=fc, now=c[-1].ts)
    assert r["status"] == "done"
    assert r["decision"]["action"] == "NO_TRADE" and r["decision"]["size_fraction"] == 1.0
    llm = [a for a in council.relevant_agents("stocks") if a.kind == "llm"]
    assert len(fc.calls) == 2 * len(llm) + 1                     # onafhankelijk, debat, besluit
    assert all(kw["model"] == council.MODEL for kw in fc.calls)
    assert {d["agent"] for d in r["debate"]} >= {"risk", "quant", "auditor"}
    assert r["cost_usd"] > 0
    # Zelfde invoer binnen zes uur: uit de cache, geen nieuwe aanroepen.
    n = len(fc.calls)
    assert council.convene(db, "IWDA.AS", "stocks", c, guardian_verdict=veto, client=fc, now=c[-1].ts)["cached"]
    assert len(fc.calls) == n


def test_council_forecasts_resolve_into_scorecard_and_weights(db, monkeypatch):
    monkeypatch.setenv("NEXUS_AI_DAILY_BUDGET_USD", "100")
    c = series(400)
    council.convene(db, "IWDA.AS", "stocks", c[:300], client=FakeClient(), now=c[299].ts)
    assert council.resolve_forecasts(db, {"IWDA.AS": c}) > 0
    with db.session() as s:
        f = s.scalars(select(AgentForecast).where(AgentForecast.brier.is_not(None))).first()
    assert f is not None and 0 <= f.brier <= 1
    sc = {x["agent"]: x for x in council.scorecard(db)}
    assert sc["macro"]["forecasts"] == 1
    w = council.weights(db)
    assert 0 <= w["macro"]["weight"] <= 1 and not w["macro"]["calibrated"]   # één voorspelling: nog niet gekalibreerd


def test_failed_model_call_is_recorded_not_filled_in(db, monkeypatch):
    monkeypatch.setenv("NEXUS_AI_DAILY_BUDGET_USD", "100")
    fc = FakeClient()

    def refuse(**kw):
        return SimpleNamespace(usage=SimpleNamespace(input_tokens=10, output_tokens=0), stop_reason="refusal", content=[])
    fc.beta.messages.create = refuse
    r = council.convene(db, "IWDA.AS", "stocks", series(300), client=fc)
    assert r["status"] == "failed" and r["decision"] == {} and "weigerde" in r["error"]


# ── audit-keten ────────────────────────────────────────────────────────────────────────────
def test_audit_chain_detects_tampering(db):
    for k in range(4):
        db.audit("tester", f"stap{k}", {"k": k})
    assert db.verify_audit_chain() == {"ok": True, "checked": 4}
    with db.session.begin() as s:
        row = s.scalars(select(AuditLog).order_by(AuditLog.id).offset(1)).first()
        row.detail = {"k": 99}
    v = db.verify_audit_chain()
    assert v["ok"] is False and v["broken_at"] == row.id


# ── leerronde en arena ─────────────────────────────────────────────────────────────────────
def test_evolution_cycle_records_learns_and_registers_candidates_not_champions(db, synth):
    out = evolution.cycle(db, synth)
    assert out["observed"]["replay:IWDA.AS"] > 0 and out["measured"] > 0
    with db.session() as s:
        hs = s.scalars(select(Hypothesis)).all()
        models = s.scalars(select(ModelVersion)).all()
    assert len(hs) >= 4 and all(h.status in ("supported", "rejected", "inconclusive") for h in hs)
    champs = [m for m in models if m.role == "champion"]
    assert len(champs) == 1 and champs[0].key == "lab:volatility_filter"   # leren vervangt de kampioen nooit zelf
    for t in out["tested"]:
        if t["status"] == "supported":
            m = next(m for m in models if m.id == t["model_version_id"])
            assert m.status == "candidate" and m.role != "champion"
    # Tweede ronde: niets dubbel vastgelegd.
    again = evolution.cycle(db, synth, test=False)
    assert again["observed"]["replay:IWDA.AS"] == 0


def test_arena_keeps_holdout_paper_and_human_review_closed(synth, tmp_path):
    from nexus import alpha
    led = alpha.HoldoutLedger(tmp_path / "l.jsonl")
    rep = champion.arena(synth, "IWDA.AS", ledger=led)
    assert rep["champion"]["key"] == "volatility_filter" and rep["buy_hold"]["sharpe"] is not None
    for c in rep["challengers"]:
        g = c["gates"]
        early = all(g[k]["status"] == "pass" for k in ("1_backtest", "2_walk_forward", "4_costs", "5_sensitivity",
                                                         "6_monte_carlo"))
        assert (g["3_holdout"]["status"] == "locked") == (not early)
        assert g["7_paper"]["status"] != "pass"                   # nul paperdagen
        assert g["8_risk_review"]["status"] != "pass"             # altijd een mens
    assert len(led.entries()) == len(rep["passed_dev_gates"])          # elke holdout-blik staat in het register


# ── taken ──────────────────────────────────────────────────────────────────────────────────
def test_jobs_record_runs_and_failures(db):
    ok = jobs.Job("t_ok", "hourly", "ok", lambda ctx: {"n": 1})
    bad = jobs.Job("t_bad", "hourly", "stuk", lambda ctx: 1 / 0)
    assert jobs.run_job(db, ok, {})["status"] == "ok"
    assert jobs.run_job(db, bad, {})["status"] == "failed"
    with db.session() as s:
        st = {r.job: r.status for r in s.scalars(select(JobRun))}
    assert st == {"t_ok": "ok", "t_bad": "failed"}
    assert [r["job"] for r in jobs.run_due(db, [ok], {})] == []      # net gedraaid: niet opnieuw


# ── API ────────────────────────────────────────────────────────────────────────────────────
def test_evolution_api_reads_without_token_and_writes_with(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    o = client.get("/api/evolution/overview").json()
    assert o["live_trading"] is False and set(o["labels"]) == {"actual", "simulated", "estimate"}
    assert client.get("/api/council/agents").json()["model"] == council.MODEL
    assert len(client.get("/api/council/agents").json()["agents"]) == 13
    assert client.post("/api/evolution/cycle").status_code == 401
    assert client.post("/api/council/run", json={"symbol": "IWDA.AS"}).status_code == 401
    r = client.post("/api/council/run", json={"symbol": "IWDA.AS"}, headers=AUTH).json()
    assert r["status"] == "unavailable"
    assert client.get("/api/audit/verify").json()["ok"] is True
    assert client.get("/api/jobs").status_code == 200
    assert client.get("/api/evolution/discovery").json()["available"] is False


def test_external_import_and_compare_via_api(client):
    r = client.post("/api/external/import", headers=AUTH,
                    json={"system": "grok", "format": "json", "content": json.dumps({"net_pnl": 42, "trades": 7})}).json()
    assert r["completeness"] == "aggregate"
    assert client.get(f"/api/external/{r['id']}/compare").json()["status"] == "incomplete"
    r2 = client.post("/api/external/import", headers=AUTH,
                     json={"format": "csv", "content": _csv(40, 25), "starting_capital_eur": 1000}).json()
    cmp = client.get(f"/api/external/{r2['id']}/compare").json()
    assert cmp["status"] == "insufficient"                         # demo-paper heeft geen 30 gesloten trades
    assert client.post("/api/external/import", headers=AUTH, json={"format": "json", "content": "{nope"}).status_code == 422


def test_promotion_without_gates_is_refused_and_audited(client):
    client.app.state  # app gestart
    db = client.app.state.db
    evolution.seed_champions(db)
    with db.session.begin() as s:
        m = ModelVersion(key="vol_target", version=1, symbols=["IWDA.AS"], interval="1d", params={}, status="candidate")
        s.add(m)
        s.flush()
        mid = m.id
    r = client.post(f"/api/evolution/models/{mid}/promote", headers=AUTH, json={"target": "champion", "reason": "test"})
    assert r.status_code in (409, 422)
    with db.session() as s:
        assert s.get(ModelVersion, mid).role is None

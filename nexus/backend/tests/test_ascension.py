"""Ascension 5.0: Provider Control Center, AI Gateway, debat, evaluatie-arena, bewaking."""

import json
import socket
import urllib.error
from datetime import UTC, datetime
from email.message import Message
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from nexus import ai_eval, ai_gateway, debate, news, providers
from nexus.db import AiCall, Database, Hypothesis, OrchestratorTask, ProviderCheck

AUTH = {"Authorization": "Bearer geheim-token-123"}
SECRET = "sk-test-SECRET-value-1234567890"


@pytest.fixture
def db():
    return Database("sqlite:///:memory:")


@pytest.fixture(autouse=True)
def _no_keys(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY",
              "X_BEARER_TOKEN", "NEXUS_OPENAI_MODEL", "NEXUS_GEMINI_MODEL", "NEXUS_XAI_MODEL", "NEXUS_SEC_USER_AGENT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NEXUS_AI_DAILY_BUDGET_USD", "5")


def _http(code):
    h = Message()
    h["retry-after"] = "30"
    return urllib.error.HTTPError("https://x", code, "err", h, None)


# ── Provider Control Center ──────────────────────────────────────────────────────────────────
def test_error_classes_separate_sandbox_auth_limits_and_outages():
    assert providers.classify(urllib.error.URLError(OSError("Tunnel connection failed: 403 Forbidden")))[0] == "network_blocked"
    assert providers.classify(_http(401)) == ("auth_invalid", 401)
    assert providers.classify(_http(403)) == ("auth_denied", 403)
    assert providers.classify(_http(429)) == ("rate_limited", 429)
    assert providers.classify(_http(503)) == ("provider_outage", 503)
    assert providers.classify(_http(404)) == ("invalid_endpoint", 404)
    assert providers.classify(urllib.error.URLError(TimeoutError("timed out")))[0] == "timeout"
    assert providers.classify(urllib.error.URLError(socket.gaierror("Name or service not known")))[0] == "network_unreachable"
    assert providers.classify(json.JSONDecodeError("x", "y", 0))[0] == "parse_error"


def test_probe_sends_nothing_with_credentials_missing_but_checks_reachability():
    sent = []

    def getter(url, headers, timeout):
        sent.append(headers)
        raise _http(401)
    p = next(x for x in providers.PROVIDERS if x.key == "openai")
    r = providers.probe(p, getter)
    assert r["status"] == "not_configured" and r["error_class"] == "credentials_missing"
    assert r["detail"]["network"] == "reachable" and "Authorization" not in sent[0]


def test_probe_ok_records_rate_limit_and_never_stores_the_key(db, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    seen = {}

    def getter(url, headers, timeout):
        seen.update(headers)
        return 200, {"anthropic-ratelimit-requests-remaining": "49"}, b'{"data": [], "has_more": false}'
    rows = providers.check_all(db, getter, keys=["anthropic"])
    assert rows[0]["status"] == "ok" and rows[0]["detail"]["rate_limit"]["anthropic-ratelimit-requests-remaining"] == "49"
    assert seen["x-api-key"] == SECRET
    st = next(r for r in providers.status(db) if r["key"] == "anthropic")
    assert st["state"] == "CONNECTED" and st["last_success"]
    assert SECRET not in json.dumps(providers.status(db)) and SECRET not in json.dumps(ai_gateway.describe())


def test_probe_error_is_redacted_and_classified(db, monkeypatch):
    monkeypatch.setenv("X_BEARER_TOKEN", SECRET)

    def getter(url, headers, timeout):
        raise urllib.error.URLError(OSError(f"Tunnel connection failed: 403 Forbidden {SECRET}"))
    r = providers.check_all(db, getter, keys=["x_api"])[0]
    assert r["error_class"] == "network_blocked" and SECRET not in json.dumps(r)
    with db.session() as s:
        assert s.scalars(select(ProviderCheck)).one().error_class == "network_blocked"


def test_feed_probe_parses_items():
    from test_evolution_lab import RSS
    p = next(x for x in providers.all_providers() if x.key == "news:fed")
    r = providers.probe(p, lambda u, h, t: (200, {}, RSS.encode()))
    assert r["status"] == "ok" and r["detail"]["items"] > 0


# ── AI Gateway ───────────────────────────────────────────────────────────────────────────────
def _gw(db, behaviour: dict, configured=("openai", "gemini")):
    calls = []

    def make(p):
        def adapter(system, user, schema, effort, timeout, max_tokens, model):
            calls.append(p)
            b = behaviour[p]
            if isinstance(b, Exception):
                raise b
            return b(system, user) if callable(b) else (b, 100, 50)
        return adapter
    g = ai_gateway.Gateway(db, adapters={p: make(p) for p in behaviour},
                           is_configured=lambda p: (p in configured, "ingesteld" if p in configured else "geen sleutel"))
    return g, calls


SCHEMA = {"type": "object", "required": ["label"], "properties": {"label": {"type": "string", "enum": ["a", "b"]}}}


def test_gateway_refuses_numerical_tasks():
    g = ai_gateway.Gateway(Database("sqlite:///:memory:"))
    for t in ("valuation", "risk_limits", "order_validation", "position_sizing"):
        with pytest.raises(ai_gateway.DeterministicOnly):
            g.complete(t, "s", "u", SCHEMA)


def test_gateway_falls_back_on_error_and_invalid_schema_and_logs_every_call(db):
    g, calls = _gw(db, {"openai": RuntimeError("boom"), "gemini": {"label": "zzz"}, "anthropic": {"label": "a"}},
                   configured=("openai", "gemini", "anthropic"))
    g.policies["t"] = ai_gateway.Policy(("openai", "gemini", "anthropic"), "test")
    r = g.complete("t", "s", "u", SCHEMA)
    assert r["provider"] == "anthropic" and r["output"] == {"label": "a"} and calls == ["openai", "gemini", "anthropic"]
    assert [x["status"] for x in r["trail"]] == ["error", "error", "ok"]
    with db.session() as s:
        logged = s.scalars(select(AiCall).order_by(AiCall.id)).all()
    assert [c.status for c in logged] == ["error", "error", "ok"] and logged[-1].cost_usd > 0


def test_gateway_skips_unconfigured_and_raises_when_nobody_answers(db):
    g, calls = _gw(db, {"openai": {"label": "a"}}, configured=())
    with pytest.raises(ai_gateway.NoProvider) as e:
        g.complete("copilot_answer", "s", "u", SCHEMA)
    assert calls == [] and all(t["status"] == "skipped" for t in e.value.trail)


def test_circuit_breaker_opens_after_repeated_failures(db):
    g, calls = _gw(db, {"openai": RuntimeError("down"), "gemini": {"label": "b"}})
    g.policies["t"] = ai_gateway.Policy(("openai", "gemini"), "test")
    for _ in range(3):
        g.complete("t", "s", "u", SCHEMA)
    assert g.breaker_open("openai")
    calls.clear()
    r = g.complete("t", "s", "u", SCHEMA)
    assert calls == ["gemini"] and r["trail"][0]["reason"].startswith("stroomonderbreker")


def test_unknown_price_is_reported_not_invented(db):
    g, _ = _gw(db, {"openai": {"label": "a"}}, configured=("openai",))
    g.policies["t"] = ai_gateway.Policy(("openai",), "test")
    r = g.complete("t", "s", "u", SCHEMA)
    assert r["cost_usd"] is None and r["cost_known"] is False


def test_budget_exhausted_stops_calls(db, monkeypatch):
    monkeypatch.setenv("NEXUS_AI_DAILY_BUDGET_USD", "0")
    g, calls = _gw(db, {"openai": {"label": "a"}}, configured=("openai",))
    g.policies["t"] = ai_gateway.Policy(("openai",), "test")
    with pytest.raises(ai_gateway.NoProvider):
        g.complete("t", "s", "u", SCHEMA)
    assert calls == []


def test_other_providers_need_an_explicit_model_name(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    assert ai_gateway.configured("openai") == (False, "geen modelnaam (NEXUS_OPENAI_MODEL)")
    monkeypatch.setenv("NEXUS_OPENAI_MODEL", "model-x")
    assert ai_gateway.configured("openai")[0] is True


def test_adapter_contracts_with_recorded_response_shapes():
    seen = {}

    def post(url, body, headers, timeout):
        seen[url] = body
        if "generativelanguage" in url:
            return {"candidates": [{"content": {"parts": [{"text": '{"label": "a"}'}]}, "finishReason": "STOP"}],
                    "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 3}, "modelVersion": "g-1"}
        return {"choices": [{"message": {"content": '{"label": "b"}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 2}, "model": "served-1"}
    assert ai_gateway.openai_adapter("s", "u", SCHEMA, "low", 5, 100, "m", post=post) == ({"label": "b"}, 11, 2, "served-1")
    assert ai_gateway.xai_adapter("s", "u", SCHEMA, "low", 5, 100, "m", post=post)[:3] == ({"label": "b"}, 11, 2)
    assert ai_gateway.gemini_adapter("s", "u", SCHEMA, "low", 5, 100, "m", post=post) == ({"label": "a"}, 12, 3, "g-1")
    oa = seen["https://api.openai.com/v1/chat/completions"]
    assert oa["messages"][0]["role"] == "system" and oa["response_format"]["type"] == "json_schema"

    def refuse(url, body, headers, timeout):
        return {"candidates": [{"finishReason": "SAFETY"}]}
    with pytest.raises(RuntimeError):
        ai_gateway.gemini_adapter("s", "u", SCHEMA, "low", 5, 100, "m", post=refuse)


def test_anthropic_adapter_uses_the_existing_council_call():
    def create(**kw):
        assert kw["output_config"]["format"]["type"] == "json_schema"
        return SimpleNamespace(usage=SimpleNamespace(input_tokens=7, output_tokens=3), stop_reason="end_turn",
                               model="served-model", content=[SimpleNamespace(type="text", text='{"label": "a"}')])
    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    assert ai_gateway.anthropic_adapter("s", "u", SCHEMA, "low", 5, 100, "m", client=client) == ({"label": "a"}, 7, 3,
                                                                                                "served-model")


# ── Debat ────────────────────────────────────────────────────────────────────────────────────
def _hyp(db, status="supported"):
    with db.session.begin() as s:
        h = Hypothesis(source="test", title="Minder handelen helpt", statement="Minder trades verlaagt kosten",
                       test={"family": "volfilter"}, status=status, result={"sharpe_delta": 0.3, "p": 0.04})
        s.add(h)
        s.flush()
        return h.id


def test_debate_flags_unsupported_claims_and_needs_two_providers_for_independence(db):
    hid = _hyp(db)
    subject, facts, quant = debate.facts_for_hypothesis(db, hid)
    seen = {}

    def research(system, user):
        return ({"thesis": "x", "claims": [
            {"text": "kosten dalen", "evidence": [f"hypothesis:{hid}:result"], "confidence": 0.7},
            {"text": "werkt overal", "evidence": ["model:zegt-het"], "confidence": 0.9}],
            "uncertainty": "klein monster", "falsifiers": ["nieuwe data"]}, 100, 50)

    def challenge(system, user):
        seen["user"] = user
        return ({"objections": [{"claim": 1, "text": "geen bewijs", "evidence": [], "severity": "medium"}],
                 "unsupported_claims": [1], "confidence_in_thesis": 0.5}, 100, 50)
    g, _ = _gw(db, {"anthropic": research, "openai": challenge}, configured=("anthropic", "openai"))
    out = debate.run(db, g, subject, facts, quant, ref=f"hypothesis:{hid}")
    assert out["status"] == "done" and out["independent"] is True
    assert out["author"] == "anthropic" and out["challenger"] == "openai"
    assert "BEWERINGEN (geen bewijs)" in seen["user"]
    s = out["summary"]
    assert [c["index"] for c in s["unsupported"]] == [1] and [c["index"] for c in s["agreements"]] == [0]
    assert s["recommendation"].startswith("verder testen")
    with db.session() as ss:
        t = ss.scalars(select(OrchestratorTask).where(OrchestratorTask.source_ref == f"debate:{out['id']}")).one()
    assert t.status == "escalated" and t.agent == "ceo"


def test_debate_without_providers_is_unavailable_and_escalates_nothing(db):
    hid = _hyp(db)
    subject, facts, quant = debate.facts_for_hypothesis(db, hid)
    g, _ = _gw(db, {"openai": {"label": "a"}}, configured=())
    out = debate.run(db, g, subject, facts, quant)
    assert out["status"] == "unavailable" and out["independent"] is False
    assert [x["step"] for x in out["steps"]] == ["research", "quant", "risk", "central"]
    with db.session() as s:
        assert s.scalars(select(OrchestratorTask)).first() is None


def test_same_provider_debate_is_marked_not_independent(db):
    hid = _hyp(db, status="inconclusive")
    subject, facts, quant = debate.facts_for_hypothesis(db, hid)
    both = {"anthropic": lambda s, u: ({"thesis": "x", "claims": [], "uncertainty": "-", "falsifiers": []}, 1, 1)
            if "BEWERINGEN" not in u else ({"objections": [], "unsupported_claims": [], "confidence_in_thesis": 0.4}, 1, 1)}
    g, _ = _gw(db, both, configured=("anthropic",))
    out = debate.run(db, g, subject, facts, quant)
    assert out["independent"] is False and "zelfde aanbieder" in out["summary"]["independence"]
    assert out["summary"]["recommendation"].startswith("geen actie")


# ── Evaluatie-arena ──────────────────────────────────────────────────────────────────────────
def test_news_benchmark_measures_rules_and_compares_models_with_uncertainty(db):
    g, _ = _gw(db, {"gemini": lambda s, u: ({"label": "other"}, 10, 2)}, configured=("gemini",))
    out = ai_eval.news_benchmark(db, g, providers=["gemini", "openai"])
    det = out["entrants"][0]
    assert det["entrant"] == "deterministic" and det["n"] == 30 and 0 <= det["accuracy"] <= 1
    gem = next(e for e in out["entrants"] if e["entrant"] == "gemini")
    assert gem["accuracy"] < det["accuracy"] and gem["verdict"] == "slechter dan de vaste regels"
    assert next(e for e in out["entrants"] if e["entrant"] == "openai")["status"] == "not_available"
    assert ai_eval.latest(db)["benchmark"] == "news-labels-v1"


def test_benchmark_set_is_frozen_and_uses_known_labels():
    b = ai_eval.load()
    assert b["frozen"] == "2026-11-13" and len(b["items"]) == 30
    assert all(i["label"] in b["labels"] for i in b["items"])
    cats = {c for c, _ in news.CATEGORIES} | {"other"}
    assert set(b["labels"]) <= cats


def test_calibration_says_nothing_without_resolved_forecasts(db):
    assert ai_eval.calibration(db)["rows"] == []


def test_importance_is_not_opportunity():
    assert news.opportunity("rate_decision", [])["status"] == "unknown"
    study = [{"category": "rate_decision", "symbol": "IWDA.AS", "mean_z_ci95": [-0.2, 0.3]}]
    assert news.opportunity("rate_decision", study)["status"] == "no_edge"


# ── API ──────────────────────────────────────────────────────────────────────────────────────
def test_ascension_api_is_read_safe_and_write_protected(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    r = client.get("/api/providers")
    assert r.status_code == 200 and SECRET not in r.text
    keys = {p["key"] for p in r.json()["providers"]}
    assert {"anthropic", "openai", "gemini", "xai", "x_api", "goplus", "dexscreener", "news:fed"} <= keys
    gw = client.get("/api/ai/gateway").json()
    assert "valuation" in gw["deterministic_only"] and gw["routes"]["copilot_answer"]
    health = client.get("/api/ops/health").json()
    assert health["audit_chain_ok"] is True and "ai_budget" in health
    assert client.get("/api/ai/eval").status_code == 200
    for path, body in (("/api/providers/check", {}), ("/api/ai/eval", None), ("/api/ai/debate", {"hypothesis_id": 1})):
        assert client.post(path, json=body).status_code == 401
    assert client.post("/api/ai/debate", json={"hypothesis_id": 999}, headers=AUTH).status_code == 404


def test_providers_job_is_registered():
    from nexus import jobs
    assert any(j.key == "providers" for j in jobs.JOBS)
    assert datetime.now(tz=UTC)

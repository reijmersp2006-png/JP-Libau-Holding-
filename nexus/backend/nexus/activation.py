"""Mijlpaal C2: eerste gecontroleerde, echte Council-taak via de AI Gateway.

Eén kleine onderzoeksvraag over één instrument, met echte feiten uit de database. Vastgelegd:
provider, het model dat echt antwoordde, latency, tokens, geschatte kosten vóóraf en werkelijke kosten
achteraf, schema-controle, geldigheid van de bronverwijzingen, een fallback-test, een budgettest en
een CEO-escalatie. Zonder sleutel: NOT CONNECTED, en er wordt niets nagebootst.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import select

from nexus import ai_gateway, central, debate, providers
from nexus.db import Database, NewsEvent, ResearchRun

MAX_OUT_TOKENS = 1200


def _facts(db: Database, ctx: dict, symbol: str) -> list[dict]:
    facts: list[dict] = []
    data = ctx.get("data")
    if data is not None:
        c = data.raw(symbol, "1d")
        if len(c) >= 31:
            facts.append({"id": f"market:{symbol}:1d", "text": (
                f"{symbol} slot {c[-1].close:.6g} op {c[-1].ts.date()}; 1 dag {c[-1].close / c[-2].close - 1:+.2%}, "
                f"7 dagen {c[-1].close / c[-8].close - 1:+.2%}, 30 dagen {c[-1].close / c[-31].close - 1:+.2%} "
                "(vertraagde dagkoersen)")})
    with db.session() as s:
        for e in s.scalars(select(NewsEvent).order_by(NewsEvent.published_at.desc()).limit(5)):
            facts.append({"id": f"news:{e.id}", "text": f"{e.source}: {e.title}"})
    return facts


def estimate_cost(provider: str, system: str, user: str, max_out: int = MAX_OUT_TOKENS) -> float | None:
    """Vooraf: ~4 tekens per token voor de invoer, maximaal ``max_out`` voor de uitvoer (bovengrens)."""
    pr = ai_gateway.price_of(provider)
    if not pr:
        return None
    return ((len(system) + len(user)) / 4 * pr[0] + max_out * pr[1]) / 1e6


def council_activation(db: Database, gateway: ai_gateway.Gateway, ctx: dict, symbol: str = "BTC-EUR",
                       probe_getter=None, now: datetime | None = None) -> dict:
    now = now or datetime.now(tz=UTC)
    p = next(x for x in providers.PROVIDERS if x.key == "anthropic")
    probe = providers.probe(p, probe_getter) if probe_getter else providers.probe(p)
    report: dict = {"symbol": symbol, "at": now.isoformat(), "config": ai_gateway.describe(),
                    "connectivity": {k: probe[k] for k in ("status", "error_class", "http_status", "latency_ms")},
                    "checks": []}
    usable = [d["provider"] for d in report["config"] if d["usable"]]
    if not usable:
        report["status"] = "NOT_CONNECTED"
        report["reason"] = "geen AI-aanbieder ingesteld; er is geen echte aanroep gedaan"
        _save(db, report)
        return report

    facts = _facts(db, ctx, symbol)
    ids = {f["id"] for f in facts}
    system = debate.SYS_RESEARCH
    user = f"ONDERWERP: korte onderzoeksvraag over {symbol}: is er reden voor verder onderzoek?\n" + json.dumps(
        {"FEITEN": facts}, ensure_ascii=False)
    pol = gateway.policies["research_synthesis"]
    gw = replace(gateway, policies={**gateway.policies,
                                    "activation": ai_gateway.Policy(pol.providers, "activatietest", "low", 90, MAX_OUT_TOKENS)})
    est = estimate_cost(usable[0], system, user)
    try:
        r = gw.complete("activation", system, user, debate.CLAIMS_SCHEMA, ref=f"activation:{symbol}", now=now)
    except ai_gateway.NoProvider as e:
        report.update(status="FAILED", trail=e.trail, reason="alle ingestelde aanbieders faalden")
        _save(db, report)
        return report
    bad = [ref for c in r["output"]["claims"] for ref in c.get("evidence", []) if ref not in ids]
    report["live_call"] = {"provider": r["provider"], "model": r["model"], "requested_model": r.get("requested_model"),
                           "latency_ms": r["latency_ms"], "tokens_in": r["tokens_in"], "tokens_out": r["tokens_out"],
                           "estimated_cost_usd": est, "actual_cost_usd": r["cost_usd"], "trail": r["trail"]}
    report["checks"].append({"check": "schema", "ok": True, "detail": "antwoord volgt het schema (gateway-controle)"})
    report["checks"].append({"check": "evidence_refs", "ok": not bad,
                             "detail": "alle verwijzingen bestaan" if not bad else f"onbekende verwijzingen: {bad[:5]}"})

    # Fallback: een bewust falende eerste aanbieder, daarna de echte. Kost één extra kleine aanroep.
    def failing(*a, **k):
        raise RuntimeError("bewust falende testaanbieder")
    fb = replace(gw, adapters={**gw.adapters, "_fail": failing},
                 is_configured=lambda x: (True, "test") if x == "_fail" else gateway.is_configured(x),
                 policies={**gw.policies, "activation_fallback": ai_gateway.Policy(("_fail", *pol.providers), "fallbacktest",
                                                                                  "low", 60, 200)})
    try:
        f = fb.complete("activation_fallback", "Antwoord met JSON {\"label\": \"ok\"}.", "test",
                        {"type": "object", "required": ["label"], "properties": {"label": {"type": "string"}}},
                        ref="activation:fallback", now=now)
        report["checks"].append({"check": "fallback", "ok": f["trail"][0]["status"] == "error" and f["provider"] != "_fail",
                                 "detail": f"na een fout antwoordde {f['provider']}"})
    except ai_gateway.NoProvider as e:
        report["checks"].append({"check": "fallback", "ok": False, "detail": str(e.trail)[:200]})

    # Budget: met nul budget mag er niets verstuurd worden.
    calls = []
    zero = replace(gw, budget_override=0.0, adapters={k: (lambda *a, _k=k, **kw: calls.append(_k)) for k in gw.adapters})
    try:
        zero.complete("activation", system, user, debate.CLAIMS_SCHEMA, now=now)
        ok = False
    except ai_gateway.NoProvider:
        ok = not calls
    report["checks"].append({"check": "budget", "ok": ok, "detail": "bij een leeg budget wordt geen aanroep gedaan"})

    rid = _save(db, {**report, "status": "CONNECTED" if all(c["ok"] for c in report["checks"]) else "DEGRADED"})
    tid = central.enqueue(db, "approval", "ceo", f"activatie-run #{rid}: eerste echte AI-aanroep beoordelen",
                          subject=symbol, source_ref=f"activation:{rid}", status="escalated", priority=60)
    report["checks"].append({"check": "ceo_escalation", "ok": tid is not None, "detail": f"taak #{tid}"})
    report["status"] = "CONNECTED" if all(c["ok"] for c in report["checks"]) else "DEGRADED"
    report["run_id"] = rid
    with db.session.begin() as s:
        s.get(ResearchRun, rid).report = json.loads(json.dumps(report, default=str))
    return report


def _save(db: Database, report: dict) -> int:
    with db.session.begin() as s:
        r = ResearchRun(kind="activation_council", status=report.get("status", "NOT_CONNECTED").lower()[:16],
                        summary={"status": report.get("status")}, report=json.loads(json.dumps(report, default=str)),
                        ai_requests=len((report.get("live_call") or {}).get("trail", [])),
                        ai_cost_usd=float((report.get("live_call") or {}).get("actual_cost_usd") or 0))
        s.add(r)
        s.flush()
        return r.id


def latest(db: Database) -> dict | None:
    with db.session() as s:
        r = s.scalars(select(ResearchRun).where(ResearchRun.kind == "activation_council")
                      .order_by(ResearchRun.id.desc())).first()
        return r.report if r else None

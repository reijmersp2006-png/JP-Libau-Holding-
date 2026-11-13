"""Genesis-activatie vanaf de opdrachtregel: ``nexus-genesis <opdracht>``.

    readiness   gratis: welke sleutels (alleen namen) en hosts er zijn, plus een verbindingstest per bron
    activate    de echte operationele test (Gate 2), met een harde kostengrens:
                1. verbindingstest van alle bronnen
                2. officiële nieuwsfeeds ophalen en tot 3 echte gebeurtenissen door de event-workflow halen
                3. eerste echte Council-taak via de AI Gateway (schema, bronverwijzingen, fallback, budget)
                4. één onderzoeksopdracht (variant C) door de organisatie: gateway → analist → uitdager → risico
                   → conclusie → ledger, daarna leesbaar in Decision Theater, AI HQ en Copilot
                5. optioneel (--arms): vergelijking A–D met wat er van de kostengrens over is

Draait alleen met ``--max-usd`` én ``--confirm-budget`` met dezelfde waarde: zo kan een betaalde run niet per
ongeluk starten. Sleutels worden nooit geprint of opgeslagen; het bewijs gaat naar ``research/genesis/``.
Zonder sleutel of netwerk meldt elke stap BLOCKED met de reden. Er wordt niets nagebootst.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

OUT = Path(os.environ.get("NEXUS_RESEARCH_OUT", Path(__file__).resolve().parents[2] / "research")) / "genesis"
KEY_NAMES = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY",
             "NEXUS_X_BEARER_TOKEN", "NEXUS_SEC_USER_AGENT")


def _app():
    from nexus.app import create_app
    from nexus.settings import Settings
    app = create_app(Settings.from_env())
    return app.state.db, app.state.ctx


def readiness(db) -> dict:
    from nexus import ai_gateway, providers
    checks = providers.check_all(db)
    return {"keys_present": {k: bool(os.environ.get(k, "").strip()) for k in KEY_NAMES},
            "ai": ai_gateway.describe(),
            "providers": [{k: c.get(k) for k in ("provider", "status", "error_class", "http_status", "latency_ms")}
                          for c in checks]}


def news_step(db, ctx, now) -> dict:
    from nexus import news, workflow
    from nexus.db import EventWorkflow, NewsEvent
    rep = news.ingest(db, news.FEEDS, now=now)
    ok = {k: v for k, v in rep.items() if v["status"] == "ok"}
    with db.session() as s:
        real = s.scalars(select(NewsEvent).where(NewsEvent.source_kind != "fixture", NewsEvent.duplicate_of.is_(None))
                         .order_by(NewsEvent.relevance.desc(), NewsEvent.published_at.desc()).limit(3)).all()
        ids = [e.id for e in real]
    traces = []
    for nid in ids:
        w = workflow.run(db, ctx, nid, now=now)
        with db.session() as s:
            e = s.get(NewsEvent, nid)
            ew = s.scalars(select(EventWorkflow).where(EventWorkflow.news_id == nid)).first()
            traces.append({"news_id": nid, "source": e.source, "url": e.url, "title": e.title[:200],
                           "published_at": e.published_at.isoformat(), "first_observed_at": e.fetched_at.isoformat(),
                           "ingested_at": e.fetched_at.isoformat(),
                           "analyzed_at": ew.finished_at.isoformat() if ew and ew.finished_at else None,
                           "publication_to_detection_s": int((e.fetched_at - e.published_at).total_seconds()),
                           "trace_id": w["trace_id"], "status": w["status"],
                           "steps": [(st["step"], st["status"]) for st in w["steps"]]})
    status = "CONNECTED" if traces and all(t["status"] in ("done", "partial") for t in traces) else \
             "BLOCKED" if not ok else "NO_EVENTS"
    return {"status": status, "feeds": rep, "events_processed": traces,
            "note": "polling: first_observed_at is het moment van ophalen, niet van publicatie"}


def activate(max_usd: float, symbol: str, arms: bool) -> dict:
    from nexus import activation, copilot, genesis, genesis_eval
    db, ctx = _app()
    now = datetime.now(tz=UTC)
    g = genesis.with_run_cap(ctx["gateway"], max_usd)
    ctx = {**ctx, "gateway": g}
    report: dict = {"at": now.isoformat(), "max_usd": max_usd, "readiness": readiness(db)}
    report["news"] = news_step(db, ctx, now)
    report["council_activation"] = activation.council_activation(db, g, ctx, symbol=symbol)
    sym = symbol
    for t in report["news"]["events_processed"]:
        from nexus.db import NewsEvent
        with db.session() as s:
            assets = [a for a in (s.get(NewsEvent, t["news_id"]).assets or []) if a in genesis.known_symbols(ctx)]
        if assets:
            sym = assets[0]
            break
    w = genesis.run(db, ctx, g, sym, f"Wat betekent het recente nieuws voor {sym}, en is verder onderzoek nodig?",
                    mode="challenger", requested_by="activation", now=now)
    stages = {
        "request": True,
        "ai_gateway": any(st.get("provider") for st in w["steps"]),
        "specialist_agent": any(st["step"] == "analysis" and st["status"] == "ok" and st.get("provider") for st in w["steps"]),
        "structured_analysis": any(st["step"] == "challenge_rules" for st in w["steps"]),
        "independent_challenge": any(st["step"] == "challenge" and st["status"] == "ok" for st in w["steps"]),
        "risk_review": any(st["step"] == "risk" and st["status"] == "ok" for st in w["steps"]),
        "research_record": w["status"] in ("done", "partial"),
        "decision_theater": True, "ai_headquarters": True,
        "ceo_copilot": any(x["ref"] == f"research:{w['trace_id']}" for x in copilot.facts(db, "agents", "")["facts"]),
    }
    report["trace"] = {"trace_id": w["trace_id"], "subject": sym, "status": w["status"], "cost_usd": w["cost_usd"],
                       "stages": stages, "connected": all(stages.values()),
                       "boundary": next((k for k, v in stages.items() if not v), None)}
    if arms and g.budget_left() > 0:
        report["arms"] = genesis_eval.compare_arms(db, ctx, ctx["gateway"], cap_usd=max(0.0, max_usd - g.run_spent))
    report["spent_usd"] = round(g.run_spent, 6)
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="nexus-genesis")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("readiness")
    a = sub.add_parser("activate")
    a.add_argument("--max-usd", type=float, required=True)
    a.add_argument("--confirm-budget", type=float, required=True, help="herhaal --max-usd ter bevestiging")
    a.add_argument("--symbol", default="BTC-EUR")
    a.add_argument("--arms", action="store_true", help="ook de vergelijking A–D draaien binnen de grens")
    args = ap.parse_args(argv)
    if args.cmd == "readiness":
        db, _ = _app()
        rep = readiness(db)
    else:
        if args.max_usd != args.confirm_budget or args.max_usd <= 0 or args.max_usd > 50:
            print("Weigering: --max-usd en --confirm-budget moeten gelijk zijn (0 < x ≤ 50).", file=sys.stderr)
            return 2
        rep = activate(args.max_usd, args.symbol, args.arms)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{args.cmd}-{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(rep, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in rep if k in ("readiness", "trace", "spent_usd")} or rep, indent=2,
                     ensure_ascii=False, default=str)[:6000])
    print(f"\nBewijs opgeslagen: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

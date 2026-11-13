"""Mijlpaal C5: één nieuwsgebeurtenis door de hele organisatie, met een trace-id.

    News Reactor (valideren, ontdubbelen, instrumenten, feiten, classificatie)
    → Social Intelligence (X-meting of "niet verbonden")
    → Market Data (beweging vóór en na detectie, vertraagde dagkoersen)
    → onderzoeker + onafhankelijke uitdager (AI Gateway; overgeslagen zonder aanbieder)
    → Quant Engine (event study: is deze soort nieuws ooit een kans gebleken?)
    → Risk Guardian (onderzoek, nooit een order)
    → NEXUS Central (onderzoeksprioriteit, niet een handelsadvies)
    → Copilot-uitleg (vaste tekst uit de feiten)
    → opslag voor latere evaluatie

Elke stap krijgt status, tijd en detail. Een ontbrekende bron stopt de keten niet, maar staat er als
"unavailable". Elke gebeurtenis krijgt hooguit één workflow (uniek op news_id); AI-stappen hebben een
eigen daglimiet bovenop het AI-budget. Nieuwstekst is data: hij gaat alleen als gelabelde feiten naar
een model, en geen enkele stap kan een order plaatsen of een instelling wijzigen.
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from nexus import news
from nexus.db import Database, EventWorkflow, NewsEvent, SocialSnapshot

MAX_PER_RUN = 3


def _utc(d):
    return None if d is None else (d if d.tzinfo else d.replace(tzinfo=UTC))


def ai_per_day() -> int:
    try:
        return int(os.environ.get("NEXUS_WORKFLOW_AI_PER_DAY", "5"))
    except ValueError:
        return 5


def _step(steps, step, agent, status, detail, t0=None):
    now = datetime.now(tz=UTC)
    steps.append({"step": step, "agent": agent, "status": status, "at": now.isoformat(),
                  "ms": int((now - t0).total_seconds() * 1000) if t0 else None, "detail": detail})


def market_context(candles, published: datetime, detected: datetime) -> dict:
    """Beweging vóór de publicatie (5 dagen) en ná de detectie (1 dag), uit dagkoersen. Geen intraday."""
    before = [c for c in candles if _utc(c.ts) < published]
    after = [c for c in candles if _utc(c.ts) > detected]
    out = {"resolution": "1d", "label": "DELAYED"}
    if len(before) >= 6:
        out["move_before_5d"] = before[-1].close / before[-6].close - 1
        out["last_close_before"] = before[-1].close
    if before and after:
        out["move_after_1d"] = after[0].close / before[-1].close - 1
    else:
        out["move_after_1d"] = None
        out["after_note"] = "nog geen dagkoers na de detectie"
    out["spread_liquidity"] = None
    out["missing"] = ["spread en orderboekdiepte (geen bron gekoppeld)"]
    return out


def intelligence(e: NewsEvent, ctx_rows: dict, opportunity: dict, social: dict) -> dict:
    official = e.source_kind in ("official", "exchange")
    reacted = {s: (m.get("move_before_5d"), m.get("move_after_1d")) for s, m in ctx_rows.items()}
    missing = ["marktverwachting (geen consensusbron)"]
    if not ctx_rows:
        missing.append("koersdata voor de betrokken instrumenten")
    if social.get("status") != "ok":
        missing.append("sociale discussie (X niet verbonden)")
    missing += sorted({x for m in ctx_rows.values() for x in m.get("missing", [])})
    enough = opportunity.get("status") == "candidate"
    return {
        "what_happened": e.title, "facts": e.facts or [],
        "assets": e.assets or [],
        "confirmed": "bevestigd: officiële bron" if official and e.factuality == "fact" else
                     "deels: bevat vooruitblik of speculatie" if official else "niet bevestigd",
        "new_information": e.duplicate_of is None,
        "market_expectation": (e.expectation or {}).get("reason", "niet beschikbaar"),
        "already_reacted": reacted,
        "enough_evidence_for_research": enough,
        "evidence_note": opportunity.get("reason"),
        "missing": missing,
    }


def priority(e: NewsEvent, opportunity: dict) -> str:
    rel = e.relevance or 0
    if e.duplicate_of is not None:
        return "geen (duplicaat)"
    if opportunity.get("status") == "candidate" and rel >= 0.7:
        return "hoog"
    return "middel" if rel >= news.SIGNAL_THRESHOLD else "laag"


def run(db: Database, ctx: dict, news_id: int, now: datetime | None = None) -> dict:
    now = now or datetime.now(tz=UTC)
    with db.session() as s:
        existing = s.scalars(select(EventWorkflow).where(EventWorkflow.news_id == news_id)).first()
        if existing:
            return get(db, existing.id)
        e = s.get(NewsEvent, news_id)
        if e is None:
            raise KeyError(news_id)
        s.expunge(e)
    trace = f"evt-{news_id}-{hashlib.sha256(f'{news_id}|{e.content_hash}'.encode()).hexdigest()[:10]}"
    with db.session.begin() as s:
        wf = EventWorkflow(trace_id=trace, news_id=news_id, status="running", simulated=e.source_kind == "fixture",
                           steps=[], created_at=now)
        s.add(wf)
        s.flush()
        wid = wf.id
    steps: list[dict] = []
    cost = 0.0

    # 1-5 · News Reactor
    t0 = datetime.now(tz=UTC)
    pub, fetched = _utc(e.published_at), _utc(e.fetched_at)
    skew = (fetched - pub).total_seconds()
    ts_ok = skew >= -300 and pub > fetched - timedelta(days=30)
    _step(steps, "validate", "news", "ok" if ts_ok else "warning",
          {"source": e.source, "url": e.url, "published_at": pub.isoformat(), "detected_at": fetched.isoformat(),
           "publication_to_detection_s": skew, "timestamp_check": "ok" if ts_ok else "tijdstempel verdacht"}, t0)
    _step(steps, "deduplicate", "news", "duplicate" if e.duplicate_of else "ok",
          {"duplicate_of": e.duplicate_of, "cluster": e.cluster_key})
    _step(steps, "classify", "news", "ok",
          {"category": e.category, "assets": e.assets, "factuality": e.factuality, "relevance": e.relevance,
           "facts": len(e.facts or [])})
    if e.duplicate_of is not None:
        return _finish(db, wid, "done", steps, {"what_happened": e.title, "new_information": False}, "geen (duplicaat)", 0.0)

    # 6 · Social Intelligence
    from nexus import social
    tags = {t.symbol: t.cashtag for t in social.WATCHLIST}
    soc = {"status": "not_applicable", "detail": "geen meme-instrument betrokken"}
    rel_tags = [tags[a] for a in (e.assets or []) if a in tags]
    if rel_tags:
        with db.session() as s:
            snap = s.scalars(select(SocialSnapshot).where(SocialSnapshot.topic.in_([f"${t}" for t in rel_tags]))
                             .order_by(SocialSnapshot.id.desc())).first()
        soc = ({"status": "ok", "topic": snap.topic, "at": snap.created_at.isoformat(),
                "mentions_per_hour": snap.metrics.get("mentions_per_hour"), "bot_risk": snap.metrics.get("bot_risk")}
               if snap else {"status": "unavailable", "detail": social.x_status()["detail"]})
    _step(steps, "social", "social", soc["status"], soc)

    # 7 · Market Data
    ctx_rows = {}
    data = ctx.get("data")
    for a in (e.assets or [])[:3]:
        c = data.raw(a, "1d") if data is not None else []
        if c:
            ctx_rows[a] = market_context(c, pub, fetched)
    _step(steps, "market", "regime", "ok" if ctx_rows else "unavailable",
          ctx_rows or {"detail": "geen koersdata voor de betrokken instrumenten"})

    # 8-10 · onderzoeker, uitdager, quant (via het bestaande debat)
    opp = news.opportunity(e.category, news.event_study(db))
    quant = {"status": {"candidate": "inconclusive", "no_edge": "rejected"}.get(opp["status"], "open"),
             "result": {"opportunity": opp["status"], "reason": opp["reason"]}}
    gw = ctx.get("gateway")
    if gw is not None and _ai_today(db, now) < ai_per_day():
        from nexus import debate
        facts = [{"id": f"news:{e.id}", "text": f"{e.source} ({pub.date()}): {e.title}"}]
        facts += [{"id": f"news:{e.id}:fact:{i}", "text": f} for i, f in enumerate(e.facts or [])]
        facts += [{"id": f"market:{a}:context", "text": str(m)} for a, m in ctx_rows.items()]
        facts.append({"id": f"study:{e.category}", "text": f"event study: {opp['status']} ({opp['reason']})"})
        d = debate.run(db, gw, f"Gevolgen van: {e.title[:150]}", facts, quant, ref=trace, now=now)
        cost += d["cost_usd"]
        for st in d["steps"]:
            if st["step"] in ("research", "challenge"):
                _step(steps, st["step"], "crypto" if st["step"] == "research" else "auditor",
                      "ok" if st.get("by") else "unavailable",
                      {"provider": st.get("by"), "model": st.get("model"), "debate": d["id"],
                       "trail": st.get("trail")})
        for name, agent in (("research", "crypto"), ("challenge", "auditor")):
            if not any(x["step"] == name for x in steps):
                _step(steps, name, agent, "unavailable", {"debate": d["id"], "reason": "geen (tweede) aanbieder beschikbaar"})
        ai_summary = d["summary"]
    else:
        reason = "AI Gateway niet beschikbaar" if gw is None else "daglimiet AI-workflows bereikt"
        _step(steps, "research", "crypto", "skipped", {"reason": reason})
        _step(steps, "challenge", "auditor", "skipped", {"reason": reason})
        ai_summary = None
    _step(steps, "quant", "quant", "ok", {"opportunity": opp})

    # 11 · Risk Guardian
    _step(steps, "risk", "risk", "ok",
          {"decision": "alleen onderzoek", "order": None,
           "rule": "nieuws leidt nooit direct tot een order; limieten en live-status veranderen niet"})

    # 12 · NEXUS Central + Copilot-uitleg
    intel = intelligence(e, ctx_rows, opp, soc)
    prio = priority(e, opp)
    _step(steps, "central", "cio", "ok", {"research_priority": prio, "trade_recommendation": None,
                                          "ai_summary": (ai_summary or {}).get("recommendation")})
    explain = (f"{e.source} meldde: {e.title}. Betrokken: {', '.join(e.assets or []) or 'geen'}. "
               f"{intel['confirmed'].capitalize()}. Onderzoeksprioriteit {prio}; dit is geen handelsadvies. "
               f"Ontbreekt: {'; '.join(intel['missing'])}.")
    _step(steps, "explain", "cio", "ok", {"text": explain})
    status = "done" if all(s["status"] in ("ok", "duplicate", "not_applicable", "warning") for s in steps) else "partial"
    return _finish(db, wid, status, steps, {**intel, "research_priority": prio}, prio, cost)


def _ai_today(db: Database, now: datetime) -> int:
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    with db.session() as s:
        rows = s.scalars(select(EventWorkflow).where(EventWorkflow.created_at >= day)).all()
    return sum(1 for w in rows if any(st["step"] == "research" and st["status"] == "ok" for st in (w.steps or [])))


def _finish(db, wid, status, steps, intel, prio, cost) -> dict:
    with db.session.begin() as s:
        w = s.get(EventWorkflow, wid)
        w.status, w.steps, w.intelligence, w.cost_usd, w.finished_at = status, steps, intel, cost, datetime.now(tz=UTC)
        db.audit("central", "event_workflow", {"trace": w.trace_id, "status": status, "priority": prio}, s=s)
    return get(db, wid)


def get(db: Database, wid: int) -> dict:
    with db.session() as s:
        w = s.get(EventWorkflow, wid)
        if w is None:
            raise KeyError(wid)
        e = s.get(NewsEvent, w.news_id)
        return {"id": w.id, "trace_id": w.trace_id, "news_id": w.news_id, "status": w.status, "simulated": w.simulated,
                "source": e.source, "title": e.title, "url": e.url,
                "published_at": _utc(e.published_at).isoformat(), "detected_at": _utc(e.fetched_at).isoformat(),
                "intelligence": w.intelligence, "steps": w.steps, "cost_usd": float(w.cost_usd or 0),
                "created_at": _utc(w.created_at).isoformat(),
                "finished_at": _utc(w.finished_at).isoformat() if w.finished_at else None}


def recent(db: Database, limit: int = 30) -> list[dict]:
    with db.session() as s:
        ids = s.scalars(select(EventWorkflow.id).order_by(EventWorkflow.id.desc()).limit(limit)).all()
    return [get(db, i) for i in ids]


def pending(db: Database, limit: int = MAX_PER_RUN) -> list[int]:
    """Signaal-gebeurtenissen zonder workflow, belangrijkste eerst. Begrensd per run."""
    with db.session() as s:
        done = set(s.scalars(select(EventWorkflow.news_id)))
        rows = s.scalars(select(NewsEvent).where(NewsEvent.relevance >= news.SIGNAL_THRESHOLD,
                                                 NewsEvent.duplicate_of.is_(None))
                         .order_by(NewsEvent.relevance.desc(), NewsEvent.published_at.desc()).limit(200)).all()
        return [e.id for e in rows if e.id not in done][:limit]


def count(db: Database) -> int:
    with db.session() as s:
        return s.scalar(select(func.count()).select_from(EventWorkflow)) or 0

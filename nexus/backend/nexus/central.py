"""NEXUS Central: de coördinerende laag boven alle afdelingen.

Wat Central doet:
- uit echte gebeurtenissen taken maken (nieuws boven de drempel, open hypothesen, kandidaat-modellen,
  mislukte taken, onenigheid in de Council);
- taken één voor één uitvoeren met expliciete statusovergangen en een geschiedenis per taak;
- beslissingen die bij de mens horen escaleren naar de CEO (promoties, mislukte systemen);
- een dagelijkse CEO-briefing en een beslissingstijdlijn opbouwen uit wat er echt gebeurd is.

Wat Central niet doet: vrije agent-lussen, orders plaatsen, risicolimieten wijzigen of modellen
promoveren. Per ronde is het aantal taken en AI-aanroepen begrensd.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from nexus import council, news
from nexus.db import (
    AgentForecast,
    Briefing,
    CouncilRun,
    Database,
    DecisionRecord,
    Execution,
    Hypothesis,
    JobRun,
    ModelVersion,
    NewsEvent,
    OrchestratorTask,
    Order,
    ResearchRun,
    RiskEvaluation,
    TokenCheck,
    TradeProposal,
    utcnow,
)

log = logging.getLogger("nexus.central")

# ── Organisatie ────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Role:
    key: str
    name: str
    department: str
    kind: str              # human, coordinator, llm, deterministic
    backed_by: str         # welk stuk code het werk echt doet


DEPARTMENTS = {
    "leadership": "Leiding",
    "research": "Research",
    "intelligence": "Market Intelligence",
    "operations": "Trading Operations",
    "risk": "Risk & Oversight",
    "learning": "Learning",
}
ROLES = [
    Role("ceo", "Founder / CEO", "leadership", "human", "goedkeuringen, noodstop, limieten"),
    Role("cio", "NEXUS Central (CIO)", "leadership", "coordinator", "nexus.central + Council-besluit"),
    Role("quant", "Quantitative Researcher", "research", "deterministic", "nexus.champion + nexus.alpha"),
    Role("technical", "Technical Analyst", "research", "llm", "Council (Claude)"),
    Role("fundamental", "Fundamental Analyst", "research", "llm", "Council (Claude)"),
    Role("evolution", "Strategy Evolution Scientist", "research", "llm", "Council (Claude) + nexus.evolution"),
    Role("news", "News Analyst", "intelligence", "llm", "nexus.news (News Reactor) + Council"),
    Role("macro", "Macro Economist", "intelligence", "llm", "Council (Claude)"),
    Role("crypto", "Crypto Analyst", "intelligence", "llm", "Council (Claude)"),
    Role("meme", "Meme Coin Specialist", "intelligence", "llm", "Council (Claude) + nexus.social"),
    Role("social", "Social Intelligence Analyst", "intelligence", "deterministic", "nexus.social (X + on-chain)"),
    Role("execution", "Execution Specialist", "operations", "deterministic", "nexus.paper (alleen paper)"),
    Role("portfolio", "Portfolio Manager", "operations", "llm", "Council (Claude)"),
    Role("regime", "Market Regime Specialist", "operations", "llm", "Council (Claude) + regime-regels"),
    Role("risk", "Risk Guardian", "risk", "deterministic", "nexus.guardian (veto)"),
    Role("auditor", "Strategy Auditor", "risk", "deterministic", "nexus.audit + Council-bewijscontrole"),
    Role("security", "Security & Compliance", "risk", "deterministic", "hash-keten auditlog, live-poort"),
    Role("model_eval", "Model & Agent Evaluation", "learning", "deterministic", "Council-scorecard (Brier)"),
    Role("experiments", "Experiment Tracking", "learning", "deterministic", "holdout-register + hypothesen"),
]
ROLE = {r.key: r for r in ROLES}

# ── Statusmachine ──────────────────────────────────────────────────────────────────────────
TRANSITIONS = {
    "queued": {"running", "cancelled", "escalated"},
    "running": {"done", "failed", "escalated"},
    "escalated": {"done", "cancelled"},
    "failed": {"queued"},
    "done": set(),
    "cancelled": set(),
}
OPEN = ("queued", "running", "escalated")
MAX_TASKS_PER_STEP = 10
MAX_AI_TASKS_PER_DAY = 3


class InvalidTransition(Exception):
    pass


def move(t: OrchestratorTask, new: str, note: str = "") -> None:
    if new not in TRANSITIONS.get(t.status, set()):
        raise InvalidTransition(f"{t.status} → {new} is niet toegestaan")
    t.history = [*(t.history or []), {"from": t.status, "to": new, "at": utcnow().isoformat(), "note": note}]
    t.status, t.updated_at = new, utcnow()


def enqueue(db: Database, kind: str, agent: str, reason: str, subject: str | None = None,
            source_ref: str | None = None, payload: dict | None = None, priority: int = 50,
            status: str = "queued") -> int | None:
    """Maakt een taak, tenzij er al een open (of vandaag afgeronde) taak voor dezelfde bron bestaat."""
    with db.session.begin() as s:
        if source_ref:
            dup = s.scalar(select(OrchestratorTask.id).where(OrchestratorTask.kind == kind,
                                                            OrchestratorTask.source_ref == source_ref))
            if dup:
                return None
        t = OrchestratorTask(kind=kind, department=ROLE[agent].department, agent=agent, status=status,
                             priority=priority, subject=subject, source_ref=source_ref, reason=reason,
                             payload=payload or {},
                             history=[{"from": None, "to": status, "at": utcnow().isoformat(), "note": reason}])
        s.add(t)
        s.flush()
        db.audit("central", "task_created", {"task": t.id, "kind": kind, "agent": agent, "status": status,
                                             "source": source_ref}, s=s)
        return t.id


# ── Plannen: van gebeurtenis naar taak ──────────────────────────────────────────────────────
def plan(db: Database, ctx: dict | None = None, now: datetime | None = None) -> list[int]:
    now = now or datetime.now(tz=UTC)
    ctx = ctx or {}
    made: list[int | None] = []
    council_syms = set(ctx.get("council_symbols") or ())
    with db.session() as s:
        evs = s.scalars(select(NewsEvent).where(NewsEvent.relevance >= news.SIGNAL_THRESHOLD,
                                                NewsEvent.duplicate_of.is_(None),
                                                NewsEvent.published_at >= now - timedelta(days=2))
                        .order_by(NewsEvent.relevance.desc()).limit(20)).all()
        hyps = s.scalars(select(Hypothesis).where(Hypothesis.status == "open")).all()
        cands = s.scalars(select(ModelVersion).where(ModelVersion.status == "candidate")).all()
        failed = s.scalars(select(JobRun).where(JobRun.status == "failed",
                                                JobRun.started_at >= now - timedelta(days=1))).all()
        runs = s.scalars(select(CouncilRun).where(CouncilRun.status == "done",
                                                  CouncilRun.created_at >= now - timedelta(days=2))).all()
        unsafe = s.scalars(select(TokenCheck).where(TokenCheck.status == "fail",
                                                    TokenCheck.checked_at >= now - timedelta(days=1))).all()
    for e in evs:
        made.append(enqueue(db, "news_review", "news", f"{e.category}: {e.title[:120]}", subject=(e.assets or [None])[0],
                            source_ref=f"news:{e.id}", payload={"news_id": e.id, "assets": e.assets,
                                                                "relevance": e.relevance},
                            priority=int(100 * (e.relevance or 0))))
    for h in hyps:
        made.append(enqueue(db, "hypothesis_test", "experiments", f"hypothese #{h.id} toetsen: {h.title[:120]}",
                            subject=(h.test or {}).get("symbol"), source_ref=f"hypothesis:{h.id}",
                            payload={"hypothesis_id": h.id}, priority=40))
    for m in cands:
        made.append(enqueue(db, "approval", "ceo", f"kandidaat {m.key} v{m.version}: beslissen over paper-test",
                            subject=(m.symbols or [None])[0], source_ref=f"model:{m.id}",
                            payload={"model_id": m.id}, priority=70, status="escalated"))
    for j in failed:
        made.append(enqueue(db, "system_issue", "security", f"taak {j.job} mislukt: {(j.detail or {}).get('error', '')[:120]}",
                            source_ref=f"job:{j.id}", payload={"job_run": j.id}, priority=80, status="escalated"))
    for r in runs:
        stances = {d.get("agent"): council._dir(d.get("stance", "")) for d in (r.debate or [])}
        dirs = {v for v in stances.values() if v != 0}
        if len(dirs) > 1:
            made.append(enqueue(db, "disagreement", "auditor", f"Council verdeeld over {r.symbol}",
                                subject=r.symbol, source_ref=f"council:{r.id}",
                                payload={"run_id": r.id, "stances": stances}, priority=55, status="escalated"))
    for t in unsafe:
        made.append(enqueue(db, "safety_block", "social", f"token {t.symbol or t.address[:10]} zakt voor veiligheidscontrole",
                            subject=t.symbol, source_ref=f"token:{t.id}", payload={"token_check": t.id}, priority=60,
                            status="done"))
    # Een Council-review alleen voor ingestelde instrumenten, en hooguit een paar per dag.
    if council_syms:
        with db.session() as s:
            today = s.scalar(select(func.count(OrchestratorTask.id)).where(
                OrchestratorTask.kind == "council_review", OrchestratorTask.created_at >= now - timedelta(days=1))) or 0
        for e in evs:
            if today >= MAX_AI_TASKS_PER_DAY:
                break
            sym = next((a for a in e.assets or [] if a in council_syms), None)
            if sym:
                tid = enqueue(db, "council_review", "cio", f"Council over {sym} na nieuws: {e.title[:100]}",
                              subject=sym, source_ref=f"council-news:{e.id}", payload={"news_id": e.id}, priority=65)
                if tid:
                    today += 1
                made.append(tid)
    return [m for m in made if m]


# ── Uitvoeren ───────────────────────────────────────────────────────────────────────────────
def _h_news_review(db: Database, t: OrchestratorTask, ctx: dict) -> dict:
    from nexus import workflow
    nid = t.payload["news_id"]
    with db.session.begin() as s:
        e = s.get(NewsEvent, nid)
        e.signal_at = e.signal_at or utcnow()
    w = workflow.run(db, ctx, nid)            # de hele keten: sociaal, markt, debat, quant, risico, samenvatting
    return {"news_id": nid, "trace_id": w["trace_id"], "workflow": w["status"],
            "research_priority": w["intelligence"].get("research_priority"), "cost_usd": w["cost_usd"],
            "note": "onderzoekssignaal, geen handelssignaal: de Council en de Risk Guardian beslissen daarna"}


def _h_hypothesis(db: Database, t: OrchestratorTask, ctx: dict) -> dict:
    from nexus import evolution
    if ctx.get("data") is None:
        raise RuntimeError("geen onderzoeksdata beschikbaar")
    r = evolution.test_hypothesis(db, ctx["data"], t.payload["hypothesis_id"])
    return {"status": r["status"], "best": r.get("best"), "p_better_than_baseline": r.get("p_better_than_baseline")}


def _h_council(db: Database, t: OrchestratorTask, ctx: dict) -> dict:
    data = ctx.get("data")
    if data is None:
        raise RuntimeError("geen onderzoeksdata beschikbaar")
    from nexus.datasets import universe
    inst = next(i for i in universe(data.config) if i.symbol == t.subject)
    r = council.convene(db, t.subject, inst.asset_class.value, data.load(inst, "1d").candles,
                        client=ctx.get("council_client"))
    return {"run_id": r["id"], "status": r["status"], "action": (r.get("decision") or {}).get("action"),
            "cost_usd": r["cost_usd"], "error": r.get("error")}


HANDLERS = {"news_review": _h_news_review, "hypothesis_test": _h_hypothesis, "council_review": _h_council}


def run(db: Database, ctx: dict | None = None, limit: int = MAX_TASKS_PER_STEP) -> list[dict]:
    ctx = ctx or {}
    with db.session() as s:
        ids = [t.id for t in s.scalars(select(OrchestratorTask).where(OrchestratorTask.status == "queued",
                                                                     OrchestratorTask.kind.in_(HANDLERS))
                                       .order_by(OrchestratorTask.priority.desc(), OrchestratorTask.id).limit(limit))]
    out = []
    for tid in ids:
        with db.session.begin() as s:
            t = s.get(OrchestratorTask, tid)
            move(t, "running")
        with db.session() as s:
            t = s.get(OrchestratorTask, tid)
        try:
            res = HANDLERS[t.kind](db, t, ctx)
            new, err = "done", None
            if t.kind == "council_review" and res.get("status") != "done":
                new = "escalated" if res.get("status") == "failed" else "done"
        except Exception as e:
            log.exception("taak %s mislukt", tid)
            res, new, err = {}, "failed", str(e)[:500]
        with db.session.begin() as s:
            t = s.get(OrchestratorTask, tid)
            t.result, t.error, t.cost_usd = res, err, float(res.get("cost_usd") or 0)
            move(t, new, err or "")
            db.audit("central", "task_finished", {"task": tid, "kind": t.kind, "status": new}, s=s)
        out.append({"id": tid, "kind": t.kind, "status": new, "error": err})
    return out


def resolve_approvals(db: Database) -> int:
    """Escalaties die de mens al via een andere weg afhandelde (model gepromoveerd/afgewezen) sluiten."""
    n = 0
    with db.session.begin() as s:
        for t in s.scalars(select(OrchestratorTask).where(OrchestratorTask.kind == "approval",
                                                          OrchestratorTask.status == "escalated")):
            m = s.get(ModelVersion, t.payload.get("model_id"))
            if m is None or m.status != "candidate":
                move(t, "done", f"model nu {m.status if m else 'verwijderd'}")
                n += 1
    return n


def decide(db: Database, tid: int, actor: str, decision: str, note: str) -> dict:
    """De CEO sluit een escalatie (gezien/afgehandeld of geannuleerd). Geen handelsactie."""
    with db.session.begin() as s:
        t = s.get(OrchestratorTask, tid)
        if t is None:
            raise KeyError(tid)
        move(t, "done" if decision == "acknowledge" else "cancelled", f"{actor}: {note}")
        db.audit(actor, "task_decided", {"task": tid, "decision": decision, "note": note}, s=s)
        return {"id": tid, "status": t.status}


def step(db: Database, ctx: dict | None = None) -> dict:
    created = plan(db, ctx)
    closed = resolve_approvals(db)
    done = run(db, ctx)
    return {"created": len(created), "closed_approvals": closed, "ran": done}


def tasks(db: Database, status: str | None = None, limit: int = 100) -> list[dict]:
    with db.session() as s:
        q = select(OrchestratorTask).order_by(OrchestratorTask.id.desc()).limit(limit)
        if status:
            q = q.where(OrchestratorTask.status == status)
        return [_task(t) for t in s.scalars(q)]


def _task(t: OrchestratorTask) -> dict:
    return {"id": t.id, "kind": t.kind, "department": t.department, "agent": t.agent, "status": t.status,
            "priority": t.priority, "subject": t.subject, "source_ref": t.source_ref, "reason": t.reason,
            "result": t.result, "error": t.error, "history": t.history, "cost_usd": t.cost_usd,
            "created_at": _iso(t.created_at), "updated_at": _iso(t.updated_at)}


def _iso(d):
    return None if d is None else (d if d.tzinfo else d.replace(tzinfo=UTC)).isoformat()


# ── Organisatie-overzicht met echte activiteit ─────────────────────────────────────────────
def organization(db: Database) -> list[dict]:
    with db.session() as s:
        last_fc = dict(s.execute(select(AgentForecast.agent, func.max(AgentForecast.ts)).group_by(AgentForecast.agent)).all())
        nfc = dict(s.execute(select(AgentForecast.agent, func.count(AgentForecast.id)).group_by(AgentForecast.agent)).all())
        last_run = s.scalar(select(func.max(CouncilRun.created_at)).where(CouncilRun.status == "done"))
        task_rows = s.scalars(select(OrchestratorTask).order_by(OrchestratorTask.id.desc()).limit(500)).all()
        sources = {
            "news": s.scalar(select(func.max(NewsEvent.fetched_at))),
            "risk": s.scalar(select(func.max(RiskEvaluation.ts))),
            "execution": s.scalar(select(func.max(Execution.ts))),
            "experiments": s.scalar(select(func.max(Hypothesis.created_at))),
            "quant": s.scalar(select(func.max(ResearchRun.created_at))),
            "model_eval": s.scalar(select(func.max(AgentForecast.resolved_at))),
            "social": s.scalar(select(func.max(TokenCheck.checked_at))),
            "security": s.scalar(select(func.max(JobRun.started_at)).where(JobRun.job == "security")),
            "cio": s.scalar(select(func.max(OrchestratorTask.updated_at))),
        }
    by_agent: dict[str, list[OrchestratorTask]] = {}
    for t in task_rows:
        by_agent.setdefault(t.agent, []).append(t)
    out = []
    for r in ROLES:
        ts = [x for x in (sources.get(r.key), last_fc.get(r.key), last_run if r.kind == "llm" else None) if x]
        mine = by_agent.get(r.key, [])
        out.append({"key": r.key, "name": r.name, "department": r.department, "department_name": DEPARTMENTS[r.department],
                    "kind": r.kind, "backed_by": r.backed_by,
                    "last_activity": _iso(max((x if x.tzinfo else x.replace(tzinfo=UTC)) for x in ts)) if ts else None,
                    "forecasts": nfc.get(r.key, 0),
                    "open_tasks": [_task(t) for t in mine if t.status in OPEN][:10],
                    "recent_tasks": [_task(t) for t in mine if t.status not in OPEN][:10],
                    "errors": [_task(t) for t in mine if t.status == "failed"][:5]})
    return out


# ── Beslissingstijdlijn ─────────────────────────────────────────────────────────────────────
STAGES = ["market_event", "intelligence", "quant", "debate", "risk_review", "proposal", "execution", "outcome", "learning"]


def timeline(db: Database, limit: int = 15) -> list[dict]:
    """Per episode (Council-run of handelsvoorstel) welke stappen echt gebeurd zijn, met verwijzing."""
    eps = []
    with db.session() as s:
        props = s.scalars(select(TradeProposal).order_by(TradeProposal.id.desc()).limit(limit)).all()
        runs = s.scalars(select(CouncilRun).order_by(CouncilRun.id.desc()).limit(limit)).all()

        def news_before(sym, t):
            t = t if t.tzinfo else t.replace(tzinfo=UTC)
            for e in s.scalars(select(NewsEvent).where(NewsEvent.published_at <= t,
                                                       NewsEvent.published_at >= t - timedelta(hours=48))
                               .order_by(NewsEvent.published_at.desc()).limit(50)):
                if sym in (e.assets or []):
                    return e
            return None

        def stage(key, status, ts=None, ref=None, detail=""):
            return {"stage": key, "status": status, "at": _iso(ts), "ref": ref, "detail": detail}

        for r in runs:
            e = news_before(r.symbol, r.created_at)
            st = [stage("market_event", "done" if e else "none", e.published_at if e else None,
                        f"news:{e.id}" if e else None, e.title[:120] if e else "geen nieuws binnen 48 uur"),
                  stage("intelligence", "done" if r.independent else r.status, r.created_at, f"council:{r.id}",
                        f"{len(r.independent or [])} onafhankelijke oordelen"),
                  stage("quant", "done" if (r.inputs or {}).get("context", {}).get("research") else "none",
                        r.created_at, f"council:{r.id}", "arena-resultaat als context"),
                  stage("debate", "done" if r.debate else r.status, r.created_at, f"council:{r.id}",
                        (r.decision or {}).get("action") or (r.error or "")),
                  stage("risk_review", "pending", None, None, "pas bij een concreet voorstel"),
                  stage("proposal", "none", None, None, "de Council plaatst geen orders")]
            st += [stage(k, "none") for k in ("execution", "outcome", "learning")]
            eps.append({"kind": "council", "id": r.id, "symbol": r.symbol, "at": _iso(r.created_at), "stages": st})
        for p in props:
            ev = s.scalars(select(RiskEvaluation).where(RiskEvaluation.proposal_id == p.id)).first()
            od = s.scalars(select(Order).where(Order.proposal_id == p.id)).first()
            ex = s.scalars(select(Execution).where(Execution.order_id == od.id)).first() if od else None
            dr = s.scalars(select(DecisionRecord).where(DecisionRecord.dedupe_key == f"nexus:proposal:{p.id}")).first()
            e = news_before(p.symbol, p.created_at)
            cr = s.scalars(select(CouncilRun).where(CouncilRun.symbol == p.symbol, CouncilRun.created_at <= p.created_at)
                           .order_by(CouncilRun.id.desc())).first()
            st = [stage("market_event", "done" if e else "none", e.published_at if e else None,
                        f"news:{e.id}" if e else None, e.title[:120] if e else ""),
                  stage("intelligence", "done" if cr else "none", cr.created_at if cr else None,
                        f"council:{cr.id}" if cr else None),
                  stage("quant", "done", p.created_at, f"proposal:{p.id}", f"strategie {p.strategy_id}"),
                  stage("debate", "done" if cr and cr.debate else "none", cr.created_at if cr else None,
                        f"council:{cr.id}" if cr else None),
                  stage("risk_review", ("approved" if ev.approved else "vetoed") if ev else "pending",
                        ev.ts if ev else None, f"risk:{ev.id}" if ev else None, ev.reason[:160] if ev else ""),
                  stage("proposal", "done", p.created_at, f"proposal:{p.id}", f"{p.direction} {p.symbol}"),
                  stage("execution", ("filled" if ex else od.status) if od else "none", ex.ts if ex else None,
                        f"order:{od.id}" if od else None, "paper" if od else ""),
                  stage("outcome", "done" if dr and dr.outcome else "pending", dr.outcome_at if dr else None,
                        f"decision:{dr.id}" if dr else None,
                        f"20 d: {(dr.outcome or {}).get('fwd_20', 0):+.1%}" if dr and dr.outcome else ""),
                  stage("learning", "done" if dr and dr.error_tags else "none", None,
                        f"decision:{dr.id}" if dr else None, ", ".join(dr.error_tags or []) if dr else "")]
            eps.append({"kind": "proposal", "id": p.id, "symbol": p.symbol, "at": _iso(p.created_at), "stages": st})
    eps.sort(key=lambda x: x["at"] or "", reverse=True)
    return eps[:limit]


# ── CEO-briefing ────────────────────────────────────────────────────────────────────────────
def briefing(db: Database, ctx: dict | None = None, now: datetime | None = None, save: bool = True) -> dict:
    """Dagelijkse briefing uit echte data. Wat ontbreekt staat onder ``missing``."""
    ctx = ctx or {}
    now = now or datetime.now(tz=UTC)
    day_ago, week_ago = now - timedelta(days=1), now - timedelta(days=7)
    missing: list[str] = []
    out: dict = {"day": now.date().isoformat(), "generated_at": now.isoformat()}

    paper = ctx.get("paper")
    if paper is not None:
        try:
            v = paper.valuation()
            out["portfolio"] = {"label": "SIMULATED", "equity_eur": v["equity_eur"], "pnl_eur": v["pnl_eur"],
                                "realized_eur": v.get("realized_eur"), "positions": len(v.get("positions", []))}
        except Exception as e:  # noqa: BLE001
            missing.append(f"paper-portefeuille niet te waarderen: {e}")
    else:
        missing.append("paper-portefeuille niet gekoppeld")

    with db.session() as s:
        evs = s.scalars(select(NewsEvent).where(NewsEvent.published_at >= day_ago, NewsEvent.duplicate_of.is_(None))
                        .order_by(NewsEvent.relevance.desc()).limit(5)).all()
        out["news"] = [{"id": e.id, "title": e.title, "source": e.source, "category": e.category,
                        "relevance": e.relevance, "factuality": e.factuality, "url": e.url} for e in evs]
        if not evs:
            missing.append("geen nieuws in de laatste 24 uur (bron niet bereikbaar of niets gepubliceerd)")
        n_exec = s.scalar(select(func.count(Execution.id)).where(Execution.ts >= day_ago)) or 0
        n_veto = s.scalar(select(func.count(RiskEvaluation.id)).where(RiskEvaluation.ts >= day_ago,
                                                                     RiskEvaluation.approved.is_(False))) or 0
        n_prop = s.scalar(select(func.count(TradeProposal.id)).where(TradeProposal.created_at >= day_ago)) or 0
        out["trading"] = {"label": "SIMULATED", "proposals": n_prop, "vetoes": n_veto, "fills": n_exec,
                          "live_trading": False}
        arena = s.scalars(select(ResearchRun).where(ResearchRun.kind == "arena").order_by(ResearchRun.id.desc())).first()
        if arena:
            rep = arena.report or {}
            out["research"] = {"label": "ESTIMATE", "symbol": rep.get("symbol"), "at": _iso(arena.created_at),
                               "champion_sharpe": ((rep.get("champion") or {}).get("walk_forward") or {}).get("sharpe"),
                               "buy_hold_sharpe": (rep.get("buy_hold") or {}).get("sharpe"),
                               "passed_dev_gates": rep.get("passed_dev_gates", []),
                               "holdout": (rep.get("holdout_governance") or {}).get("status")}
        else:
            missing.append("nog geen arena-run")
        res = s.scalars(select(Hypothesis).where(Hypothesis.resolved_at >= week_ago)).all()
        out["learning"] = {"hypotheses_resolved_7d": len(res),
                           "supported": [h.title for h in res if h.status == "supported"],
                           "decisions_measured": s.scalar(select(func.count(DecisionRecord.id)).where(
                               DecisionRecord.outcome_at >= week_ago)) or 0}
        cruns = s.scalars(select(CouncilRun).where(CouncilRun.created_at >= day_ago)).all()
        out["ai"] = {"council_runs": len(cruns), "done": sum(1 for r in cruns if r.status == "done"),
                     "cost_usd": round(sum(r.cost_usd or 0 for r in cruns), 4),
                     "unavailable": sum(1 for r in cruns if r.status == "unavailable")}
        esc = s.scalars(select(OrchestratorTask).where(OrchestratorTask.status == "escalated")
                        .order_by(OrchestratorTask.priority.desc())).all()
        failed_jobs = s.scalars(select(JobRun).where(JobRun.status == "failed", JobRun.started_at >= day_ago)).all()
    actions = [{"task": t.id, "kind": t.kind, "text": t.reason} for t in esc[:8]]
    if out["ai"]["unavailable"]:
        actions.append({"kind": "setup", "text": "AI Council staat uit: zet ANTHROPIC_API_KEY op de server"})
    out["actions"] = actions
    out["system"] = {"failed_jobs_24h": [j.job for j in failed_jobs]}
    out["missing"] = missing
    if save:
        with db.session.begin() as s:
            s.add(Briefing(day=out["day"], content=_json(out)))
            db.audit("central", "briefing_created", {"day": out["day"], "actions": len(actions)}, s=s)
    return out


def latest_briefing(db: Database) -> dict | None:
    with db.session() as s:
        b = s.scalars(select(Briefing).order_by(Briefing.id.desc())).first()
        return b.content if b else None


def _json(x):
    import json
    return json.loads(json.dumps(x, default=str))

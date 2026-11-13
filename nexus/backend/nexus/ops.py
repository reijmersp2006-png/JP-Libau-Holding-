"""Operationele bewaking (Ascension 6.2): taken, wachtrij, versheid van data, AI-budget, stroomonderbrekers.

Elke waarschuwing komt uit een echte meting; er worden geen groene vinkjes getoond voor iets dat niet
gecontroleerd is."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from nexus import ai_gateway, jobs
from nexus.db import Database, OrchestratorTask

STALE_DAYS = {"1d": 4}


def _utc(d):
    return None if d is None else (d if d.tzinfo else d.replace(tzinfo=UTC))


def health(db: Database, ctx: dict, gateway: ai_gateway.Gateway, now: datetime | None = None) -> dict:
    now = now or datetime.now(tz=UTC)
    alerts: list[dict] = []
    job_rows = jobs.overview(db, jobs.JOBS)
    for j in job_rows:
        if j["last_status"] == "failed":
            alerts.append({"level": "high", "kind": "job_failed", "text": f"taak {j['job']} mislukte bij de laatste run",
                           "detail": (j["last_detail"] or {}).get("error")})
        elif j["last_started"] and _utc(datetime.fromisoformat(j["next_due"])) < now - timedelta(hours=6):
            alerts.append({"level": "medium", "kind": "job_overdue", "text": f"taak {j['job']} is achterstallig"})
    with db.session() as s:
        queue = dict(s.execute(select(OrchestratorTask.status, func.count()).group_by(OrchestratorTask.status)).all())
        oldest = s.scalar(select(func.min(OrchestratorTask.created_at)).where(OrchestratorTask.status == "queued"))
    if oldest and now - _utc(oldest) > timedelta(hours=6):
        alerts.append({"level": "medium", "kind": "queue_stale", "text": "er staan taken langer dan 6 uur in de wachtrij"})
    if queue.get("escalated"):
        alerts.append({"level": "info", "kind": "ceo", "text": f"{queue['escalated']} besluit(en) wachten op de CEO"})
    fresh = None
    data = ctx.get("data")
    if data is not None:
        from nexus.datasets import universe
        last = []
        for inst in universe(data.config):
            c = data.raw(inst.symbol, "1d")
            if c:
                last.append(_utc(c[-1].ts))
        if last:
            newest = max(last)
            age = (now - newest).total_seconds() / 86400
            fresh = {"newest_daily_bar": newest.isoformat(), "age_days": round(age, 2)}
            if age > STALE_DAYS["1d"]:
                alerts.append({"level": "high", "kind": "data_stale", "text": f"nieuwste dagkoers is {age:.1f} dagen oud"})
    breakers = [p for p in ai_gateway.CONF if gateway.breaker_open(p, now)]
    for p in breakers:
        alerts.append({"level": "high", "kind": "breaker", "text": f"stroomonderbreker open voor {p}"})
    budget = {"daily_budget_usd": None, "spent_today_usd": gateway.spent_today(now), "left_usd": gateway.budget_left(now)}
    from nexus import council
    budget["daily_budget_usd"] = council.daily_budget()
    budget["council_spent_today_usd"] = council.spent_today(db, now)
    if budget["left_usd"] <= 0:
        alerts.append({"level": "medium", "kind": "budget", "text": "AI-dagbudget is op; AI-taken worden overgeslagen"})
    audit = db.verify_audit_chain()
    if not audit["ok"]:
        alerts.append({"level": "high", "kind": "audit", "text": f"auditketen gebroken bij regel {audit['broken_at']}"})
    return {"generated_at": now.isoformat(), "alerts": alerts, "jobs": job_rows, "queue": queue,
            "data_freshness": fresh, "ai_budget": budget, "breakers_open": breakers, "audit_chain_ok": audit["ok"],
            "retry_policy": {"jobs": "volgende geplande run; geen herhaalde pogingen binnen één run",
                             "ai": f"volgende provider in het beleid; stroomonderbreker na {gateway.breaker_failures} fouten "
                                   f"binnen {gateway.breaker_minutes} min"}}

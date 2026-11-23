"""Master Prompt 8.0 (Unification): NEXUS leest de echte stand van JP-Libau Holding en maakt er een
controleerbaar onderzoeksrecord van. Alleen lezen.

    onderzoeksvraag → snapshot van de holding (``jplh.snapshot/v1``, gecontroleerd)
    → beschikbare marktdata uit dezelfde snapshot (koers, 24u, versheid)
    → bewijscontext (feiten met id, bron en tijd)
    → analyse in vaste code (gelabeld ``deterministic``; geen AI-tekst)
    → AI-stap: alleen een eerlijke status (NOT CONNECTED / NOT ENABLED); in 8.0 wordt geen model aangeroepen
    → opslag als ``ResearchWorkflow`` (mode ``operations``) + auditregel
    → op te vragen via ``/api/ops/research`` en te exporteren als ``nexus.records/v1`` voor Jarvis

Grenzen, in code:
- De holding is de enige bron van portefeuille- en risicostand. NEXUS rekent die niet na en houdt geen
  eigen kopie bij als waarheid; het bewaart alleen de snapshot-hash en de feiten die het gebruikte.
- Niets hier plaatst een order, wijzigt een limiet, heft een pauze op of raakt de noodstop.
- De holding-databases worden alleen-lezen geopend (SQLite ``mode=ro``) of er wordt een
  ``snapshot.json`` gelezen; er wordt nooit naar de holding-map geschreven.
- Een uitkomst is een onderzoeksprioriteit, geen handelsadvies.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from jplh.config import HoldingConfig, load_config
from jplh.contract import RECORDS_SCHEMA, SNAPSHOT_SCHEMA, operational_snapshot, validate_snapshot
from sqlalchemy import select

from nexus import ai_gateway
from nexus.db import Database, ResearchWorkflow

MODE = "operations"
GENERATOR = "deterministic:ops-v1"
SCOPES = ("holding", "crypto", "meme", "stocks", "metals", "fx")
SNAPSHOT_FILE = Path("site") / "snapshot.json"
_PATCH = threading.Lock()                       # open_desks wordt kort omgeleid naar de alleen-lezen opslag


class SnapshotError(RuntimeError):
    """Geen geldige, verifieerbare snapshot: het onderzoek stopt (BLOCKED) in plaats van te gokken."""


# ── 1. snapshot ophalen ─────────────────────────────────────────────────────────────────────

class _ReadOnlyStore:
    """Zoals ``jplh.store.Store``, maar via een alleen-lezen SQLite-verbinding: geen schema-aanmaak,
    geen schrijfacties. Een poging tot schrijven faalt in SQLite zelf (``attempt to write a readonly database``)."""

    def __new__(cls, path: Path):
        from jplh.store import Store
        obj = Store.__new__(Store)
        obj.db = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
        return obj


def build_from_home(home: Path, config: HoldingConfig | None = None, now: datetime | None = None) -> dict:
    """Bouwt ``jplh.snapshot/v1`` met de eigen code van de holding (``site.build_state``), met alle
    databases alleen-lezen geopend. Werkt op een kopie van de ``paper-data``-branch."""
    import jplh.desks as desks_mod
    from jplh.site import build_state

    home = Path(home)
    db = home / "data" / "holding.sqlite3"
    if not db.exists():
        raise SnapshotError(f"geen holding-database in {home}")
    cfg = config or load_config(None)
    now = now or datetime.now(tz=UTC)
    market = _ReadOnlyStore(db)
    with _PATCH:
        original = desks_mod.Store
        desks_mod.Store = _ReadOnlyStore           # open_desks opent de afdelingsboeken via Store
        try:
            desks = desks_mod.open_desks(cfg, home, market)
        finally:
            desks_mod.Store = original
    try:
        # Nep-koersen (bron 'demo') maken de hele snapshot SIMULATED, ook als de map er echt uitziet.
        demo = market.db.execute("SELECT 1 FROM candles WHERE source='demo' LIMIT 1").fetchone() is not None
        state = build_state(cfg, desks, market, home, now, demo=demo)
        return operational_snapshot(json.loads(json.dumps(state, default=str)), now)
    finally:
        for d in desks.values():
            d.holding.store.close()
        market.close()


def load(path: Path | None = None, home: Path | None = None, now: datetime | None = None) -> dict:
    """Snapshot uit een bestand (``site/snapshot.json`` zoals het dashboard hem publiceert) of uit de holding-map.
    Altijd gecontroleerd tegen het contract en de hash."""
    if path is None and home is not None and (Path(home) / SNAPSHOT_FILE).exists() \
            and not (Path(home) / "data" / "holding.sqlite3").exists():
        path = Path(home) / SNAPSHOT_FILE
    if path is not None:
        try:
            snap = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise SnapshotError(f"snapshot onleesbaar: {e}") from e
        origin = f"file:{Path(path).name}"
    elif home is not None:
        snap = build_from_home(Path(home), now=now)
        origin = "holding-db (alleen-lezen)"
    else:
        raise SnapshotError("geen bron: geef een snapshot-bestand of een holding-map")
    errs = validate_snapshot(snap)
    if errs:
        raise SnapshotError("snapshot afgekeurd: " + "; ".join(errs[:3]))
    snap = dict(snap)
    snap["_origin"] = origin
    return snap


def freshness(snap: dict, now: datetime, max_age_hours: float) -> dict:
    # Leeftijd van de data = laatste paper-ronde; zonder ronde het moment van opbouwen.
    gen = datetime.fromisoformat(snap["freshness"].get("last_round_at") or snap["generated_at"])
    gen = gen if gen.tzinfo else gen.replace(tzinfo=UTC)
    age_h = (now - gen).total_seconds() / 3600
    stale = snap["freshness"].get("stale_instruments") or []
    label = "SIMULATED" if snap["source"].get("demo") else ("DELAYED" if age_h <= max_age_hours else "STALE")
    return {"data_asof": gen.isoformat(), "age_hours": round(age_h, 2), "max_age_hours": max_age_hours,
            "label": label, "stale_instruments": stale}


# ── 2–5. bewijs en analyse ─────────────────────────────────────────────────────────────────

def _fact(fid: str, text: str, source: str, ts: str, values: dict | None = None) -> dict:
    return {"id": fid, "text": text, "source": source, "ts": ts, "values": values or {}}


def _p(x) -> str:
    return "onbekend" if x is None else f"{x * 100:+.1f}%".replace(".", ",")


def evidence(snap: dict, scope: str) -> list[dict]:
    ts = snap["freshness"].get("last_round_at") or snap["generated_at"]
    src = f"jplh.snapshot/v1 sha256:{snap['sha256'][:12]}"
    h = snap["holding"]
    facts = [_fact("F-holding", f"Holding: {_p(h['pnl_pct'])} sinds start, vasthouden {_p(h.get('benchmark_pct'))}, "
                                f"daling vanaf top {_p(-(h['drawdown'] or 0))}.", src, ts,
                   {k: h.get(k) for k in ("equity_eur", "pnl_pct", "benchmark_pct", "drawdown", "day_pnl_pct")})]
    lim = snap.get("limits") or {}
    if lim:
        facts.append(_fact("F-limits", f"Pauzegrens per afdeling: daling {_p(-(lim.get('max_drawdown_pct') or 0))}.", src, ts, lim))
    desks = [d for d in snap["desks"] if scope in ("holding", d["id"])]
    for d in desks:
        facts.append(_fact(f"F-desk-{d['id']}",
                           f"{d['name']}: {_p(d['pnl_pct'])}, vasthouden {_p(d.get('benchmark_pct'))}, "
                           f"daling {_p(-(d['drawdown'] or 0))}, {d.get('trades')} trades, "
                           f"€{(d.get('fees_eur') or 0):.2f} kosten" + (f", GEPAUZEERD ({d['paused_reason']})" if d["paused"] else ""),
                           src, ts, {k: d.get(k) for k in ("pnl_pct", "benchmark_pct", "drawdown", "paused", "fees_eur", "trades")}))
        for i in d["instruments"]:
            facts.append(_fact(f"F-px-{i['symbol']}", f"{i['symbol']}: {_p(i.get('change_24h'))} in 24 uur"
                               + ("" if i["fresh"] else " (koers niet vers)"), src, ts,
                               {"price_eur": i.get("price_eur"), "change_24h": i.get("change_24h"), "fresh": i["fresh"]}))
    ac = (snap.get("academy") or {}).get("live_7d")
    if ac:
        facts.append(_fact("F-academy", f"Academie 7 dagen: {ac.get('n')} metingen, effectief {ac.get('effective')}, "
                                        f"oordeel '{ac.get('verdict')}'.", src, ts, ac))
    for desk, a in ((snap.get("arena") or {}).get("desks") or {}).items():
        if scope not in ("holding", desk):
            continue
        b = a.get("best_challenger")
        if b:
            facts.append(_fact(f"F-arena-{desk}", f"Arena {desk}: beste uitdager '{b['name']}' {_p(b.get('return'))} "
                                                  f"tegen live {_p((a.get('live') or {}).get('return'))}; "
                                                  f"promotie klaar: {'ja' if a.get('promote_ready') else 'nee'}.", src, ts, a))
    for k, issue in enumerate((snap.get("health") or {}).get("issues") or []):
        facts.append(_fact(f"F-health-{k}", f"Gezondheid ({issue.get('level')}): {issue.get('text')}", src, ts))
    return facts


def analyse(snap: dict, scope: str, facts: list[dict], fresh: dict) -> dict:
    """Analyse in vaste code. Elke bevinding verwijst naar feiten-id's. Geen voorspelling van winst."""
    ids = {f["id"] for f in facts}
    findings: list[dict] = []
    desks = [d for d in snap["desks"] if scope in ("holding", d["id"])]

    def add(kind, text, ev, severity="info"):
        findings.append({"kind": kind, "severity": severity, "text": text, "evidence": [e for e in ev if e in ids]})

    h = snap["holding"]
    if scope == "holding" and h.get("benchmark_pct") is not None:
        gap = h["pnl_pct"] - h["benchmark_pct"]
        add("benchmark", f"De holding staat {_p(gap)} {'boven' if gap >= 0 else 'onder'} gewoon vasthouden.",
            ["F-holding"], "warn" if gap < 0 else "info")
    for d in desks:
        if d.get("benchmark_pct") is not None:
            gap = d["pnl_pct"] - d["benchmark_pct"]
            add("benchmark", f"{d['name']} staat {_p(gap)} {'boven' if gap >= 0 else 'onder'} vasthouden.",
                [f"F-desk-{d['id']}"], "warn" if gap < 0 else "info")
        if d["paused"]:
            add("risk", f"{d['name']} is gepauzeerd door de risicoregel. Hervatten is een CEO-besluit; "
                        "NEXUS kan en zal dat niet doen.", [f"F-desk-{d['id']}", "F-limits"], "alarm")
        else:
            lim = (snap.get("limits") or {}).get("max_drawdown_pct")
            if lim and d.get("drawdown") is not None and d["drawdown"] >= 0.7 * lim:
                add("risk", f"{d['name']} zit op {_p(-d['drawdown'])}, dicht bij de pauzegrens van {_p(-lim)}.",
                    [f"F-desk-{d['id']}", "F-limits"], "warn")
        if d.get("trades") and d.get("fees_eur") and d.get("capital_eur"):
            fee = d["fees_eur"] / d["capital_eur"]
            if fee > 0.005:
                add("costs", f"{d['name']}: kosten {fee * 100:.1f}% van het startkapitaal.".replace(".", ",", 1),
                    [f"F-desk-{d['id']}"], "warn")
    for desk, a in ((snap.get("arena") or {}).get("desks") or {}).items():
        if scope in ("holding", desk) and a.get("promote_ready"):
            add("research", f"Arena {desk}: een uitdager voldoet aan de promotie-eisen. Alleen de CEO beslist.",
                [f"F-arena-{desk}"], "warn")
    ac = (snap.get("academy") or {}).get("live_7d")
    if ac and ac.get("verdict"):
        add("evidence", f"Academie: oordeel '{ac['verdict']}'. Een hogere trefkans is geen bewijs van winst.",
            ["F-academy"])
    if fresh["label"] == "STALE":
        add("data", f"De snapshot is {fresh['age_hours']:.0f} uur oud (grens {fresh['max_age_hours']:.0f} uur): "
                    "conclusies wachten op verse data.", [], "alarm")
    in_scope = {i["symbol"] for d in desks for i in d["instruments"]}
    stale = [x for x in fresh["stale_instruments"] if x in in_scope]
    if stale:
        add("data", f"Niet-verse koersen: {', '.join(stale[:6])}.", [f"F-px-{x}" for x in stale], "warn")

    sev = {"alarm": 3, "warn": 2, "info": 1}
    worst = max((sev[f["severity"]] for f in findings), default=1)
    rec = {3: "escalate_to_ceo", 2: "monitor", 1: "no_further_research"}[worst]
    if fresh["label"] == "STALE":
        rec = "further_research"
    alarms = [f for f in findings if f["severity"] == "alarm"]
    summary = (alarms[0]["text"] if alarms else next((f["text"] for f in findings if f["severity"] == "warn"),
                                                       findings[0]["text"] if findings else "Geen bijzonderheden."))
    return {"findings": findings, "recommendation": rec, "summary": summary, "generator": GENERATOR,
            "not_trading_advice": True,
            "limits_of_analysis": ["vaste regels op de holding-stand; geen voorspelling van koersen of winst",
                                   "een trefkans of korte periode is geen bewijs van een voordeel"]}


def ai_status(gateway: ai_gateway.Gateway | None) -> dict:
    """Eerlijke AI-status zonder aanroep. In 8.0 wordt geen model gebruikt voor operationeel onderzoek."""
    usable = [p["provider"] for p in ai_gateway.describe() if p["usable"]]
    if not usable:
        return {"status": "NOT CONNECTED", "detail": "geen AI-aanbieder met sleutel en modelnaam ingesteld"}
    return {"status": "NOT ENABLED", "detail": f"aanbieder(s) {', '.join(usable)} ingesteld, maar AI-analyse van de "
                                               "holding-stand vraagt eerst CEO-akkoord op budget (Master Prompt 8.0)"}


# ── 6–8. opslaan en opvragen ───────────────────────────────────────────────────────────────

def run(db: Database, snap: dict, *, scope: str = "holding", question: str = "", requested_by: str = "ceo",
        gateway: ai_gateway.Gateway | None = None, max_age_hours: float = 3.0, now: datetime | None = None) -> dict:
    if scope not in SCOPES:
        raise ValueError(f"onbekende scope {scope!r}")
    now = now or datetime.now(tz=UTC)
    if snap.get("schema") != SNAPSHOT_SCHEMA:
        raise SnapshotError("geen jplh.snapshot/v1")
    t0 = now.isoformat()
    fresh = freshness(snap, now, max_age_hours)
    facts = evidence(snap, scope)
    result = analyse(snap, scope, facts, fresh)
    ai = ai_status(gateway)
    question = (question or f"Hoe staat {'de holding' if scope == 'holding' else scope} ervoor, en wat vraagt aandacht?")[:300]
    steps = [
        {"step": "request", "status": "done", "ts": t0, "detail": {"scope": scope, "question": question}},
        {"step": "snapshot", "status": "done", "ts": t0, "source": snap.get("_origin"),
         "detail": {"schema": snap["schema"], "sha256": snap["sha256"], "generated_at": snap["generated_at"],
                    "data_asof": fresh["data_asof"], "label": fresh["label"],
                    "age_hours": fresh["age_hours"]}},
        {"step": "market_data", "status": "done" if not fresh["stale_instruments"] else "partial", "ts": t0,
         "source": "jplh.snapshot/v1 (instrumenten)",
         "detail": {"instruments": snap["freshness"]["instruments"], "stale": fresh["stale_instruments"]}},
        {"step": "evidence", "status": "done", "ts": t0, "detail": {"facts": len(facts)}},
        {"step": "analysis", "status": "done", "ts": t0, "detail": {"generator": GENERATOR, "findings": len(result["findings"])}},
        {"step": "ai_analysis", "status": "blocked", "ts": t0, "detail": ai},
        {"step": "store", "status": "done", "ts": t0},
    ]
    conclusion = {**result, "scope": scope, "snapshot_sha256": snap["sha256"], "snapshot_generated_at": snap["generated_at"],
                  "data_label": fresh["label"], "data_asof": fresh["data_asof"], "facts": facts, "ai": ai, "live_trading": False}
    trace = f"ops-{now:%Y%m%d%H%M%S}-{secrets.token_hex(3)}"
    subject = "holding" if scope == "holding" else f"desk:{scope}"
    status = "partial" if fresh["label"] == "STALE" else "done"
    with db.session.begin() as s:
        wf = ResearchWorkflow(trace_id=trace, subject=subject, question=question, mode=MODE, requested_by=requested_by,
                              status=status, simulated=bool(snap["source"].get("demo")), steps=steps,
                              messages=[], conclusion=conclusion, cost_usd=0, max_cost_usd=0,
                              created_at=now, finished_at=now)
        s.add(wf)
        s.flush()
        db.audit(requested_by, "ops.research", {"trace_id": trace, "scope": scope, "snapshot_sha256": snap["sha256"],
                                                 "recommendation": result["recommendation"]}, s=s)
    return get(db, trace)


def _row(w: ResearchWorkflow) -> dict:
    c = w.conclusion or {}
    created = w.created_at if w.created_at.tzinfo else w.created_at.replace(tzinfo=UTC)
    return {"trace_id": w.trace_id, "subject": w.subject, "question": w.question, "status": w.status,
            "simulated": w.simulated, "created_at": created.isoformat(), "requested_by": w.requested_by,
            "generator": c.get("generator"), "summary": c.get("summary"), "recommendation": c.get("recommendation"),
            "snapshot_sha256": c.get("snapshot_sha256"), "snapshot_generated_at": c.get("snapshot_generated_at"),
            "data_label": c.get("data_label"), "data_asof": c.get("data_asof"), "ai_status": (c.get("ai") or {}).get("status"),
            "findings": c.get("findings") or [], "facts": c.get("facts") or [], "steps": w.steps or []}


def get(db: Database, trace: str) -> dict:
    with db.session() as s:
        w = s.scalars(select(ResearchWorkflow).where(ResearchWorkflow.trace_id == trace,
                                                     ResearchWorkflow.mode == MODE)).first()
        if w is None:
            raise KeyError(trace)
        return _row(w)


def recent(db: Database, limit: int = 20) -> list[dict]:
    with db.session() as s:
        rows = s.scalars(select(ResearchWorkflow).where(ResearchWorkflow.mode == MODE)
                         .order_by(ResearchWorkflow.id.desc()).limit(limit)).all()
        return [_row(w) for w in rows]


def export(db: Database, now: datetime | None = None, limit: int = 10) -> dict:
    """``nexus.records/v1``: compacte records voor Jarvis (zonder ruwe feiten)."""
    now = now or datetime.now(tz=UTC)
    keep = ("trace_id", "subject", "created_at", "status", "generator", "snapshot_sha256", "summary",
            "recommendation", "data_label", "ai_status")
    return {"schema": RECORDS_SCHEMA, "exported_at": now.isoformat(),
            "items": [{k: r[k] for k in keep} for r in recent(db, limit)]}


def max_age_hours(config: HoldingConfig | None = None) -> float:
    cfg = config or load_config(None)
    return float(cfg.risk.max_data_age_hours)


__all__ = ["SCOPES", "SnapshotError", "load", "build_from_home", "freshness", "evidence", "analyse", "run", "get",
           "recent", "export", "ai_status", "max_age_hours"]

"""E1.4: helpt complexiteit? Vier varianten op dezelfde vragen, plus een toets van de uitdager zelf.

1. ``challenger_benchmark``: bevroren set analyses met geplante fouten (en schone controles). Meet of de vaste
   controles van de uitdager de fouten vinden. **Synthetisch en door de ontwikkelaar geschreven**: dit toetst het
   mechaniek van de controles, niet hoe goed fouten in echte modeluitvoer gevonden worden. Daarvoor tellen de
   echte runs (herziening: ernstige bevindingen vóór en na) en blinde menselijke beoordelingen.
2. ``compare_arms``: A (vaste code), B (één AI-analist), C (B + uitdager), D (volledige Council) op een vaste lijst
   instrumenten met een harde kostengrens. Gemeten: status, kosten, tijd, onderbouwde beweringen, ernstige
   bevindingen, herstel na herziening, aanbeveling en de geregistreerde kans (later af te rekenen in de ledger).
3. Blinde beoordeling: een mens krijgt uitkomsten zonder variantlabel en geeft bruikbaarheid 1–5 en gevonden fouten.
   Als de eenvoudiger variant even goed scoort, gaat de voorkeur naar de eenvoudiger variant.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from nexus import genesis
from nexus.db import Database, ResearchReview, ResearchRun, ResearchWorkflow

ARMS = ("deterministic", "single", "challenger", "council")
DEFAULT_SUBJECTS = ("BTC-EUR", "ETH-EUR", "SOL-EUR", "IWDA.AS", "ASML.AS", "NVDA", "AAPL", "GC=F", "EURUSD=X", "DOGE-EUR")


# ── 1 · Toets van de uitdager ───────────────────────────────────────────────────────────────
def _bench_facts(asof: datetime) -> list[dict]:
    f = genesis._fact
    return [f("market:X:returns", "X slot 100; 30d -8%; 90d -12%", "measured", asof,
              {"close": 100.0, "ret_30d": -0.08, "ret_90d": -0.12}),
            f("technical:X:indicators", "onder 200-daags; RSI 38", "measured", asof, {"rsi14": 38.0}),
            f("quant:X:forward28", "basiskans 52%", "measured", asof, {"base_rate_up": 0.52}),
            f("news:1", "bericht van vóór het peilmoment", "news", asof - timedelta(days=2)),
            f("news:2", "bericht van ná het peilmoment", "news", asof + timedelta(days=4))]


def _ok(**over) -> dict:
    a = {"hypothesis": "Neerwaarts momentum; geen voordeel boven de basiskans.",
         "claims": [{"text": "De 30-daagse richting is negatief.", "evidence": ["market:X:returns"], "confidence": 0.6,
                     "numbers": [{"value": -0.08, "fact": "market:X:returns"}]},
                    {"text": "Ligt onder het 200-daags gemiddelde.", "evidence": ["technical:X:indicators"], "confidence": 0.6,
                     "numbers": []},
                    {"text": "Basiskans rond de helft.", "evidence": ["quant:X:forward28"], "confidence": 0.5,
                     "numbers": [{"value": 52, "fact": "quant:X:forward28"}]}],
         "assumptions": ["verleden representatief"], "uncertainties": ["vertraagd"], "prob_up": 0.45,
         "missing_information": [], "next_investigations": [], "recommendation": "monitor"}
    a.update(over)
    return a


def _with_claim(i: int, **over) -> dict:
    a = _ok()
    a["claims"] = [dict(c) for c in a["claims"]]
    a["claims"][i] = {**a["claims"][i], **over}
    return a


BENCH = [  # (naam, analyse, verwachte soort of None voor schoon)
    ("schoon-1", lambda: _ok(), None),
    ("schoon-2", lambda: _ok(prob_up=0.5), None),
    ("schoon-3", lambda: _with_claim(0, numbers=[{"value": -8, "fact": "market:X:returns"}]), None),
    ("verkeerd-getal", lambda: _with_claim(0, numbers=[{"value": -0.18, "fact": "market:X:returns"}]), "calculation"),
    ("verkeerd-percentage", lambda: _with_claim(2, numbers=[{"value": 62, "fact": "quant:X:forward28"}]), "calculation"),
    ("verzonnen-bron", lambda: _with_claim(1, evidence=["news:77"]), "unknown_reference"),
    ("geen-bewijs", lambda: _with_claim(1, evidence=[]), "unsupported_claim"),
    ("datalek", lambda: _with_claim(1, evidence=["news:2"]), "data_leakage"),
    ("prestatieclaim", lambda: _with_claim(0, text="Deze strategie verslaat koop-en-houd."), "overfitting"),
    ("te-zeker", lambda: _with_claim(1, confidence=0.95), "overconfidence"),
    ("stellige-taal", lambda: _with_claim(0, text="De koers gaat gegarandeerd omhoog."), "overconfidence"),
    ("tegen-de-meting", lambda: _ok(prob_up=0.8), "conflicting_sources"),
    ("lege-analyse", lambda: _ok(claims=[]), "missing_evidence"),
    ("geen-onzekerheid", lambda: _ok(uncertainties=[]), "overconfidence"),
]


def challenger_benchmark() -> dict:
    asof = datetime(2026, 11, 11, tzinfo=UTC)
    facts = _bench_facts(asof)
    rows = []
    for name, make, expect in BENCH:
        found = genesis.check_analysis(make(), facts, asof)
        kinds = sorted({f["kind"] for f in found})
        rows.append({"case": name, "expected": expect, "found": kinds,
                     "hit": (expect in kinds) if expect else None, "false_alarm": (bool(found) if expect is None else None)})
    planted = [r for r in rows if r["expected"]]
    clean = [r for r in rows if not r["expected"]]
    return {"cases": rows, "planted": len(planted), "detected": sum(r["hit"] for r in planted),
            "clean": len(clean), "false_alarms": sum(r["false_alarm"] for r in clean),
            "set_hash": hashlib.sha256(json.dumps([(n, m(), e) for n, m, e in BENCH], sort_keys=True, default=str)
                                       .encode()).hexdigest()[:16],
            "caveat": "synthetisch en door de ontwikkelaar geschreven: toetst het mechaniek van de controles, "
                      "niet de vangst in echte modeluitvoer"}


# ── 2 · Varianten vergelijken ──────────────────────────────────────────────────────────────
def compare_arms(db: Database, ctx: dict, gateway, subjects=DEFAULT_SUBJECTS, arms=ARMS, cap_usd: float = 0.0,
                 actor: str = "ceo", now: datetime | None = None) -> dict:
    """Draait elke variant op elk instrument. ``cap_usd`` is een harde grens voor de hele vergelijking."""
    now = now or datetime.now(tz=UTC)
    run = f"eval-{secrets.token_hex(5)}"
    g = genesis.with_run_cap(gateway, cap_usd)
    known = genesis.known_symbols(ctx)
    rows = []
    for sym in [x for x in subjects if x in known]:
        for arm in arms:
            w = genesis.run(db, ctx, g, sym, f"Is er reden voor verder onderzoek naar {sym} in de komende 28 dagen?",
                            mode=arm, requested_by=actor, eval_run=run, now=now)
            c = w["conclusion"] or {}
            rules = next((s for s in w["steps"] if s["step"] == "challenge_rules"), {}).get("detail", {})
            rev = (c.get("challenge") or {}).get("revision")
            ms = sum(s.get("ms") or 0 for s in w["steps"])
            rows.append({"subject": sym, "arm": arm, "variant": genesis.MODES[arm], "trace": w["trace_id"], "status": w["status"],
                         "cost_usd": w["cost_usd"], "ms": ms, "supported_claims": len(c.get("supporting_evidence") or []),
                         "high_findings": rules.get("high"), "findings": len(rules.get("findings") or []),
                         "revision_fixed": (rev or {}).get("fixed"), "recommendation": c.get("recommendation"),
                         "prob_up": (c.get("confidence") or {}).get("author_prob_up"),
                         "independent": (c.get("challenge") or {}).get("independent_provider")})
    report = {"run": run, "at": now.isoformat(), "cap_usd": cap_usd, "spent_usd": round(g.run_spent, 6),
              "rows": rows, "arms": aggregate(rows)}
    with db.session.begin() as s:
        s.add(ResearchRun(kind="genesis_arms", status="done", summary={"run": run, "arms": report["arms"]},
                          report=json.loads(json.dumps(report, default=str)),
                          ai_requests=sum(1 for r in rows if r["arm"] != "deterministic" and r["status"] in ("done", "partial")),
                          ai_cost_usd=report["spent_usd"]))
    db.audit(actor, "genesis_compare_arms", {"run": run, "spent_usd": report["spent_usd"]})
    return report


def aggregate(rows: list[dict]) -> dict:
    out = {}
    for arm in ARMS:
        xs = [r for r in rows if r["arm"] == arm]
        ok = [r for r in xs if r["status"] in ("done", "partial")]
        out[arm] = {"variant": genesis.MODES[arm], "runs": len(xs), "completed": len(ok),
                    "blocked": sum(r["status"] == "blocked" for r in xs),
                    "cost_usd": round(sum(r["cost_usd"] or 0 for r in ok), 6),
                    "cost_per_completed": round(sum(r["cost_usd"] or 0 for r in ok) / len(ok), 6) if ok else None,
                    "median_ms": sorted(r["ms"] for r in ok)[len(ok) // 2] if ok else None,
                    "mean_supported_claims": round(sum(r["supported_claims"] for r in ok) / len(ok), 2) if ok else None,
                    "mean_high_findings": round(sum(r["high_findings"] or 0 for r in ok) / len(ok), 2) if ok else None,
                    "revisions_fixed": sum(r["revision_fixed"] or 0 for r in ok)}
    return out


# ── 3 · Blinde menselijke beoordeling ──────────────────────────────────────────────────────
def next_for_review(db: Database, reviewer: str) -> dict | None:
    with db.session() as s:
        done = set(s.scalars(select(ResearchReview.workflow_id).where(ResearchReview.reviewer == reviewer)))
        pool = [w for w in s.scalars(select(ResearchWorkflow).where(ResearchWorkflow.eval_run.is_not(None),
                                                                    ResearchWorkflow.status.in_(("done", "partial"))))
                if w.id not in done]
    if not pool:
        return None
    w = random.Random(f"{reviewer}:{len(done)}").choice(pool)
    c = w.conclusion or {}
    return {"workflow_id": w.id, "subject": w.subject, "question": w.question,     # variant bewust weggelaten
            "conclusion": {k: c.get(k) for k in ("main_hypothesis", "supporting_evidence", "counterarguments",
                                                 "quantitative_findings", "missing_information", "risk_considerations",
                                                 "recommendation", "disagreements")}}


def add_review(db: Database, workflow_id: int, reviewer: str, usefulness: int, errors_found: int = 0, note: str = "") -> dict:
    if not 1 <= int(usefulness) <= 5:
        raise ValueError("bruikbaarheid 1 tot 5")
    with db.session.begin() as s:
        if s.get(ResearchWorkflow, workflow_id) is None:
            raise KeyError(workflow_id)
        s.add(ResearchReview(workflow_id=workflow_id, reviewer=reviewer, usefulness=int(usefulness),
                             errors_found=max(0, int(errors_found)), note=genesis._clean(note, 500)))
    return {"ok": True}


def review_summary(db: Database) -> dict:
    with db.session() as s:
        rows = s.execute(select(ResearchReview, ResearchWorkflow.mode).join(ResearchWorkflow,
                                                                            ResearchWorkflow.id == ResearchReview.workflow_id)).all()
    out = {}
    for arm in ARMS:
        xs = [r.usefulness for r, m in rows if m == arm]
        n = len(xs)
        mean = sum(xs) / n if n else None
        sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1)) if n > 1 else None
        out[arm] = {"variant": genesis.MODES[arm], "n": n, "mean_usefulness": round(mean, 2) if mean is not None else None,
                    "ci95": [round(mean - 1.96 * sd / math.sqrt(n), 2), round(mean + 1.96 * sd / math.sqrt(n), 2)] if sd else None,
                    "errors_found": sum(r.errors_found for r, m in rows if m == arm)}
    return {"arms": out, "total": len(rows),
            "rule": "een complexere variant wint alleen als het 95%-interval boven dat van de eenvoudiger variant ligt"}


def latest(db: Database) -> dict | None:
    with db.session() as s:
        r = s.scalars(select(ResearchRun).where(ResearchRun.kind == "genesis_arms").order_by(ResearchRun.id.desc())).first()
        return r.report if r else None

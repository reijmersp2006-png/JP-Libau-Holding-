"""Prediction Ledger (E1.5): falsifieerbare voorspellingen die na registratie niet meer kunnen veranderen.

Regels (in code afgedwongen, niet alleen beschreven):
- Registratietijd = servertijd. Een agent kan geen tijdstip in het verleden opgeven.
- De horizon moet ná de registratie liggen, en de gebruikte data moet van vóór de registratie zijn.
- De uitkomst is vooraf exact gedefinieerd (``outcome_def``) en wordt door vaste code bepaald, niet door een model.
- Voorspellingen, amendementen en uitkomsten zijn alleen-toevoegen (ORM-hook én databasetrigger).
- Een amendement kan alleen vóór het einde van de horizon, en de oorspronkelijke voorspelling blijft staan
  en blijft meetellen. Zo kan niemand na afloop een gunstiger cijfer neerzetten.
- Hash-keten over alle voorspellingen: wijzigen of weghalen buiten de app om valt op (``verify``).

Uitkomsten na 12-11-2026 liggen in de prospectieve holdout-periode. Ze worden hier alleen gebruikt om
voorspellingen te scoren, nooit om een strategie te kiezen of af te stellen.
"""

from __future__ import annotations

import hashlib
import json
import math
import secrets
from datetime import UTC, datetime

from sqlalchemy import select

from nexus.db import Database, Prediction, PredictionAmendment, PredictionOutcome

MIN_CALIBRATION_N = 30          # minder afgerekende voorspellingen: geen kalibratie-uitspraak
OUTCOME_TYPES = ("price_above",)


class LedgerError(ValueError):
    pass


def _utc(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _body(p: dict) -> str:
    keys = ("pid", "agent", "provider", "model", "prompt_version", "subject", "outcome_def", "probability",
            "evidence", "data_asof", "market_snapshot", "horizon_end", "workflow_trace", "created_at", "prev_hash")
    return json.dumps({k: p.get(k) for k in keys}, sort_keys=True, default=str)


def _validate_def(d: dict) -> None:
    if d.get("type") not in OUTCOME_TYPES:
        raise LedgerError(f"onbekend uitkomsttype {d.get('type')!r}")
    if not d.get("symbol") or not isinstance(d.get("threshold"), int | float) or d.get("interval") != "1d":
        raise LedgerError("price_above vraagt symbol, interval '1d' en een numerieke drempel")


def register(db: Database, *, agent: str, subject: str, outcome_def: dict, probability: float,
             horizon_end: datetime, data_asof: datetime, evidence: list[str] | None = None,
             provider: str | None = None, model: str | None = None, prompt_version: str = "v1",
             market_snapshot: dict | None = None, workflow_trace: str | None = None,
             now: datetime | None = None) -> dict:
    now = now or datetime.now(tz=UTC)
    if not 0.0 <= float(probability) <= 1.0 or math.isnan(float(probability)):
        raise LedgerError("kans moet tussen 0 en 1 liggen")
    if _utc(horizon_end) <= now:
        raise LedgerError("de horizon moet in de toekomst liggen: achteraf voorspellen kan niet")
    if _utc(data_asof) > now:
        raise LedgerError("data van na het registratiemoment kan niet als invoer dienen")
    _validate_def(outcome_def)
    with db.session.begin() as s:
        prev = s.scalars(select(Prediction.hash).order_by(Prediction.id.desc()).limit(1)).first()
        row = {"pid": f"pred-{secrets.token_hex(8)}", "agent": agent, "provider": provider, "model": model,
               "prompt_version": prompt_version, "subject": subject, "outcome_def": outcome_def,
               "probability": round(float(probability), 6), "evidence": list(evidence or []),
               "data_asof": _utc(data_asof).isoformat(), "market_snapshot": market_snapshot or {},
               "horizon_end": _utc(horizon_end).isoformat(), "workflow_trace": workflow_trace,
               "created_at": now.isoformat(), "prev_hash": prev}
        h = hashlib.sha256(_body(row).encode()).hexdigest()
        s.add(Prediction(**{**row, "data_asof": _utc(data_asof), "horizon_end": _utc(horizon_end), "created_at": now,
                            "hash": h}))
    return {**row, "hash": h}


def amend(db: Database, pid: str, actor: str, reason: str, change: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(tz=UTC)
    if not reason.strip():
        raise LedgerError("een amendement vraagt een reden")
    with db.session.begin() as s:
        p = s.scalars(select(Prediction).where(Prediction.pid == pid)).first()
        if p is None:
            raise KeyError(pid)
        if _utc(p.horizon_end) <= now:
            raise LedgerError("na het einde van de horizon kan een voorspelling niet meer worden gecorrigeerd")
        body = json.dumps({"pid": pid, "actor": actor, "reason": reason, "change": change, "at": now.isoformat(),
                           "of": p.hash}, sort_keys=True, default=str)
        a = PredictionAmendment(prediction_id=p.id, actor=actor, reason=reason, change=change, created_at=now,
                                hash=hashlib.sha256(body.encode()).hexdigest())
        s.add(a)
    return {"pid": pid, "amended": True, "note": "de oorspronkelijke voorspelling blijft staan en telt mee"}


def resolve_due(db: Database, closes, now: datetime | None = None) -> list[dict]:
    """Rekent verlopen voorspellingen af met vaste code. ``closes(symbol)`` geeft [(ts, close), ...] dagkoersen.
    Uitkomst = slotkoers van de eerste dagcandle op of na het einde van de horizon > drempel."""
    now = now or datetime.now(tz=UTC)
    out = []
    with db.session() as s:
        done = set(s.scalars(select(PredictionOutcome.prediction_id)))
        due = [p for p in s.scalars(select(Prediction).where(Prediction.horizon_end <= now)) if p.id not in done]
    for p in due:
        d = p.outcome_def
        series = [(t if t.tzinfo else t.replace(tzinfo=UTC), c) for t, c in closes(d["symbol"])]
        after = [(t, c) for t, c in series if t >= _utc(p.horizon_end)]
        if not after:
            out.append({"pid": p.pid, "status": "waiting_for_data"})
            continue
        t, c = after[0]
        with db.session.begin() as s:
            s.add(PredictionOutcome(prediction_id=p.id, outcome=int(c > d["threshold"]), evaluator="ledger.resolve_due",
                                    detail={"close": c, "bar_ts": t.isoformat(), "threshold": d["threshold"]}))
        out.append({"pid": p.pid, "status": "resolved", "outcome": int(c > d["threshold"])})
    return out


def verify(db: Database) -> dict:
    with db.session() as s:
        prev, n = None, 0
        for p in s.scalars(select(Prediction).order_by(Prediction.id)):
            row = {"pid": p.pid, "agent": p.agent, "provider": p.provider, "model": p.model,
                   "prompt_version": p.prompt_version, "subject": p.subject, "outcome_def": p.outcome_def,
                   "probability": p.probability, "evidence": p.evidence, "data_asof": _utc(p.data_asof).isoformat(),
                   "market_snapshot": p.market_snapshot, "horizon_end": _utc(p.horizon_end).isoformat(),
                   "workflow_trace": p.workflow_trace, "created_at": _utc(p.created_at).isoformat(), "prev_hash": p.prev_hash}
            if p.prev_hash != prev or hashlib.sha256(_body(row).encode()).hexdigest() != p.hash:
                return {"ok": False, "broken_at": p.pid, "checked": n}
            prev, n = p.hash, n + 1
    return {"ok": True, "checked": n}


# ── Evaluatie ──────────────────────────────────────────────────────────────────────────────
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def score(pairs: list[tuple[float, int]], base_rate: float | None = None) -> dict:
    """Brier, log loss, richting, kalibratie (alleen bij genoeg n) en Brier-skill tegen een vaste basiskans."""
    n = len(pairs)
    if n == 0:
        return {"n": 0, "note": "nog geen afgerekende voorspellingen"}
    brier = sum((p - y) ** 2 for p, y in pairs) / n
    eps = 1e-6
    logloss = -sum(y * math.log(max(p, eps)) + (1 - y) * math.log(max(1 - p, eps)) for p, y in pairs) / n
    hits = sum(int((p >= 0.5) == bool(y)) for p, y in pairs)
    out = {"n": n, "brier": round(brier, 4), "log_loss": round(logloss, 4),
           "directional_accuracy": round(hits / n, 4), "directional_ci95": wilson(hits, n)}
    if base_rate is not None:
        ref = sum((base_rate - y) ** 2 for _, y in pairs) / n
        out["brier_reference"] = round(ref, 4)
        out["brier_skill"] = round(1 - brier / ref, 4) if ref > 0 else None
    if n >= MIN_CALIBRATION_N:
        bins = []
        for lo in (0.0, 0.2, 0.4, 0.6, 0.8):
            xs = [(p, y) for p, y in pairs if lo <= p < lo + 0.2 or (lo == 0.8 and p == 1.0)]
            if xs:
                bins.append({"bin": f"{lo:.1f}-{lo + 0.2:.1f}", "n": len(xs), "mean_p": round(sum(p for p, _ in xs) / len(xs), 3),
                             "freq": round(sum(y for _, y in xs) / len(xs), 3)})
        out["calibration"] = bins
    else:
        out["calibration"] = None
        out["calibration_note"] = f"pas vanaf {MIN_CALIBRATION_N} afgerekende voorspellingen (nu {n})"
    return out


def summary(db: Database, now: datetime | None = None) -> dict:
    now = now or datetime.now(tz=UTC)
    with db.session() as s:
        preds = s.scalars(select(Prediction).order_by(Prediction.id.desc())).all()
        outs = {o.prediction_id: o for o in s.scalars(select(PredictionOutcome))}
        n_am = {}
        for a in s.scalars(select(PredictionAmendment)):
            n_am[a.prediction_id] = n_am.get(a.prediction_id, 0) + 1
    by_agent: dict[str, list[tuple[float, int]]] = {}
    for p in preds:
        if p.id in outs:
            by_agent.setdefault(p.agent, []).append((p.probability, outs[p.id].outcome))
    base = by_agent.get("baseline_climatology")
    base_rate = sum(p for p, _ in base) / len(base) if base else None
    return {
        "total": len(preds), "open": sum(1 for p in preds if p.id not in outs),
        "resolved": len(outs), "due_unresolved": sum(1 for p in preds if p.id not in outs and _utc(p.horizon_end) <= now),
        "chain": verify(db),
        "agents": {a: score(xs, base_rate) for a, xs in by_agent.items()},
        "items": [{"pid": p.pid, "agent": p.agent, "model": p.model, "subject": p.subject, "probability": p.probability,
                   "outcome_def": p.outcome_def, "created_at": _utc(p.created_at).isoformat(),
                   "horizon_end": _utc(p.horizon_end).isoformat(), "data_asof": _utc(p.data_asof).isoformat(),
                   "evidence": p.evidence, "workflow_trace": p.workflow_trace, "amendments": n_am.get(p.id, 0),
                   "outcome": outs[p.id].outcome if p.id in outs else None,
                   "status": "resolved" if p.id in outs else ("due" if _utc(p.horizon_end) <= now else "open")}
                  for p in preds[:100]],
        "rules": "onveranderbaar na registratie; uitkomst door vaste code; correcties alleen als amendement vóór de horizon",
    }

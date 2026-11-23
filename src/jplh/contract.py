"""Gedeelde contracten tussen de holding (``jplh``) en NEXUS (Master Prompt 8.0).

De holding is en blijft de enige bron van portefeuille- en risicostand. NEXUS en Jarvis lezen een
*snapshot* in een vast, geversioneerd formaat en rekenen niets opnieuw uit. Dit bestand doet geen
IO en raakt geen orders, limieten, pauzes of planning: het zet alleen de dashboardstand
(``site.build_state``) om naar het contract en controleert dat contract.

Contracten
- ``jplh.snapshot/v1``: de stand van de holding (zie ``operational_snapshot``).
- ``nexus.records/v1``: onderzoeksrecords die NEXUS terugzet voor Jarvis (zie ``validate_records``).

Een nieuwe, niet-compatibele vorm krijgt een nieuw versienummer (v2). Lezers weigeren een versie die
ze niet kennen in plaats van te gokken.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

SNAPSHOT_SCHEMA = "jplh.snapshot/v1"
RECORDS_SCHEMA = "nexus.records/v1"

# Velden die een snapshot nooit mag bevatten (geheimen of besturing). Wordt getest.
FORBIDDEN_KEYS = {"token", "telegram_token", "api_key", "secret", "password", "chat_id"}


def _f(x) -> float | None:
    return None if x is None else float(x)


def _pct(eur: float | None, cap: float | None) -> float | None:
    if eur is None or not cap:
        return None
    return eur / cap - 1


def _desk(d: dict) -> dict:
    cap = d.get("capital_eur")
    return {
        "id": d["id"],
        "name": d.get("name"),
        "status": d.get("status"),
        "paused": bool(d.get("paused_reason")),
        "paused_reason": d.get("paused_reason"),
        "capital_eur": _f(cap),
        "equity_eur": _f(d.get("equity_eur")),
        "cash_eur": _f(d.get("cash_eur")),
        "pnl_pct": _f(d.get("pnl_pct")),
        "benchmark_eur": _f(d.get("benchmark_eur")),
        "benchmark_pct": _pct(d.get("benchmark_eur"), cap),
        "drawdown": _f(d.get("drawdown")),
        "fees_eur": _f(d.get("fees_eur")),
        "trades": d.get("trades"),
        "positions": [{"symbol": p["symbol"], "value_eur": _f(p.get("value_eur")), "pnl_pct": _f(p.get("pnl_pct")),
                       "strategy": p.get("strategy")} for p in d.get("positions") or []],
        "instruments": [{"symbol": i["symbol"], "price_eur": _f(i.get("price_eur")),
                         "change_24h": _f(i.get("change_24h")), "fresh": bool(i.get("fresh")),
                         "strategy": i.get("strategy"), "in_market": bool(i.get("in_market"))}
                        for i in d.get("instruments") or []],
    }


def _academy(a: dict | None) -> dict | None:
    if not a:
        return None
    live = (a.get("live") or {})
    al = live.get("all") or None
    return {"forecasts": a.get("forecasts"), "computed_at": a.get("computed_at"),
            "live_7d": None if al is None else {k: al.get(k) for k in ("n", "effective", "hit", "base", "edge",
                                                                         "edge_lo", "edge_hi", "verdict")}}


def _arena(a: dict | None) -> dict | None:
    if not a:
        return None
    out = {}
    for desk, v in (a.get("desks") or {}).items():
        board = v.get("board") or []
        live = next((r for r in board if r.get("live")), None)
        challengers = [r for r in board if not r.get("live")]
        best = max(challengers, key=lambda r: r.get("return") or float("-inf"), default=None)
        out[desk] = {"live": None if live is None else {k: live.get(k) for k in ("name", "return", "sharpe", "max_dd")},
                     "best_challenger": None if best is None else {k: best.get(k) for k in ("name", "return", "sharpe",
                                                                                              "max_dd", "luck", "promote")},
                     "promote_ready": any(r.get("promote") for r in challengers)}
    return {"start": a.get("start"), "computed_at": a.get("computed_at"), "desks": out}


def _last_round(total: dict) -> str | None:
    """Tijd van de laatste vastgelegde paper-ronde (laatste punt van de equity-curve)."""
    curve = total.get("equity_curve") or []
    return str(curve[-1][0]) if curve else None


def operational_snapshot(state: dict, now: datetime | None = None) -> dict:
    """Zet de dashboardstand om naar ``jplh.snapshot/v1``. Puur: geen IO, geen bijwerkingen."""
    now = now or datetime.now(tz=UTC)
    t = state["total"]
    cap = t.get("capital_eur")
    desks = [_desk(d) for d in state.get("desks") or []]
    instruments = [i for d in desks for i in d["instruments"]]
    health = ((state.get("jarvis") or {}).get("health") or {})
    body = {
        "schema": SNAPSHOT_SCHEMA,
        "source": {"system": "jplh", "name": state.get("name"), "mode": state.get("mode"),
                   "demo": bool(state.get("demo")), "authoritative": True},
        "generated_at": state.get("generated_at"),
        "exported_at": now.isoformat(),
        "freshness": {"state_generated_at": state.get("generated_at"),
                      "last_round_at": _last_round(t),
                      "instruments": len(instruments),
                      "stale_instruments": sorted(i["symbol"] for i in instruments if not i["fresh"])},
        "holding": {"capital_eur": _f(cap), "equity_eur": _f(t.get("equity_eur")), "pnl_pct": _f(t.get("pnl_pct")),
                    "benchmark_eur": _f(t.get("benchmark_eur")), "benchmark_pct": _pct(t.get("benchmark_eur"), cap),
                    "drawdown": _f(t.get("drawdown")), "day_pnl_pct": _f(t.get("day_pnl_pct")),
                    "days_active": state.get("days_active"), "kill_switch": bool(state.get("kill"))},
        "limits": dict(state.get("limits") or {}),
        "desks": desks,
        "market_weather": [{"name": w.get("name"), "ok": w.get("ok"), "text": w.get("text")}
                           for w in state.get("market_weather") or []],
        "academy": _academy(state.get("academy")),
        "arena": _arena(state.get("arena")),
        "health": {"status": health.get("status"), "issues": list(health.get("issues") or [])},
        "live_trading": False,
    }
    body["sha256"] = digest(body)
    return body


def digest(snapshot: dict) -> str:
    """Vaste vingerafdruk van een snapshot (zonder het eigen hashveld en het exportmoment)."""
    core = {k: v for k, v in snapshot.items() if k not in ("sha256", "exported_at")}
    return hashlib.sha256(json.dumps(core, sort_keys=True, default=str).encode()).hexdigest()


def _keys(x) -> set[str]:
    if isinstance(x, dict):
        return set(x) | set().union(*(_keys(v) for v in x.values())) if x else set()
    if isinstance(x, list):
        return set().union(*(_keys(v) for v in x)) if x else set()
    return set()


def validate_snapshot(s: dict) -> list[str]:
    """Lege lijst = geldig. Lezers (NEXUS, Jarvis) weigeren een snapshot met fouten."""
    errs: list[str] = []
    if not isinstance(s, dict):
        return ["snapshot is geen object"]
    if s.get("schema") != SNAPSHOT_SCHEMA:
        return [f"onbekend schema {s.get('schema')!r} (verwacht {SNAPSHOT_SCHEMA})"]
    for k in ("source", "generated_at", "holding", "desks", "limits", "freshness", "sha256"):
        if k not in s:
            errs.append(f"veld ontbreekt: {k}")
    if errs:
        return errs
    if s.get("live_trading") is not False:
        errs.append("live_trading moet false zijn")
    for k in ("equity_eur", "capital_eur", "pnl_pct", "drawdown"):
        if not isinstance(s["holding"].get(k), int | float):
            errs.append(f"holding.{k} ontbreekt of is geen getal")
    ids = [d.get("id") for d in s["desks"]]
    if len(ids) != len(set(ids)):
        errs.append("dubbele afdeling")
    for d in s["desks"]:
        for k in ("id", "status", "paused", "equity_eur", "pnl_pct", "drawdown", "instruments"):
            if k not in d:
                errs.append(f"afdeling {d.get('id')}: veld ontbreekt: {k}")
    try:
        datetime.fromisoformat(str(s["generated_at"]))
    except ValueError:
        errs.append("generated_at is geen ISO-tijd")
    bad = _keys(s) & FORBIDDEN_KEYS
    if bad:
        errs.append(f"verboden velden: {sorted(bad)}")
    if digest(s) != s["sha256"]:
        errs.append("sha256 klopt niet: snapshot is gewijzigd na export")
    return errs


def validate_records(r: dict) -> list[str]:
    """Controle op ``nexus.records/v1`` (wat Jarvis leest)."""
    if not isinstance(r, dict) or r.get("schema") != RECORDS_SCHEMA:
        return [f"onbekend schema {r.get('schema') if isinstance(r, dict) else None!r} (verwacht {RECORDS_SCHEMA})"]
    errs = []
    for i, rec in enumerate(r.get("items") or []):
        for k in ("trace_id", "subject", "created_at", "status", "generator", "snapshot_sha256", "summary"):
            if k not in rec:
                errs.append(f"record {i}: veld ontbreekt: {k}")
    return errs

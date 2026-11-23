"""Master Prompt 9.0 (Overmind): de gegevens achter het Command Center en de Jarvis-antwoorden.

Alles hier is **alleen lezen** en **vaste code**: geen model, geen gok, geen orders. Het bouwt
``jplh.overmind/v1`` uit wat de holding al vastlegt:

- ``attention``: wat nu aandacht vraagt (kritiek → veranderingen → context), elk met bron.
- ``decisions``: openstaande CEO-besluiten (pauzes, promoties, escalaties).
- ``changes``: wat er in 24 uur veranderde.
- ``pulse``: systeemhartslag per onderdeel met tijdstip en drempels (de browser rekent de status opnieuw uit).
- ``replay``: beslissingen met drie strikt gescheiden lagen: RECORDED (vastgelegd op het moment zelf),
  RECONSTRUCTED (alleen data die toen al bekend was) en POST_EVENT (wat er daarna gebeurde).
- ``exposure`` en ``scenarios``: invoer voor de read-only risicosimulator.
- ``radar``: onderzoeksprioriteiten met zichtbare componenten, of NOT RATED.
- ``graph``: getypeerde relaties tussen afdelingen, instrumenten, strategieën, beslissingen, regels en bevindingen.

Publiek veilig: er gaat alleen een expliciete selectie velden mee (geen chat-id's, tokens, paden of logs).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jplh.config import HoldingConfig
from jplh.desks import DESK_NAMES, DESK_ORDER
from jplh.store import Store

SCHEMA = "jplh.overmind/v1"
RECORDS_FILE = Path("intelligence") / "records.json"

# Hartslag: binnen ``healthy`` uur gezond, na ``stale`` uur verouderd; daartussen DEGRADED.
PULSE = {
    "paper_cycle": ("Handelsronde (elk uur)", 1.5, 3.0),
    "market_1h": ("Koersen per uur", 2.0, 4.0),
    "market_1d": ("Dagkoersen", 26.0, 50.0),
    "scouts": ("Verkenners en meme-radar", 2.0, 6.0),
    "risk": ("Risicodirecteur", 26.0, 50.0),
    "academy": ("Academie", 26.0, 50.0),
    "coach": ("Coaches", 26.0, 50.0),
    "arena": ("Schaduw-arena", 26.0, 50.0),
    "snapshot": ("Snapshot voor NEXUS", 1.5, 3.0),
}

# Deterministische scenario's (geen kansen): schok per activaklasse, plus valuta en concentratie.
SCENARIOS = [
    {"id": "market", "name": "Brede marktdaling", "shocks": {"stocks": -0.10, "crypto": -0.15, "meme": -0.20, "metals": -0.03, "fx": 0.0},
     "assumption": "Aandelen -10%, crypto -15%, memes -20%, metalen -3%, valuta 0%. Cash blijft gelijk."},
    {"id": "crypto", "name": "Cryptocrash", "shocks": {"crypto": -0.30, "meme": -0.40},
     "assumption": "Crypto -30% en memes -40%; de rest gelijk."},
    {"id": "equity_vol", "name": "Volatiliteitsschok aandelen", "shocks": {"stocks": -0.07},
     "assumption": "Aandelen -7% in één klap; de rest gelijk."},
    {"id": "fx", "name": "Euro +5% tegen de dollar", "usd_move": -0.05,
     "assumption": "Alles wat in dollars genoteerd staat, wordt 5% minder waard in euro's."},
    {"id": "correlation", "name": "Alles beweegt samen", "shocks": {"stocks": -0.12, "crypto": -0.12, "meme": -0.12, "metals": -0.12, "fx": -0.02},
     "assumption": "Spreiding helpt niet: alle risicoklassen -12%, valuta -2%."},
    {"id": "single", "name": "Grootste positie halveert", "largest": -0.50,
     "assumption": "Alleen de grootste positie van de holding verliest 50%."},
]

FORBIDDEN = {"chat", "chat_id", "token", "telegram_token", "api_key", "secret", "password", "offset"}


# ── hulpjes ────────────────────────────────────────────────────────────────────────────────

def _dt(x) -> datetime | None:
    if not x:
        return None
    d = datetime.fromisoformat(str(x))
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _age_h(ts, now: datetime) -> float | None:
    d = _dt(ts)
    return None if d is None else round((now - d).total_seconds() / 3600, 2)


def _pct(x) -> str:
    return "onbekend" if x is None else f"{x * 100:+.1f}%".replace(".", ",")


def _eur(x) -> str:
    return "onbekend" if x is None else f"€{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _status(age: float | None, healthy: float, stale: float) -> str:
    if age is None:
        return "UNKNOWN"
    if age <= healthy:
        return "HEALTHY"
    return "DEGRADED" if age <= stale else "STALE"


def _curve_change(curve: list, now: datetime, hours: float = 24) -> float | None:
    """Verandering over de laatste ``hours`` uur uit een equity-curve [[ts, waarde], ...]."""
    if not curve or len(curve) < 2:
        return None
    cut = now - timedelta(hours=hours)
    before = [v for t, v in curve if _dt(t) <= cut]
    start = before[-1] if before else curve[0][1]
    return curve[-1][1] / start - 1 if start else None


def _max_ts(db, sql: str) -> str | None:
    try:
        row = db.execute(sql).fetchone()
    except Exception:                     # tabel bestaat niet (nog): geen bewijs
        return None
    return row[0] if row and row[0] else None


# ── onderdelen ─────────────────────────────────────────────────────────────────────────────

def pulse(state: dict, market: Store, now: datetime, records: dict | None) -> list[dict]:
    ts = {
        "paper_cycle": (state["total"].get("equity_curve") or [[None]])[-1][0],
        "market_1h": _max_ts(market.db, "SELECT MAX(fetched_at) FROM candles WHERE interval='1h'"),
        "market_1d": _max_ts(market.db, "SELECT MAX(fetched_at) FROM candles WHERE interval='1d'"),
        "scouts": _max_ts(market.db, "SELECT MAX(fetched_at) FROM radar"),
        "risk": (state.get("risk") or {}).get("computed_at"),
        "academy": (state.get("academy") or {}).get("computed_at"),
        "coach": (state.get("coach") or {}).get("computed_at"),
        "arena": (state.get("arena") or {}).get("computed_at"),
        "snapshot": state.get("generated_at"),
    }
    out = []
    for key, (name, healthy, stale) in PULSE.items():
        age = _age_h(ts[key], now)
        out.append({"id": key, "name": name, "last_ts": ts[key], "healthy_h": healthy, "stale_h": stale,
                    "status": _status(age, healthy, stale), "age_h": age, "evidence": "data-tijdstempel in paper-data"})
    stale = [i["symbol"] for d in state["desks"] for i in d.get("instruments") or [] if not i.get("fresh")]
    out.append({"id": "feeds", "name": "Koersen per instrument", "last_ts": ts["market_1h"], "healthy_h": None,
                "stale_h": None, "status": "DEGRADED" if stale else "HEALTHY", "age_h": None,
                "detail": f"niet vers: {', '.join(stale)}" if stale else "alle koersen vers",
                "evidence": "versheidsvlag per instrument (max. datalengte uit de config)"})
    out.append({"id": "jarvis", "name": "Jarvis (Telegram, elke 10 min.)", "last_ts": None, "healthy_h": 0.5, "stale_h": 2.0,
                "status": "UNKNOWN", "age_h": None, "github_workflow": "jarvis.yml",
                "evidence": "geen tijdstempel in de data; de browser leest de laatste run publiek van GitHub"})
    out.append({"id": "publish", "name": "Dashboard-publicatie", "last_ts": None, "healthy_h": 1.5, "stale_h": 3.0,
                "status": "UNKNOWN", "age_h": None, "github_workflow": "paper.yml",
                "evidence": "de browser leest de laatste run publiek van GitHub"})
    if records:
        age = _age_h(records.get("exported_at"), now)
        out.append({"id": "nexus", "name": "NEXUS-onderzoek", "last_ts": records.get("exported_at"), "healthy_h": 26.0,
                    "stale_h": 50.0, "status": _status(age, 26.0, 50.0), "age_h": age, "evidence": "intelligence/records.json"})
    else:
        out.append({"id": "nexus", "name": "NEXUS-onderzoek", "last_ts": None, "healthy_h": None, "stale_h": None,
                    "status": "BLOCKED", "age_h": None,
                    "detail": "NEXUS is niet uitgerold; er komen nog geen onderzoeksrecords bij de holding",
                    "evidence": "geen intelligence/records.json"})
    out.append({"id": "ai", "name": "AI-aanbieders en modelgebruik", "last_ts": None, "healthy_h": None, "stale_h": None,
                "status": "BLOCKED", "age_h": None,
                "detail": "geen AI-sleutel gekoppeld; 0 modelaanroepen, €0 kosten",
                "evidence": "de holding roept geen model aan; NEXUS-gateway niet uitgerold"})
    h = ((state.get("jarvis") or {}).get("health") or {})
    out.append({"id": "risk_monitor", "name": "Risicobewaking", "last_ts": state.get("generated_at"), "healthy_h": 1.5,
                "stale_h": 3.0, "status": _status(_age_h(state.get("generated_at"), now), 1.5, 3.0),
                "age_h": _age_h(state.get("generated_at"), now),
                "detail": f"bewaking draait; meldt nu {len(h.get('issues') or [])} probleem/problemen (status {h.get('status')})",
                "evidence": "gezondheidscheck bij elke ronde"})
    return out


def _desk_events(desks: dict, limit: int = 200) -> list[tuple[str, datetime, str, dict]]:
    out = []
    for cls, desk in desks.items():
        for ts, kind, p in desk.holding.store.events(limit=limit):
            out.append((cls, ts, kind, p))
    out.sort(key=lambda e: e[1], reverse=True)
    return out


def _equity_at(curve: list[tuple[datetime, float]], ts: datetime) -> tuple[float | None, float | None]:
    before = [e for t, e in curve if t <= ts]
    if not before:
        return None, None
    return before[-1], max(before)


def replay(config: HoldingConfig, desks: dict, market: Store, now: datetime, limit: int = 60) -> list[dict]:
    """Beslissingen terugkijken zonder vooruitkijken: de RECONSTRUCTED-laag gebruikt alleen data met
    ``fetched_at`` vóór het besluit (``known_at``). Originele records worden niet aangepast."""
    events = _desk_events(desks)
    fills = {(c, p.get("instrument"), ts.isoformat()): p for c, ts, k, p in events if k == "fill"}
    reflections = {(c, p.get("key")): {**p, "ts": ts.isoformat()} for c, ts, k, p in events if k == "reflection"}
    curves = {c: d.holding.store.equity_curve() for c, d in desks.items()}
    out = []
    for c, ts, kind, p in events:
        if kind not in ("decision", "pause", "resume", "selection") or (kind == "selection" and not p.get("changes")):
            continue
        item = {"id": f"{c}:{kind}:{ts.isoformat()}:{p.get('instrument', '')}", "desk": c,
                "desk_name": DESK_NAMES.get(c, c), "kind": kind, "ts": ts.isoformat()}
        rec = {"reason": p.get("reason")}
        if kind == "decision":
            sym = p.get("instrument")
            rec.update({k: p.get(k) for k in ("instrument", "side", "strategy", "signal_reason", "approved", "size_eur")})
            rec["checks"] = p.get("checks") or []
            fill = fills.get((c, sym, ts.isoformat()))
            if fill:
                rec["fill"] = {k: fill.get(k) for k in ("price_eur", "quantity", "fee_eur")}
            known = market.latest_close(sym, "1h", known_at=ts)
            eq, peak = _equity_at(curves[c], ts)
            item["reconstructed"] = {"price_known": known[1] if known else None,
                                     "price_ts": known[0].isoformat() if known else None,
                                     "desk_equity": eq, "desk_drawdown": (1 - eq / peak) if eq and peak else None}
            now_px = market.latest_close(sym, "1h", known_at=now)
            base = (fill or {}).get("price_eur") or (known[1] if known else None)
            post = {"price_now": now_px[1] if now_px else None, "price_now_ts": now_px[0].isoformat() if now_px else None}
            try:
                post["currency"] = config.instrument(sym).currency
            except KeyError:
                post["currency"] = None
            # Fill-prijs is in euro; candles in de eigen munt. Alleen vergelijken bij dezelfde munt.
            if base and now_px and (not fill or post["currency"] == "EUR"):
                move = now_px[1] / base - 1
                post["move_since"] = move
                post["effect"] = ("koers steeg na de verkoop: vasthouden was beter geweest" if p.get("side") == "sell" and move > 0
                                  else "koers daalde na de verkoop: verkopen hielp" if p.get("side") == "sell"
                                  else "koers steeg sinds de aankoop" if move > 0 else "koers daalde sinds de aankoop")
            refl = next((r for (rc, key), r in reflections.items() if rc == c and key and key.startswith(f"{sym}|")
                         and _dt(r.get("exit_ts")) == ts), None)
            if refl:
                post["reflection"] = {k: refl.get(k) for k in ("ts", "pnl_pct", "hold_pct", "edge_vs_hold",
                                                                "best_alternative", "verdict", "lessons")}
            item["post_event"] = post
        elif kind in ("pause", "resume"):
            eq, peak = _equity_at(curves[c], ts)
            item["reconstructed"] = {"desk_equity": eq, "desk_peak": peak,
                                     "desk_drawdown": (1 - eq / peak) if eq and peak else None,
                                     "limit": config.risk.max_drawdown_pct}
            cur = curves[c][-1][1] if curves[c] else None
            item["post_event"] = {"desk_equity_now": cur, "change_since": (cur / eq - 1) if cur and eq else None}
        else:
            rec.update({"selection": p.get("selection"), "changes": p.get("changes")})
        item["recorded"] = rec
        out.append(item)
        if len(out) >= limit:
            break
    return out


def exposure(state: dict, config: HoldingConfig) -> dict:
    pos, cash = [], {}
    for d in state["desks"]:
        cash[d["id"]] = d.get("cash_eur") or 0.0
        for p in d.get("positions") or []:
            try:
                inst = config.instrument(p["symbol"])
                cls, cur = inst.asset_class.value, inst.currency
            except KeyError:
                cls, cur = d["id"], None
            pos.append({"desk": d["id"], "symbol": p["symbol"], "asset_class": cls, "currency": cur,
                        "value_eur": p.get("value_eur") or 0.0})
    total = state["total"].get("equity_eur") or 0.0
    return {"positions": pos, "cash": cash, "equity_eur": total,
            "invested_eur": sum(p["value_eur"] for p in pos),
            "limit_drawdown": config.risk.max_drawdown_pct,
            "desk_equity": {d["id"]: d.get("equity_eur") for d in state["desks"]},
            "desk_peak": {d["id"]: d.get("peak_eur") for d in state["desks"]},
            "desk_paused": {d["id"]: bool(d.get("paused_reason")) for d in state["desks"]}}


def _priority(evidence: float | None, confirmation: float | None, freshness: float | None, minimum_ok: bool,
              missing: list[str]) -> dict:
    comps = {"evidence": evidence, "confirmation": confirmation, "freshness": freshness}
    missing = list(missing) + [k for k, v in comps.items() if v is None]
    if missing or not minimum_ok:
        return {"rated": False, "score": None, "components": comps, "missing": missing or ["te weinig bewijs"]}
    return {"rated": True, "score": round(100 * evidence * confirmation * freshness), "components": comps, "missing": []}


def radar(state: dict, now: datetime) -> list[dict]:
    """Onderzoeksprioriteiten. Prioriteit = 100 × bewijs × bevestiging × versheid (elk 0–1), alleen als alle
    drie bekend zijn en het minimum aan bewijs gehaald is; anders NOT RATED. Geen koop- of verkoopsignaal."""
    out = []
    paused = {d["id"] for d in state["desks"] if d.get("paused_reason")}
    arena = state.get("arena") or {}
    fresh_arena = 1.0 if (_age_h(arena.get("computed_at"), now) or 99) <= 26 else 0.0
    for desk, v in (arena.get("desks") or {}).items():
        board = v.get("board") or []
        live = next((r for r in board if r.get("live")), None)
        for r in board:
            if r.get("live") or live is None:
                continue
            edge = (r.get("return") or 0) - (live.get("return") or 0)
            days = r.get("days") or 0
            luck = r.get("luck")
            conf = None if luck is None else max(0.0, min(1.0, 1 - (luck - 0.10) / 0.40)) if luck > 0.10 else 1.0
            miss = [] if luck is not None else ["toeval-toets nog niet mogelijk (te weinig dagen)"]
            p = _priority(min(1.0, days / 90), conf, fresh_arena, edge > 0 and days >= 14, miss)
            if edge <= 0:
                p["missing"] = ["geen voorsprong op wat live draait"]
            out.append({"id": f"arena:{desk}:{r.get('variant')}", "source": "Schaduw-arena", "desk": desk,
                        "question": f"Is '{r.get('name')}' bij {DESK_NAMES.get(desk, desk)} echt beter dan de huidige regels?",
                        "observed": f"{_pct(r.get('return'))} tegen live {_pct(live.get('return'))} over {days} dagen (schaduw, nepgeld)",
                        "constraints": ["afdeling gepauzeerd"] if desk in paused else [], **p})
    ac = state.get("academy") or {}
    fresh_ac = 1.0 if (_age_h(ac.get("computed_at"), now) or 99) <= 26 else 0.0
    for t in ac.get("team") or []:
        if t.get("strategy") == "koop_en_houd":
            continue
        eff = t.get("effective") or 0
        conf = 1.0 if (t.get("edge_lo") or 0) > 0 else 0.5 if (t.get("edge") or 0) > 0 else 0.0
        p = _priority(min(1.0, eff / 250), conf, fresh_ac, eff >= 30 and (t.get("edge") or 0) > 0, [])
        if (t.get("edge") or 0) <= 0:
            p["missing"] = ["geen voorsprong op vasthouden in de geschiedenis"]
        out.append({"id": f"academy:{t['desk']}:{t['strategy']}", "source": "Academie (geschiedenis)", "desk": t["desk"],
                    "question": f"Voegt {t['strategy']} iets toe bij {DESK_NAMES.get(t['desk'], t['desk'])}?",
                    "observed": f"trefkans {_pct(t.get('hit'))} tegen vasthouden {_pct(t.get('hold_hit'))}, voorsprong {_pct(t.get('edge'))} "
                                f"(90%: {_pct(t.get('edge_lo'))} tot {_pct(t.get('edge_hi'))}), effectief {eff:.0f} metingen; {t.get('verdict')}",
                    "constraints": ["afdeling gepauzeerd"] if t["desk"] in paused else [], **p})
    co = state.get("coach") or {}
    fresh_co = 1.0 if (_age_h(co.get("computed_at"), now) or 99) <= 26 * 7 else 0.0
    seen: set[str] = set()
    for desk, rules in (co.get("desks") or {}).items():
        for r in rules:
            if r["id"] in seen:                   # samenwerkingsregels staan bij beide afdelingen
                continue
            seen.add(r["id"])
            n = r.get("n")
            conf = {"klopt": 1.0, "deels": 0.5}.get(r.get("verdict"), 0.0)
            p = _priority(None if n is None else min(1.0, n / 50), conf, fresh_co,
                          (n or 0) >= 10 and conf > 0, [] if n is not None else ["aantal metingen niet vastgelegd"])
            if conf == 0:
                p["rated"], p["score"], p["missing"] = False, None, [f"regel {r.get('verdict')}"]
            out.append({"id": f"rule:{r['id']}", "source": "Coach-regel", "desk": desk,
                        "question": f"{r.get('title')}: is er een veilige, toetsbare toepassing?",
                        "observed": r.get("text"), "constraints": ["afdeling gepauzeerd"] if desk in paused else [], **p})
    out.sort(key=lambda o: (not o["rated"], -(o["score"] or 0)))
    return out


def graph(state: dict, config: HoldingConfig, replay_items: list[dict], alerts: list[dict], records: dict | None) -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def node(nid, kind, label, **kw):
        nodes.setdefault(nid, {"id": nid, "type": kind, "label": label, **kw})
        return nid

    def edge(kind, a, b, ts=None, provenance="", nature="observed", **kw):
        edges.append({"type": kind, "source": a, "target": b, "ts": ts, "provenance": provenance, "nature": nature, **kw})

    gen = state.get("generated_at")
    for d in state["desks"]:
        dn = node(f"desk:{d['id']}", "department", d["name"], status=d.get("status"), paused=bool(d.get("paused_reason")))
        for i in d.get("instruments") or []:
            an = node(f"asset:{i['symbol']}", "asset", i["symbol"], fresh=i.get("fresh"))
            edge("DESK_TRADES_ASSET", dn, an, gen, "config: instrumenten per afdeling")
            if i.get("strategy"):
                sn = node(f"strategy:{i['strategy']}", "strategy", i["strategy"])
                edge("ASSET_USES_STRATEGY", an, sn, d.get("selected_at") or gen, "huidige weekkeuze van de afdeling")
    for it in replay_items[:40]:
        rid = f"decision:{it['id']}"
        dn = f"desk:{it['desk']}"
        if it["kind"] == "decision":
            r = it["recorded"]
            node(rid, "decision", f"{r.get('side')} {r.get('instrument')}", ts=it["ts"])
            edge("DEPARTMENT_MADE_DECISION", dn, rid, it["ts"], "logboek van de afdeling (vastgelegd op het moment)", "recorded")
            edge("DECISION_CONCERNS_ASSET", rid, node(f"asset:{r.get('instrument')}", "asset", r.get("instrument")), it["ts"],
                 "logboek", "recorded")
            if r.get("strategy"):
                edge("DECISION_USED_STRATEGY", rid, node(f"strategy:{r['strategy']}", "strategy", r["strategy"]), it["ts"],
                     "logboek", "recorded")
        elif it["kind"] in ("pause", "resume"):
            node(rid, "risk", "pauze" if it["kind"] == "pause" else "hervat", ts=it["ts"])
            edge("RISK_ASSESSMENT_CONCERNS_DEPARTMENT", rid, dn, it["ts"], "risicoregel (logboek)", "recorded")
    for t in (state.get("academy") or {}).get("team") or []:
        fid = node(f"finding:{t['desk']}|{t['strategy']}", "finding", f"Academie: {t['strategy']}", verdict=t.get("verdict"),
                   desk=t["desk"])
        edge("FINDING_CONCERNS_STRATEGY", fid, node(f"strategy:{t['strategy']}", "strategy", t["strategy"]),
             (state.get("academy") or {}).get("computed_at"), "Academie: geschiedenis van de afdeling", "observed",
             verdict=t.get("verdict"))
        edge("FINDING_CONCERNS_DEPARTMENT", fid, f"desk:{t['desk']}", (state.get("academy") or {}).get("computed_at"),
             "Academie", "observed")
    co = state.get("coach") or {}
    for desk, rules in (co.get("desks") or {}).items():
        for r in rules:
            nature = "observed" if r.get("verdict") == "klopt" else "hypothesis"
            rid = node(f"rule:{r['id']}", "rule", r.get("title"), verdict=r.get("verdict"))
            edge("RULE_CONCERNS_DEPARTMENT", rid, f"desk:{desk}", co.get("computed_at"), "coach: getoetst op eigen koersen",
                 nature, verdict=r.get("verdict"))
            if r.get("partner"):
                edge("RULE_LINKS_DEPARTMENTS", rid, f"desk:{r['partner']}", co.get("computed_at"), "coach: samenwerking",
                     nature, verdict=r.get("verdict"))
    for desk, v in ((state.get("arena") or {}).get("desks") or {}).items():
        for r in v.get("board") or []:
            if r.get("live"):
                continue
            cid = node(f"challenger:{desk}:{r.get('variant')}", "challenger", r.get("name"), ret=r.get("return"))
            edge("CHALLENGER_COMPETES_IN_DEPARTMENT", cid, f"desk:{desk}", (state.get("arena") or {}).get("computed_at"),
                 "schaduw-arena (nepgeld)", "observed")
    for a in alerts:
        if not a.get("symbol") or str(a["symbol"]).startswith("markt:"):
            continue
        eid = node(f"event:{a['ts']}:{a['symbol']}", "event", f"{a.get('kind')} {a['symbol']}", ts=a["ts"], level=a.get("level"))
        edge("EVENT_AFFECTS_ASSET", eid, node(f"asset:{a['symbol']}", "asset", a["symbol"]), a["ts"], "verkenners", "observed")
    if records:
        src = node("source:jplh.snapshot", "source", "jplh.snapshot/v1")
        for r in records.get("items") or []:
            rid = node(f"record:{r['trace_id']}", "research", r.get("summary", "")[:60], ts=r.get("created_at"))
            edge("RESEARCH_REFERENCES_SOURCE", rid, src, r.get("created_at"), f"NEXUS {r.get('generator')}", "recorded")
            subj = r.get("subject", "")
            if subj.startswith("desk:"):
                edge("RESEARCH_CONCERNS_DEPARTMENT", rid, f"desk:{subj[5:]}", r.get("created_at"), "NEXUS", "recorded")
    known, uniq = set(nodes), {}
    for e in edges:
        if e["source"] in known and e["target"] in known:
            uniq.setdefault((e["type"], e["source"], e["target"]), e)
    edges = list(uniq.values())
    return {"nodes": list(nodes.values()), "edges": edges,
            "missing": [] if records else ["NEXUS-onderzoeksrecords (NEXUS niet uitgerold)"]
            + ["nieuwsgebeurtenissen (News Reactor geblokkeerd: geen bron)", "Prediction Ledger (niet in gebruik)"]}


def attention(state: dict, ov: dict, now: datetime) -> tuple[list[dict], list[dict]]:
    items: list[dict] = []
    decisions: list[dict] = []
    t = state["total"]
    if state.get("kill"):
        items.append({"level": "critical", "title": "Noodstop staat AAN", "detail": "Er gaat geen enkele order uit.",
                      "section": "control", "source": "KILL-bestand"})
    for d in state["desks"]:
        if d.get("paused_reason"):
            pause = next((r for r in ov["replay"] if r["desk"] == d["id"] and r["kind"] == "pause"), None)
            items.append({"level": "critical", "title": f"{d['name']} staat stil",
                          "detail": f"{d['paused_reason']}. Hervatten is jouw besluit.", "section": "trading",
                          "desk": d["id"], "replay": pause["id"] if pause else None, "source": "risicoregel"})
            decisions.append({"id": f"resume:{d['id']}", "title": f"{d['name']} weer laten handelen?",
                              "detail": f"Gepauzeerd sinds {(pause or {}).get('ts', '?')[:10]}: {d['paused_reason']}",
                              "how": "jplh resume (alleen de eigenaar)", "desk": d["id"], "replay": pause["id"] if pause else None})
    for p in ov["pulse"]:
        if p["status"] == "STALE" and p["id"] in ("paper_cycle", "market_1h", "snapshot"):
            items.append({"level": "critical", "title": f"{p['name']}: verouderd",
                          "detail": f"laatste {p['last_ts']}", "section": "control", "source": "systeemhartslag"})
    limit = state.get("limits", {}).get("max_drawdown_pct") or 0.15
    for d in state["desks"]:
        if not d.get("paused_reason") and (d.get("drawdown") or 0) >= 0.7 * limit:
            items.append({"level": "critical", "title": f"{d['name']} dicht bij de pauzegrens",
                          "detail": f"{_pct(-d['drawdown'])} onder de top (grens {_pct(-limit)})", "section": "trading",
                          "desk": d["id"], "source": "risicoregel"})
    for desk, v in ((state.get("arena") or {}).get("desks") or {}).items():
        for r in v.get("board") or []:
            if r.get("promote"):
                decisions.append({"id": f"promote:{desk}:{r.get('variant')}", "title": f"Uitdager '{r['name']}' promoveren?",
                                  "detail": f"{_pct(r.get('return'))} in de schaduw; toeval {_pct(r.get('luck'))}",
                                  "how": "alleen de CEO beslist (spelregel)", "desk": desk})
    ch = ov["changes"]
    if ch.get("equity_24h") is not None:
        items.append({"level": "change", "title": f"Schatkist {_pct(ch['equity_24h'])} in 24 uur",
                      "detail": f"nu {_eur(t.get('equity_eur'))}", "section": "overview", "source": "equity-curve"})
    if ch["fills_24h"]:
        items.append({"level": "change", "title": f"{len(ch['fills_24h'])} trades in 24 uur",
                      "detail": ", ".join(f"{f['desk_name']}: {f['side']} {f['instrument']}" for f in ch["fills_24h"][:4]),
                      "section": "trading", "source": "logboek"})
    else:
        items.append({"level": "change", "title": "Geen trades in 24 uur", "detail": "de afdelingen hielden vast of stonden stil",
                      "section": "trading", "source": "logboek"})
    if ch["alerts_24h"]:
        items.append({"level": "change", "title": f"{len(ch['alerts_24h'])} meldingen van de verkenners",
                      "detail": ch["alerts_24h"][0]["text"], "section": "intelligence", "source": "verkenners"})
    if t.get("benchmark_eur"):
        gap = t["equity_eur"] / t["benchmark_eur"] - 1
        items.append({"level": "context", "title": f"{'Voor' if gap >= 0 else 'Achter'} op gewoon vasthouden: {_pct(gap)}",
                      "detail": f"holding {_pct(t.get('pnl_pct'))}, vasthouden {_pct(t['benchmark_eur'] / t['capital_eur'] - 1)}",
                      "section": "overview", "source": "benchmark"})
    live = ((state.get("academy") or {}).get("live") or {}).get("all")
    if live:
        items.append({"level": "context", "title": f"Academie: {live.get('verdict')}",
                      "detail": f"{live.get('n')} voorspellingen op 7 dagen, effectief {live.get('effective')} meting(en)",
                      "section": "academy", "source": "Academie"})
    return items, decisions


def changes(state: dict, desks: dict, market: Store, now: datetime) -> dict:
    cut = now - timedelta(hours=24)
    fills, sel = [], []
    for c, ts, kind, p in _desk_events(desks, 100):
        if ts < cut:
            continue
        if kind == "fill":
            fills.append({"desk": c, "desk_name": DESK_NAMES.get(c, c), "ts": ts.isoformat(), "instrument": p.get("instrument"),
                          "side": p.get("side"), "price_eur": p.get("price_eur"), "fee_eur": p.get("fee_eur")})
        elif kind == "selection" and p.get("changes"):
            sel.append({"desk": c, "ts": ts.isoformat(), "changes": p.get("changes")})
    from jplh.scouts import recent as recent_alerts
    alerts = [a for a in recent_alerts(market, 40) if _dt(a["ts"]) and _dt(a["ts"]) >= cut]
    lessons = [x for x in (state.get("lessons") or {}).get("items") or [] if _dt(x.get("ts")) and _dt(x["ts"]) >= cut]
    return {"equity_24h": _curve_change(state["total"].get("equity_curve") or [], now),
            "desks_24h": {d["id"]: _curve_change(d.get("equity_curve") or [], now) for d in state["desks"]},
            "fills_24h": fills, "selections_24h": sel,
            "alerts_24h": [{k: a.get(k) for k in ("ts", "symbol", "kind", "level", "text")} for a in alerts],
            "lessons_24h": len(lessons)}


def load_records(home: Path | None) -> dict | None:
    if home is None:
        return None
    p = Path(home) / RECORDS_FILE
    if not p.exists():
        return None
    try:
        from jplh.contract import validate_records
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if not validate_records(data) else None
    except (OSError, ValueError):
        return None


def build(state: dict, config: HoldingConfig, desks: dict, market: Store, now: datetime | None = None,
          home: Path | None = None) -> dict:
    now = now or datetime.now(tz=UTC)
    records = load_records(home)
    ov: dict = {"schema": SCHEMA, "generated_at": now.isoformat(), "live_trading": False}
    ov["pulse"] = pulse(state, market, now, records)
    ov["replay"] = replay(config, desks, market, now)
    ov["changes"] = changes(state, desks, market, now)
    ov["attention"], ov["decisions"] = attention(state, ov, now)
    for r in (records or {}).get("items") or []:
        if r.get("recommendation") == "escalate_to_ceo":
            ov["decisions"].append({"id": f"nexus:{r['trace_id']}", "title": "NEXUS vraagt je aandacht",
                                    "detail": r.get("summary"), "how": "onderzoeksrecord bekijken"})
    ov["exposure"] = exposure(state, config)
    ov["scenarios"] = SCENARIOS
    ov["radar"] = radar(state, now)
    from jplh.scouts import recent as recent_alerts
    ov["graph"] = graph(state, config, ov["replay"], [a for a in recent_alerts(market, 40)
                                                       if _dt(a["ts"]) and _dt(a["ts"]) >= now - timedelta(days=3)], records)
    ov["research"] = {"connected": records is not None, "items": (records or {}).get("items") or [],
                      "exported_at": (records or {}).get("exported_at")}
    ov["desk_order"] = [c for c in DESK_ORDER if c in desks]
    return ov


def forbidden_keys(x) -> set[str]:
    if isinstance(x, dict):
        return (set(x) & FORBIDDEN) | set().union(*(forbidden_keys(v) for v in x.values()))
    if isinstance(x, list):
        return set().union(*(forbidden_keys(v) for v in x)) if x else set()
    return set()


# ── Jarvis: gegronde antwoorden in vaste code ──────────────────────────────────────────────

def attention_text(ov: dict) -> str:
    lines = ["🧭 Wat vraagt je aandacht (vaste regels, geen AI)"]
    crit = [a for a in ov["attention"] if a["level"] == "critical"]
    lines += [f"🔴 {a['title']}: {a['detail']}" for a in crit] or ["✅ Niets kritieks."]
    if ov["decisions"]:
        lines.append("Besluiten die op jou wachten:")
        lines += [f"• {d['title']} ({d['how']})" for d in ov["decisions"]]
    return "\n".join(lines)


def changes_text(ov: dict) -> str:
    ch = ov["changes"]
    lines = [f"🔄 Afgelopen 24 uur: schatkist {_pct(ch.get('equity_24h'))}"]
    for desk, v in ch["desks_24h"].items():
        if v is not None:
            lines.append(f"• {DESK_NAMES.get(desk, desk)}: {_pct(v)}")
    lines.append(f"Trades: {len(ch['fills_24h'])}" + (": " + ", ".join(f"{f['side']} {f['instrument']}" for f in ch["fills_24h"][:5])
                                                      if ch["fills_24h"] else ""))
    if ch["selections_24h"]:
        lines.append(f"Strategiewissels: {sum(len(s['changes']) for s in ch['selections_24h'])}")
    lines.append(f"Verkennersmeldingen: {len(ch['alerts_24h'])} · nieuwe lessen: {ch['lessons_24h']}")
    return "\n".join(lines)


ICON = {"HEALTHY": "🟢", "DEGRADED": "🟡", "STALE": "🟠", "BLOCKED": "⛔", "UNKNOWN": "⚪"}


def pulse_text(ov: dict) -> str:
    lines = ["🩺 Systeemhartslag (op basis van tijdstempels in de data)"]
    for p in ov["pulse"]:
        age = f", {p['age_h']:.1f} u geleden" if p.get("age_h") is not None else ""
        lines.append(f"{ICON.get(p['status'], '⚪')} {p['name']}: {p['status']}{age}" + (f" ({p['detail']})" if p.get("detail") else ""))
    return "\n".join(lines)


def pause_text(ov: dict, state: dict, desk: str) -> str:
    d = next((x for x in state["desks"] if x["id"] == desk), None)
    if d is None:
        return "Die afdeling ken ik niet."
    if not d.get("paused_reason"):
        return f"{d['name']} staat niet stil: status '{d.get('status')}'."
    p = next((r for r in ov["replay"] if r["desk"] == desk and r["kind"] == "pause"), None)
    lines = [f"⏸ {d['name']} staat stil.", f"Vastgelegd ({(p or {}).get('ts', '?')[:16].replace('T', ' ')}): {d['paused_reason']}"]
    if p:
        rc = p["reconstructed"]
        lines.append(f"Toen: {_eur(rc.get('desk_equity'))}, top {_eur(rc.get('desk_peak'))}, daling {_pct(-(rc.get('desk_drawdown') or 0))}"
                     f" (grens {_pct(-(rc.get('limit') or 0))}).")
        pe = p["post_event"]
        lines.append(f"Sindsdien: {_pct(pe.get('change_since'))} (nu {_eur(pe.get('desk_equity_now'))}).")
    lines.append("Hervatten kan alleen jij (jplh resume). Jarvis en NEXUS kunnen dat niet.")
    return "\n".join(lines)

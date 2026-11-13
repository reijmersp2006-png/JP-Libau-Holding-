"""AI Expert Council: dertien rollen, eerst onafhankelijk, dan een debat, dan een uitgelegd besluit.

Werking per run (één instrument):
1. **Context** wordt deterministisch opgebouwd uit echte data: koersen en indicatoren, regime,
   nieuws (met id), onderzoeksbewijs (kampioen/uitdagers) en de eigen trackrecord van elke agent.
   Elk stuk context heeft een id (``ind:sma200``, ``news:12``, ``research:arena``). Bewijs dat naar een
   onbekend id verwijst, wordt als "niet onderbouwd" gemarkeerd.
2. **Onafhankelijk**: elke relevante agent oordeelt zonder de anderen te zien (gestructureerde JSON).
3. **Debat**: elke agent ziet de samenvattingen van de anderen, mag ze aanvechten en zijn oordeel
   bijstellen.
4. **Besluit**: de CIO weegt de oordelen met gewichten uit de echte trackrecord (Brier-score, niet
   stemmen tellen) en legt uit waarom. Een REJECT van de Risk Guardian is bindend.

Grenzen die in de code zitten, niet in de prompt:
- De Council plaatst nooit een order. Hoogstens maakt hij een voorstel, dat langs de Risk Guardian
  moet en daarna handmatig uitgevoerd wordt (alleen paper).
- Zonder ``ANTHROPIC_API_KEY`` of boven het dagbudget draait er niets en wordt er niets verzonnen.
- De Risk Guardian, de kwantitatief onderzoeker en de onafhankelijke auditor zijn deterministisch.
- Zekerheid is pas "gekalibreerd" als de agent genoeg afgerekende voorspellingen heeft.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from nexus import evolution, stats
from nexus.db import AgentForecast, CouncilRun, Database, NewsEvent, utcnow

MODEL = "claude-opus-5-5"
PRICE_PER_MTOK = {"input": 4.00, "output": 20.00}          # USD, standaardtarief
STANCES = ["BUY", "HOLD", "SELL", "NEUTRAL", "REJECT", "APPROVE", "APPROVE_WITH_LIMITS"]
BULLISH, BEARISH = {"BUY"}, {"SELL", "REJECT"}


@dataclass(frozen=True)
class Agent:
    key: str
    name: str
    kind: str                         # llm | deterministic | coordinator
    responsibilities: str
    inputs: tuple[str, ...]
    limitations: str
    asset_classes: tuple[str, ...] = ("stocks", "crypto", "meme", "metals", "fx")


AGENTS: list[Agent] = [
    Agent("cio", "Chief Investment Officer", "coordinator",
          "Weegt alle oordelen op basis van trackrecord en bewijs, legt het besluit en de onenigheid uit.",
          ("all",), "Kan alleen kiezen uit wat de agents aanleveren; volgt een REJECT van de Risk Guardian altijd."),
    Agent("quant", "Quantitative Researcher", "deterministic",
          "Vertaalt walk-forward-, holdout- en bootstrapresultaten naar een oordeel over de statistische voorsprong.",
          ("research", "market"), "Alleen wat het onderzoek heeft gemeten; geen mening over nieuws."),
    Agent("technical", "Technical Analyst", "llm",
          "Trend, momentum, steun/weerstand, volume en beweeglijkheid uit de aangeleverde indicatoren.",
          ("market",), "Ziet alleen koersdata; technische patronen hebben vaak een zwakke voorspellende waarde."),
    Agent("fundamental", "Fundamental Analyst", "llm",
          "Waardering, winstkwaliteit en bedrijfsnieuws (alleen voor aandelen en ETF's).",
          ("market", "news"), "Er is nog geen bron met jaarcijfers of consensusverwachtingen gekoppeld.",
          ("stocks",)),
    Agent("crypto", "Crypto Analyst", "llm",
          "Crypto-specifieke dynamiek: regime van BTC, liquiditeit, regelgeving, beveiligingsincidenten.",
          ("market", "news"), "Geen on-chain- of derivatendata (funding, open interest) gekoppeld.", ("crypto", "meme")),
    Agent("meme", "Meme Coin Analyst", "llm",
          "Speculatief risico van memecoins: liquiditeit, concentratie, hype en manipulatie.",
          ("market", "news"), "Beveiligingscontroles (bijv. GoPlus) zijn nog niet gekoppeld.", ("meme",)),
    Agent("news", "News Intelligence Analyst", "llm",
          "Welke recente, geverifieerde gebeurtenissen relevant zijn; feit tegenover speculatie; historische reactie.",
          ("news",), "Alleen officiële bronnen in de database; geen consensusverwachtingen."),
    Agent("macro", "Macro Economist", "llm",
          "Rente, inflatie, arbeidsmarkt en valuta, en hun richting voor dit instrument.",
          ("market", "news"), "Geen macro-tijdreeksen (FRED) gekoppeld; alleen publicaties en marktkoersen.",
          ("stocks", "fx", "metals", "crypto")),
    Agent("regime", "Market Regime Specialist", "llm",
          "Classificeert het marktregime (trend, beweeglijkheid, zijwaarts) en wat dat betekent voor strategiekeuze.",
          ("market", "research"), "Regimes worden achteraf duidelijker dan op het moment zelf."),
    Agent("portfolio", "Portfolio Manager", "llm",
          "Past een positie in de portefeuille: spreiding, correlatie, omvang tegenover de risicolimieten.",
          ("market", "portfolio"), "Ziet de portefeuille van NEXUS-paper, niet die van andere rekeningen."),
    Agent("risk", "Risk Guardian", "deterministic",
          "Toetst de limieten (omvang, daling, liquiditeit, spread) en de noodstop. Een REJECT is bindend.",
          ("market", "portfolio"), "Kent alleen de ingestelde limieten; zegt niets over rendement."),
    Agent("evolution", "Strategy Evolution Scientist", "llm",
          "Koppelt het besluit aan het trade-geheugen: welke fouten kwamen eerder voor in vergelijkbare situaties.",
          ("memory", "research"), "Het trade-geheugen is nog klein; patronen zijn voorlopig."),
    Agent("auditor", "Independent Strategy Auditor", "deterministic",
          "Controleert het bewijs van de anderen: verwijzen ze naar echte data, is de zekerheid onderbouwd, is er groepsdenken.",
          ("all",), "Beoordeelt de onderbouwing, niet de marktrichting."),
]


def agent(key: str) -> Agent:
    return next(a for a in AGENTS if a.key == key)


# ── Gestructureerde output ─────────────────────────────────────────────────────────────────
def _schema(debate: bool = False) -> dict:
    props = {
        "stance": {"type": "string", "enum": STANCES},
        "prob_up": {"type": ["number", "null"], "description": "kans dat de koers over horizon_days hoger staat (0-1)"},
        "horizon_days": {"type": "integer"},
        "summary": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "evidence": {"type": "array", "items": {"type": "object", "properties": {
            "ref": {"type": "string"}, "claim": {"type": "string"}}, "required": ["ref", "claim"],
            "additionalProperties": False}},
        "counterarguments": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}},
        "data_gaps": {"type": "array", "items": {"type": "string"}},
    }
    req = list(props)
    if debate:
        props["changed_mind"] = {"type": "boolean"}
        props["challenges"] = {"type": "array", "items": {"type": "object", "properties": {
            "agent": {"type": "string"}, "point": {"type": "string"}}, "required": ["agent", "point"],
            "additionalProperties": False}}
        req += ["changed_mind", "challenges"]
    return {"type": "object", "properties": props, "required": req, "additionalProperties": False}


DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["BUY", "HOLD", "SELL", "NO_TRADE"]},
        "size_fraction": {"type": "number", "description": "deel van de toegestane maximale positie, 0-1"},
        "rationale": {"type": "string"},
        "weighed": {"type": "array", "items": {"type": "object", "properties": {
            "agent": {"type": "string"}, "weight": {"type": "number"}, "why": {"type": "string"}},
            "required": ["agent", "weight", "why"], "additionalProperties": False}},
        "disagreements": {"type": "array", "items": {"type": "string"}},
        "why_not_majority": {"type": "string"},
        "conditions": {"type": "array", "items": {"type": "string"}},
        "invalidation": {"type": "string"},
    },
    "required": ["action", "size_fraction", "rationale", "weighed", "disagreements", "why_not_majority",
                 "conditions", "invalidation"],
    "additionalProperties": False,
}

SYSTEM = """Je bent {name} in de AI Expert Council van NEXUS, een onderzoeks- en paper-tradingplatform.
Taak: {resp}
Beperkingen die je moet benoemen: {limits}

Regels:
- Gebruik alleen de aangeleverde context. Verwijs bij elk bewijs naar het id uit de context (bijv. ind:sma200,
  news:12, research:arena). Verzin geen cijfers, nieuws of koersen.
- Zeg het als de data onvoldoende is (stance NEUTRAL, prob_up null) in plaats van te gokken.
- prob_up is een kans, geen zekerheid. Wees terughoudend: het onderzoek toont dat de meeste regels koop-en-houd
  niet verslaan.
- Je adviseert alleen. Je plaatst geen orders en kunt de Risk Guardian niet omzeilen.
- Antwoord in het Nederlands."""


# ── Context ────────────────────────────────────────────────────────────────────────────────
def build_context(db: Database, symbol: str, asset_class: str, candles, research: dict | None = None,
                  portfolio: dict | None = None, now: datetime | None = None) -> dict:
    """Alleen echte, gelabelde data. Elk onderdeel krijgt een id waarnaar agents moeten verwijzen."""
    now = now or datetime.now(tz=UTC)
    ids: dict[str, object] = {}
    market = {}
    if candles:
        i = len(candles) - 1
        ind = evolution.indicators_at(candles, i)
        reg = evolution.regime_at(candles, i)
        market = {"last_ts": candles[-1].ts.isoformat(), "indicators": ind, "regime": reg,
                  "returns": {f"r{k}": candles[-1].close / candles[-1 - k].close - 1
                              for k in (1, 5, 20, 60, 120, 250) if len(candles) > k},
                  "data_label": "HISTORICAL" if now - candles[-1].ts > timedelta(days=2) else "DELAYED"}
        for k, v in ind.items():
            ids[f"ind:{k}"] = v
        for k, v in market["returns"].items():
            ids[f"ret:{k}"] = v
        ids["regime"] = reg
    news = []
    with db.session() as s:
        rows = s.scalars(select(NewsEvent).where(NewsEvent.published_at >= now - timedelta(days=14))
                         .order_by(NewsEvent.published_at.desc()).limit(80)).all()
    for e in rows:
        if symbol in (e.assets or []) or e.category in ("rate_decision", "inflation", "employment"):
            item = {"id": f"news:{e.id}", "title": e.title, "source": e.source, "kind": e.source_kind,
                    "published_at": e.published_at.isoformat(), "category": e.category,
                    "factuality": e.factuality, "reaction": (e.reaction or {}).get(symbol)}
            news.append(item)
            ids[item["id"]] = item
    if research:
        ids["research:arena"] = research
    if portfolio:
        ids["portfolio"] = portfolio
    with db.session() as s:
        mem = s.scalars(select(evolution.DecisionRecord).where(evolution.DecisionRecord.symbol == symbol,
                                                               evolution.DecisionRecord.outcome_at.is_not(None))
                        .order_by(evolution.DecisionRecord.ts.desc()).limit(30)).all()
    tags = Counter(t for r in mem for t in (r.error_tags or []))
    memory = {"decisions": len(mem), "error_tags": dict(tags),
              "hit_rate": (sum(1 for r in mem if (r.outcome or {}).get("good")) / len(mem)) if mem else None}
    ids["memory"] = memory
    return {"symbol": symbol, "asset_class": asset_class, "as_of": now.isoformat(), "market": market,
            "news": news, "research": research or {"available": False}, "portfolio": portfolio or {},
            "memory": memory, "ids": sorted(ids)}


def _view(ctx: dict, a: Agent) -> dict:
    keep = set(a.inputs)
    if "all" in keep:
        return ctx
    out = {k: ctx[k] for k in ("symbol", "asset_class", "as_of", "ids")}
    if "market" in keep:
        out["market"] = ctx["market"]
    if "news" in keep:
        out["news"] = ctx["news"]
    if "research" in keep:
        out["research"] = ctx["research"]
    if "portfolio" in keep:
        out["portfolio"] = ctx["portfolio"]
    if "memory" in keep:
        out["memory"] = ctx["memory"]
    return out


# ── Deterministische agents ────────────────────────────────────────────────────────────────
def quant_view(ctx: dict) -> dict:
    r = ctx.get("research") or {}
    if not r.get("available", True) or not r.get("champion"):
        return _out("NEUTRAL", None, "Geen onderzoeksresultaat voor dit instrument.", [], ["geen walk-forward-data"])
    passed_dev_gates = r.get("passed_dev_gates", [])
    bh = r.get("buy_hold", {})
    best = (r.get("challengers") or [{}])[0]
    ev = [{"ref": "research:arena", "claim": f"koop-en-houd walk-forward Sharpe {bh.get('sharpe', 0):.2f}"},
          {"ref": "research:arena", "claim": f"beste uitdager {best.get('family')} Sharpe "
                                             f"{(best.get('walk_forward') or {}).get('sharpe', 0):.2f}, "
                                             f"{best.get('gates_passed', 0)} van 8 poorten"}]
    if passed_dev_gates:
        # Ontwikkelpoorten halen is nog geen koopsignaal: holdout, paper en risicotoets volgen nog.
        return _out("NEUTRAL", None, f"Uitdager(s) {', '.join(passed_dev_gates)} halen de ontwikkelpoorten; "
                    "nog niet bewezen op holdout en paper, dus geen handelssignaal.", ev, ["holdout en paper nog open"])
    return _out("HOLD", None, "Geen enkele regel verslaat koop-en-houd geloofwaardig; geen actief signaal als voorsprong.",
                ev, ["voorsprong niet aangetoond"])


def risk_view(ctx: dict, guardian_verdict: dict | None) -> dict:
    if guardian_verdict is None:
        return _out("APPROVE_WITH_LIMITS", None, "Geen concreet voorstel; limieten blijven van kracht bij uitvoering.",
                    [], ["geen voorstel om te toetsen"])
    if guardian_verdict.get("approved"):
        return _out("APPROVE_WITH_LIMITS", None, guardian_verdict.get("reason", ""),
                    [{"ref": "portfolio", "claim": c["detail"]} for c in guardian_verdict.get("checks", [])[:5]], [])
    failed = [c for c in guardian_verdict.get("checks", []) if not c["passed"]]
    return _out("REJECT", None, guardian_verdict.get("reason", "veto"),
                [{"ref": "portfolio", "claim": c["detail"]} for c in failed[:5]], [])


def audit_view(outputs: dict[str, dict], ctx: dict) -> dict:
    valid = set(ctx["ids"])
    issues, total, bad = [], 0, 0
    for k, o in outputs.items():
        for e in o.get("evidence", []):
            total += 1
            if e["ref"] not in valid:
                bad += 1
        if o.get("prob_up") is not None and not o.get("evidence"):
            issues.append(f"{k}: kans zonder bewijs")
    stances = [o["stance"] for o in outputs.values()]
    top = max(set(stances), key=stances.count) if stances else None
    share = stances.count(top) / len(stances) if stances else 0
    if share >= 0.85 and len(stances) >= 4:
        issues.append(f"mogelijk groepsdenken: {share:.0%} kiest {top}")
    quality = 1 - bad / total if total else None
    if quality is not None and quality < 0.8:
        issues.append(f"{bad} van {total} bewijsverwijzingen bestaan niet in de context")
    stance = "APPROVE" if not issues else "APPROVE_WITH_LIMITS"
    return {**_out(stance, None, "; ".join(issues) or "bewijs verwijst naar bestaande data; geen groepsdenken gezien",
                   [], []), "evidence_quality": quality, "agreement": share}


def _out(stance, prob, summary, evidence, gaps) -> dict:
    return {"stance": stance, "prob_up": prob, "horizon_days": 20, "summary": summary, "key_points": [],
            "evidence": evidence, "counterarguments": [], "limitations": [], "data_gaps": gaps}


# ── Kosten ─────────────────────────────────────────────────────────────────────────────────
def cost_usd(tokens_in: int, tokens_out: int) -> float:
    return tokens_in / 1e6 * PRICE_PER_MTOK["input"] + tokens_out / 1e6 * PRICE_PER_MTOK["output"]


def spent_today(db: Database, now: datetime | None = None) -> float:
    now = now or datetime.now(tz=UTC)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    with db.session() as s:
        return float(s.scalar(select(func.coalesce(func.sum(CouncilRun.cost_usd), 0.0))
                              .where(CouncilRun.created_at >= start)) or 0.0)


def daily_budget() -> float:
    return float(os.environ.get("NEXUS_AI_DAILY_BUDGET_USD", "3.0"))


# ── Gewichten uit trackrecord ──────────────────────────────────────────────────────────────
def weights(db: Database, prior_n: int = 20) -> dict[str, dict]:
    """Gewicht per agent: 1 − Brier/0,25, krimpend naar 0,5 bij weinig afgerekende voorspellingen.
    Brier 0,25 = munt opgooien; lager is beter."""
    out = {}
    with db.session() as s:
        rows = s.execute(select(AgentForecast.agent, func.count(AgentForecast.brier), func.avg(AgentForecast.brier))
                         .where(AgentForecast.brier.is_not(None), AgentForecast.phase == "debate")
                         .group_by(AgentForecast.agent)).all()
    for a, n, brier in rows:
        skill = max(0.0, 1 - float(brier) / 0.25)
        w = (n * skill + prior_n * 0.5) / (n + prior_n)
        out[a] = {"n": n, "brier": float(brier), "weight": round(w, 3), "calibrated": n >= 30}
    for a in AGENTS:
        out.setdefault(a.key, {"n": 0, "brier": None, "weight": 0.5, "calibrated": False})
    return out


# ── Run ────────────────────────────────────────────────────────────────────────────────────
class Unavailable(Exception):
    pass


def _client():
    if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        raise Unavailable("geen ANTHROPIC_API_KEY ingesteld")
    import anthropic
    return anthropic.Anthropic()


def _call(client, system: str, user: str, schema: dict, effort: str) -> tuple[dict, int, int]:
    out, tin, tout, _model = _call_full(client, system, user, schema, effort)
    return out, tin, tout


def _call_full(client, system: str, user: str, schema: dict, effort: str) -> tuple[dict, int, int, str | None]:
    """Als ``_call``, plus het model dat echt antwoordde (bij server-side fallback kan dat afwijken)."""
    resp = client.beta.messages.create(
        model=MODEL, max_tokens=8000, system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
    )
    tin, tout = resp.usage.input_tokens, resp.usage.output_tokens
    if resp.stop_reason == "refusal":
        raise RuntimeError("model weigerde het verzoek")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("antwoord afgekapt (max_tokens)")
    text = next((b.text for b in resp.content if b.type == "text"), "")
    return json.loads(text), tin, tout, getattr(resp, "model", None)


def relevant_agents(asset_class: str) -> list[Agent]:
    return [a for a in AGENTS if asset_class in a.asset_classes]


def convene(db: Database, symbol: str, asset_class: str, candles, research: dict | None = None,
            portfolio: dict | None = None, guardian_verdict: dict | None = None, client=None,
            now: datetime | None = None, cache_hours: int = 6) -> dict:
    """Eén volledige Council-run. Geeft altijd een record terug; bij geen sleutel of budget: status
    ``unavailable``/``budget`` zonder oordelen."""
    now = now or datetime.now(tz=UTC)
    ctx = build_context(db, symbol, asset_class, candles, research, portfolio, now)
    h = hashlib.sha256(json.dumps({k: ctx[k] for k in ("symbol", "market", "news", "research")},
                                  sort_keys=True, default=str).encode()).hexdigest()
    with db.session() as s:
        prev = s.scalars(select(CouncilRun).where(CouncilRun.symbol == symbol, CouncilRun.status == "done",
                                                  CouncilRun.created_at >= now - timedelta(hours=cache_hours))
                         .order_by(CouncilRun.id.desc())).first()
        if prev is not None and (prev.inputs or {}).get("hash") == h:
            return _as_dict(prev, cached=True)
    agents = relevant_agents(asset_class)
    if not agents:
        raise ValueError(f"onbekende vermogensklasse {asset_class!r}")
    llm_agents = [a for a in agents if a.kind == "llm"]
    est = cost_usd(len(llm_agents) * 2 * 6000 + 9000, len(llm_agents) * 2 * 1200 + 2000)
    status, error = "done", None
    if spent_today(db, now) + est > daily_budget():
        status, error = "budget", f"dagbudget ${daily_budget():.2f} zou overschreden worden (schatting ${est:.2f})"
    if status == "done":
        try:
            client = client or _client()
        except Unavailable as e:
            status, error = "unavailable", str(e)
    if status != "done":
        return _save(db, symbol, status, {"hash": h, "context": ctx}, [], [], {}, 0, 0, error)

    tin = tout = 0
    independent: dict[str, dict] = {}
    try:
        for a in llm_agents:
            sysmsg = SYSTEM.format(name=a.name, resp=a.responsibilities, limits=a.limitations)
            user = ("Fase 1, onafhankelijk oordeel. Context (JSON):\n" + json.dumps(_view(ctx, a), default=str)
                    + "\nGeef je oordeel voor de komende 20 handelsdagen.")
            o, i, out = _call(client, sysmsg, user, _schema(), "medium")
            independent[a.key], tin, tout = o, tin + i, tout + out
        independent["quant"] = quant_view(ctx)
        independent["risk"] = risk_view(ctx, guardian_verdict)
        debate: dict[str, dict] = {}
        summaries = {k: {"stance": v["stance"], "prob_up": v.get("prob_up"), "summary": v["summary"]}
                     for k, v in independent.items()}
        for a in llm_agents:
            sysmsg = SYSTEM.format(name=a.name, resp=a.responsibilities, limits=a.limitations)
            others = {k: v for k, v in summaries.items() if k != a.key}
            user = ("Fase 2, debat. Jouw eerste oordeel:\n" + json.dumps(independent[a.key], default=str)
                    + "\nDe anderen:\n" + json.dumps(others, default=str)
                    + "\nContext (JSON):\n" + json.dumps(_view(ctx, a), default=str)
                    + "\nVecht zwakke punten aan, en stel je oordeel alleen bij als het bewijs daartoe dwingt.")
            o, i, out = _call(client, sysmsg, user, _schema(debate=True), "medium")
            debate[a.key], tin, tout = o, tin + i, tout + out
        debate["quant"], debate["risk"] = independent["quant"], independent["risk"]
        debate["auditor"] = audit_view({k: v for k, v in debate.items()}, ctx)
        w = weights(db)
        cio = agent("cio")
        user = ("Fase 3, besluit. Oordelen na het debat:\n" + json.dumps(debate, default=str)
                + "\nGewichten uit de trackrecord (Brier, krimpend bij weinig data):\n" + json.dumps(w)
                + "\nContext (JSON):\n" + json.dumps(ctx, default=str)
                + "\nNeem geen meerderheidsbesluit: weeg naar bewijs en trackrecord en leg de onenigheid uit. "
                  "Een REJECT van de Risk Guardian betekent NO_TRADE.")
        decision, i, out = _call(client, SYSTEM.format(name=cio.name, resp=cio.responsibilities, limits=cio.limitations),
                                 user, DECISION_SCHEMA, "high")
        tin, tout = tin + i, tout + out
    except Exception as e:  # noqa: BLE001 - mislukte run wordt vastgelegd, niets ingevuld
        return _save(db, symbol, "failed", {"hash": h, "context": ctx}, list(independent.items()), [], {}, tin, tout,
                     str(e)[:500])
    # Harde regels na het model: de Risk Guardian en de omvang.
    if debate["risk"]["stance"] == "REJECT":
        decision["action"] = "NO_TRADE"
        decision["conditions"] = [*decision.get("conditions", []), "Risk Guardian: veto (bindend)"]
    decision["size_fraction"] = max(0.0, min(1.0, float(decision.get("size_fraction", 0))))
    decision["weights"] = w
    run = _save(db, symbol, "done", {"hash": h, "context": ctx}, list(independent.items()), list(debate.items()),
                decision, tin, tout, None)
    _record_forecasts(db, run["id"], symbol, candles, ctx, independent, debate, now)
    return run


def _save(db, symbol, status, inputs, independent, debate, decision, tin, tout, error) -> dict:
    with db.session.begin() as s:
        r = CouncilRun(symbol=symbol, status=status, model=MODEL if status in ("done", "failed") else None,
                       inputs=json.loads(json.dumps(inputs, default=str)),
                       independent=[{"agent": k, **v} for k, v in independent],
                       debate=[{"agent": k, **v} for k, v in debate], decision=decision,
                       tokens_in=tin, tokens_out=tout, cost_usd=cost_usd(tin, tout), error=error)
        s.add(r)
        s.flush()
        db.audit("council", f"council_{status}", {"run_id": r.id, "symbol": symbol, "cost_usd": cost_usd(tin, tout),
                                                   "action": (decision or {}).get("action"), "error": error}, s=s)
        return _as_dict(r)


def _as_dict(r: CouncilRun, cached: bool = False) -> dict:
    return {"id": r.id, "symbol": r.symbol, "status": r.status, "model": r.model, "independent": r.independent,
            "debate": r.debate, "decision": r.decision, "tokens_in": r.tokens_in, "tokens_out": r.tokens_out,
            "cost_usd": r.cost_usd, "error": r.error, "cached": cached,
            "created_at": (r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=UTC)).isoformat()}


def _record_forecasts(db, run_id, symbol, candles, ctx, independent, debate, now):
    if not candles:
        return
    price = candles[-1].close
    reg = (ctx.get("market") or {}).get("regime", {}).get("label")
    with db.session.begin() as s:
        for phase, outs in (("independent", independent), ("debate", debate)):
            for k, o in outs.items():
                if k == "auditor":
                    continue
                s.add(AgentForecast(run_id=run_id, agent=k, phase=phase, symbol=symbol, ts=candles[-1].ts, price=price,
                                    stance=o["stance"], prob_up=o.get("prob_up"), horizon_days=o.get("horizon_days") or 20,
                                    regime=reg, evidence=o.get("evidence", [])))


# ── Evaluatie van agents ───────────────────────────────────────────────────────────────────
def resolve_forecasts(db: Database, candles_of: dict) -> int:
    n = 0
    with db.session.begin() as s:
        for f in s.scalars(select(AgentForecast).where(AgentForecast.resolved_at.is_(None))):
            c = candles_of.get(f.symbol)
            if not c:
                continue
            ts = f.ts if f.ts.tzinfo else f.ts.replace(tzinfo=UTC)
            i = next((k for k, x in enumerate(c) if x.ts >= ts), None)
            if i is None or i + f.horizon_days >= len(c):
                continue
            r = c[i + f.horizon_days].close / c[i].close - 1
            up = 1.0 if r > 0 else 0.0
            f.realized_return = r
            if f.prob_up is not None:
                f.brier = (float(f.prob_up) - up) ** 2
            if f.stance in BULLISH:
                f.hit = r > 0
            elif f.stance in BEARISH:
                f.hit = r <= 0
            f.resolved_at = utcnow()
            n += 1
    return n


def scorecard(db: Database) -> list[dict]:
    """Per agent: voorspellingen, trefkans, Brier, kalibratie per kansvak, per regime, en bijdrage."""
    with db.session() as s:
        rows = s.scalars(select(AgentForecast).where(AgentForecast.resolved_at.is_not(None),
                                                     AgentForecast.phase == "debate")).all()
        runs = {r.id: r for r in s.scalars(select(CouncilRun).where(CouncilRun.status == "done"))}
    by: dict[str, list[AgentForecast]] = {}
    for f in rows:
        by.setdefault(f.agent, []).append(f)
    out = []
    for a in AGENTS:
        fs = by.get(a.key, [])
        hits = [f.hit for f in fs if f.hit is not None]
        briers = [f.brier for f in fs if f.brier is not None]
        buckets = {}
        for f in fs:
            if f.prob_up is None:
                continue
            b = min(4, int(float(f.prob_up) * 5))
            d = buckets.setdefault(b, {"range": f"{b * 20}-{b * 20 + 20}%", "n": 0, "up": 0})
            d["n"] += 1
            d["up"] += (f.realized_return or 0) > 0
        regimes: dict[str, list[bool]] = {}
        for f in fs:
            if f.hit is not None:
                regimes.setdefault(f.regime or "?", []).append(f.hit)
        agree_right = sum(1 for f in fs if f.hit and _agrees(f, runs.get(f.run_id)))
        mistakes: dict[str, int] = {}
        for f in fs:
            if f.hit is False:
                mistakes[f"{f.stance} in {f.regime}"] = mistakes.get(f"{f.stance} in {f.regime}", 0) + 1
        out.append({"agent": a.key, "name": a.name, "kind": a.kind, "forecasts": len(fs),
                    "hit_rate": sum(hits) / len(hits) if hits else None, "brier": stats.mean(briers) if briers else None,
                    "calibration": [{**v, "observed_up": v["up"] / v["n"]} for _, v in sorted(buckets.items())],
                    "by_regime": {k: {"n": len(v), "hit_rate": sum(v) / len(v)} for k, v in regimes.items()},
                    "decision_contribution": agree_right, "repeated_mistakes": sorted(mistakes.items(), key=lambda kv: -kv[1])[:3],
                    "evidence_quality": _evidence_quality(fs), "limitations": a.limitations,
                    "responsibilities": a.responsibilities})
    return out


def _agrees(f: AgentForecast, run: CouncilRun | None) -> bool:
    if run is None:
        return False
    act = (run.decision or {}).get("action")
    return (f.stance in BULLISH and act == "BUY") or (f.stance in BEARISH and act in ("SELL", "NO_TRADE"))


def _evidence_quality(fs: list[AgentForecast]) -> float | None:
    refs = [e for f in fs for e in (f.evidence or [])]
    if not refs:
        return None
    return sum(1 for e in refs if str(e.get("ref", "")).split(":")[0] in ("ind", "ret", "news", "research", "regime",
                                                                          "portfolio", "memory")) / len(refs)


def signal_combinations(db: Database, min_n: int = 10) -> dict:
    """Welke combinaties van oordelen hadden voorspellende waarde, en hoe gelijk denken agents?"""
    with db.session() as s:
        rows = s.scalars(select(AgentForecast).where(AgentForecast.resolved_at.is_not(None),
                                                     AgentForecast.phase == "debate")).all()
    per_run: dict[int, dict[str, AgentForecast]] = {}
    for f in rows:
        per_run.setdefault(f.run_id, {})[f.agent] = f
    keys = sorted({f.agent for f in rows})
    pairs = []
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            both = [(r[a], r[b]) for r in per_run.values() if a in r and b in r]
            if not both:
                continue
            agree = sum(1 for x, y in both if _dir(x.stance) == _dir(y.stance)) / len(both)
            joint = [x.realized_return for x, y in both if _dir(x.stance) == _dir(y.stance) == 1]
            row = {"pair": [a, b], "n": len(both), "agreement": agree}
            if len(joint) >= min_n:
                row["joint_bullish_hit_rate"] = sum(1 for r in joint if r > 0) / len(joint)
            pairs.append(row)
    groupthink = stats.mean([p["agreement"] for p in pairs]) if pairs else None
    return {"runs": len(per_run), "pairs": pairs, "mean_agreement": groupthink,
            "note": "boven ~0,8 gemiddelde overeenstemming voegen extra agents weinig onafhankelijke informatie toe"}


def _dir(stance: str) -> int:
    return 1 if stance in BULLISH else (-1 if stance in BEARISH else 0)


def runs(db: Database, limit: int = 20) -> list[dict]:
    with db.session() as s:
        return [_as_dict(r) for r in s.scalars(select(CouncilRun).order_by(CouncilRun.id.desc()).limit(limit))]


__all__ = ["AGENTS", "convene", "math", "resolve_forecasts", "scorecard", "signal_combinations", "weights"]

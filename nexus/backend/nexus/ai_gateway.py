"""NEXUS AI Gateway: één provider-neutrale ingang voor taalmodellen.

    taak → routeringsbeleid → eerste geschikte provider (sleutel, budget, stroomonderbreker) → adapter
         → JSON-antwoord dat het schema volgt → vastgelegd in ``ai_calls``

Regels:
- Rekenwerk (waardering, boekhouding, risicolimieten, ordervalidatie, positiegrootte, statistiek) gaat
  nooit naar een taalmodel. ``complete`` weigert die taken.
- Niet elke vraag naar elk model: per taak een geordende lijst, de eerste die werkt antwoordt.
- Elke provider is optioneel. Ontbreekt een sleutel of modelnaam, dan wordt hij overgeslagen en staat
  dat in het spoor (``trail``). Er wordt niets verzonnen als niemand antwoordt.
- Providers toevoegen of weghalen = één adapter + één regel in ``ADAPTERS``; de rest van de app
  praat alleen met ``complete``.

Alleen de Anthropic-adapter gebruikt de officiële SDK (zoals de Council al deed). OpenAI, Gemini en xAI
gaan via hun HTTP-API; die adapters zijn met opgenomen antwoordvormen getest, niet live (geen sleutels).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from nexus.db import AiCall, Database

DETERMINISTIC_ONLY = {"valuation", "accounting", "risk_limits", "order_validation", "position_sizing",
                      "statistics", "backtest", "pnl"}


@dataclass(frozen=True)
class Policy:
    providers: tuple[str, ...]
    purpose: str
    effort: str = "medium"
    timeout_s: float = 60.0
    max_tokens: int = 4000


DEFAULT_POLICIES: dict[str, Policy] = {
    "research_synthesis": Policy(("anthropic", "openai", "gemini"), "hypothesen en onderzoek samenvatten", "high", 120),
    "independent_challenge": Policy(("openai", "gemini", "xai", "anthropic"),
                                    "aannames aanvallen; bij voorkeur een andere aanbieder dan de auteur", "high", 120),
    "risk_review": Policy(("anthropic", "openai", "gemini"), "neerwaarts risico in woorden; limieten blijven code", "high", 90),
    "news_classification": Policy(("gemini", "openai", "anthropic"), "nieuws labelen naast de vaste regels", "low", 30, 800),
    "financial_document": Policy(("anthropic", "gemini", "openai"), "8-K, persberichten en jaarcijfers lezen", "medium", 90),
    "social_narrative": Policy(("anthropic", "xai", "openai"), "verhaallijnen in sociale data duiden", "medium", 60),
    "executive_report": Policy(("anthropic", "openai"), "briefing formuleren uit vaste feiten", "low", 60),
    "copilot_answer": Policy(("anthropic", "openai", "gemini"), "CEO-vragen beantwoorden met verwijzingen", "low", 60),
    "council_agent": Policy(("anthropic",), "Council-rollen (bestaande opzet)", "medium", 120, 8000),
}


class DeterministicOnly(ValueError):
    """Deze taak is rekenwerk en hoort niet bij een taalmodel."""


class NoProvider(RuntimeError):
    def __init__(self, task: str, trail: list[dict]):
        super().__init__(f"geen provider beschikbaar voor {task}")
        self.trail = trail


# ── Providerconfiguratie (alleen namen van variabelen; waarden blijven in de omgeving) ─────────
@dataclass(frozen=True)
class ProviderConf:
    key: str
    key_env: tuple[str, ...]
    model_env: str | None
    default_model: str | None
    price_env: tuple[str, str] | None
    default_price: tuple[float, float] | None = None
    calls_env: str = ""
    default_calls_per_day: int = 200


def _anthropic_default():
    from nexus import council
    return council.MODEL, (council.PRICE_PER_MTOK["input"], council.PRICE_PER_MTOK["output"])


CONF: dict[str, ProviderConf] = {
    "anthropic": ProviderConf("anthropic", ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"), "NEXUS_ANTHROPIC_MODEL",
                              None, None, None, "NEXUS_ANTHROPIC_MAX_CALLS_PER_DAY"),
    "openai": ProviderConf("openai", ("OPENAI_API_KEY",), "NEXUS_OPENAI_MODEL", None,
                           ("NEXUS_OPENAI_PRICE_IN", "NEXUS_OPENAI_PRICE_OUT"), None, "NEXUS_OPENAI_MAX_CALLS_PER_DAY", 100),
    "gemini": ProviderConf("gemini", ("GEMINI_API_KEY",), "NEXUS_GEMINI_MODEL", None,
                           ("NEXUS_GEMINI_PRICE_IN", "NEXUS_GEMINI_PRICE_OUT"), None, "NEXUS_GEMINI_MAX_CALLS_PER_DAY", 100),
    "xai": ProviderConf("xai", ("XAI_API_KEY",), "NEXUS_XAI_MODEL", None,
                        ("NEXUS_XAI_PRICE_IN", "NEXUS_XAI_PRICE_OUT"), None, "NEXUS_XAI_MAX_CALLS_PER_DAY", 100),
}


def _env(name: str | None) -> str:
    return os.environ.get(name, "").strip() if name else ""


def key_of(p: str) -> str:
    return next((_env(e) for e in CONF[p].key_env if _env(e)), "")


def model_of(p: str) -> str | None:
    c = CONF.get(p)
    if c is None:                    # testaanbieder (bv. de bewust falende in de activatie): geen model
        return None
    if _env(c.model_env):
        return _env(c.model_env)
    if p == "anthropic":
        return _anthropic_default()[0]
    return c.default_model           # bewust geen gegokte modelnaam voor andere aanbieders


def price_of(p: str) -> tuple[float, float] | None:
    c = CONF.get(p)
    if c is None:
        return None
    if p == "anthropic":
        return _anthropic_default()[1]
    if c.price_env and _env(c.price_env[0]) and _env(c.price_env[1]):
        try:
            return float(_env(c.price_env[0])), float(_env(c.price_env[1]))
        except ValueError:
            return None
    return c.default_price


def configured(p: str) -> tuple[bool, str]:
    if p not in CONF:
        return False, "onbekende provider"
    if not key_of(p):
        return False, f"geen sleutel ({' of '.join(CONF[p].key_env)})"
    if not model_of(p):
        return False, f"geen modelnaam ({CONF[p].model_env})"
    return True, "ingesteld"


def describe() -> list[dict]:
    """Overzicht zonder geheimen: per provider of hij bruikbaar is, welk model, welke prijs."""
    out = []
    for p in CONF:
        ok, why = configured(p)
        pr = price_of(p)
        out.append({"provider": p, "usable": ok, "reason": why, "model": model_of(p) if ok else None,
                    "price_per_mtok_usd": {"input": pr[0], "output": pr[1]} if pr else None,
                    "max_calls_per_day": calls_cap(p)})
    return out


def calls_cap(p: str) -> int:
    if p not in CONF:
        return 1
    try:
        return int(_env(CONF[p].calls_env) or CONF[p].default_calls_per_day)
    except ValueError:
        return CONF[p].default_calls_per_day


# ── Adapters: (system, user, schema, effort, timeout, max_tokens, model) → (dict, tokens_in, tokens_out) ─
def _post_json(url: str, body: dict, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "NEXUS-gateway/1.0", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read(5_000_000))


def anthropic_adapter(system, user, schema, effort, timeout, max_tokens, model, client=None):
    from nexus import council
    client = client or council._client()
    if hasattr(client, "with_options"):
        client = client.with_options(timeout=timeout)
    return council._call_full(client, system, user, schema, effort)


def _chat_compatible(base: str, key: str, system, user, schema, timeout, max_tokens, model, post):
    body = {"model": model, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "nexus_output", "schema": schema}}}
    r = post(f"{base}/chat/completions", body, {"Authorization": f"Bearer {key}"}, timeout)
    msg = r["choices"][0]["message"]
    if msg.get("refusal"):
        raise RuntimeError("model weigerde het verzoek")
    if r["choices"][0].get("finish_reason") == "length":
        raise RuntimeError("antwoord afgekapt (max_tokens)")
    u = r.get("usage") or {}
    return (json.loads(msg["content"]), int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0)),
            r.get("model"))


def openai_adapter(system, user, schema, effort, timeout, max_tokens, model, post=_post_json):
    return _chat_compatible("https://api.openai.com/v1", key_of("openai"), system, user, schema, timeout,
                            max_tokens, model, post)


def xai_adapter(system, user, schema, effort, timeout, max_tokens, model, post=_post_json):
    return _chat_compatible("https://api.x.ai/v1", key_of("xai"), system, user, schema, timeout, max_tokens, model, post)


def gemini_adapter(system, user, schema, effort, timeout, max_tokens, model, post=_post_json):
    body = {"systemInstruction": {"parts": [{"text": system + "\nAntwoord uitsluitend met JSON volgens dit schema: "
                                                       + json.dumps(schema)}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": max_tokens}}
    r = post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", body,
             {"x-goog-api-key": key_of("gemini")}, timeout)
    cand = (r.get("candidates") or [{}])[0]
    if cand.get("finishReason") in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT"):
        raise RuntimeError(f"model weigerde ({cand.get('finishReason')})")
    if cand.get("finishReason") == "MAX_TOKENS":
        raise RuntimeError("antwoord afgekapt (max_tokens)")
    text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []))
    u = r.get("usageMetadata") or {}
    return (json.loads(text), int(u.get("promptTokenCount", 0)), int(u.get("candidatesTokenCount", 0)),
            r.get("modelVersion"))


ADAPTERS: dict[str, Callable] = {"anthropic": anthropic_adapter, "openai": openai_adapter,
                                 "gemini": gemini_adapter, "xai": xai_adapter}


# ── Schema-controle (alleen wat nodig is: verplichte velden, typen, enums) ──────────────────────
def validate(out, schema: dict, path: str = "$") -> list[str]:
    errs: list[str] = []
    t = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "number": (int, float), "integer": int, "boolean": bool}
    if t in types and not isinstance(out, types[t]) or (t in ("number", "integer") and isinstance(out, bool)):
        return [f"{path}: verwacht {t}"]
    if "enum" in schema and out not in schema["enum"]:
        errs.append(f"{path}: {out!r} niet toegestaan")
    if t == "object":
        for k in schema.get("required", []):
            if k not in out:
                errs.append(f"{path}.{k}: ontbreekt")
        for k, sub in (schema.get("properties") or {}).items():
            if k in out:
                errs += validate(out[k], sub, f"{path}.{k}")
    if t == "array" and "items" in schema:
        for i, x in enumerate(out):
            errs += validate(x, schema["items"], f"{path}[{i}]")
    if t in ("number", "integer") and isinstance(out, int | float) and (
            "minimum" in schema and out < schema["minimum"] or "maximum" in schema and out > schema["maximum"]):
        errs.append(f"{path}: buiten bereik")
    return errs


# ── De gateway ───────────────────────────────────────────────────────────────────────────────
@dataclass
class Gateway:
    db: Database
    policies: dict[str, Policy] = field(default_factory=lambda: dict(DEFAULT_POLICIES))
    adapters: dict[str, Callable] = field(default_factory=lambda: dict(ADAPTERS))
    is_configured: Callable[[str], tuple[bool, str]] = configured
    breaker_failures: int = 3
    breaker_minutes: int = 15
    budget_override: float | None = None          # alleen voor de budgettest van de activatie

    @classmethod
    def from_env(cls, db: Database) -> Gateway:
        g = cls(db)
        path = _env("NEXUS_AI_ROUTING")
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
            for task, p in raw.items():
                g.policies[task] = Policy(tuple(p["providers"]), p.get("purpose", ""), p.get("effort", "medium"),
                                          float(p.get("timeout_s", 60)), int(p.get("max_tokens", 4000)))
        return g

    # budget en stroomonderbreker uit de vastgelegde aanroepen
    def _today(self, now):
        return now.replace(hour=0, minute=0, second=0, microsecond=0)

    def spent_today(self, now: datetime | None = None) -> float:
        now = now or datetime.now(tz=UTC)
        with self.db.session() as s:
            return float(s.scalar(select(func.coalesce(func.sum(AiCall.cost_usd), 0))
                                  .where(AiCall.created_at >= self._today(now))) or 0)

    def calls_today(self, provider: str, now: datetime | None = None) -> int:
        now = now or datetime.now(tz=UTC)
        with self.db.session() as s:
            return int(s.scalar(select(func.count()).where(AiCall.provider == provider, AiCall.status != "skipped",
                                                            AiCall.created_at >= self._today(now))) or 0)

    def breaker_open(self, provider: str, now: datetime | None = None) -> bool:
        now = now or datetime.now(tz=UTC)
        with self.db.session() as s:
            last = s.scalars(select(AiCall).where(AiCall.provider == provider, AiCall.status != "skipped",
                                                  AiCall.created_at >= now - timedelta(minutes=self.breaker_minutes))
                             .order_by(AiCall.id.desc()).limit(self.breaker_failures)).all()
        return len(last) >= self.breaker_failures and all(c.status == "error" for c in last)

    def budget_left(self, now: datetime | None = None) -> float:
        if self.budget_override is not None:
            return self.budget_override
        from nexus import council
        return council.daily_budget() - council.spent_today(self.db, now) - self.spent_today(now)

    def route(self, task: str, exclude: tuple[str, ...] = (), prefer_not: tuple[str, ...] = ()) -> list[tuple[str, str]]:
        """Volgorde van providers met reden waarom een provider wel/niet in aanmerking komt (zonder aanroep)."""
        if task in DETERMINISTIC_ONLY:
            raise DeterministicOnly(f"{task} is rekenwerk: dat doet NEXUS met vaste code, niet met een taalmodel")
        if task not in self.policies:
            raise KeyError(f"onbekende taak {task!r}")
        order = [p for p in self.policies[task].providers if p not in exclude]
        order = [p for p in order if p not in prefer_not] + [p for p in order if p in prefer_not]
        out = []
        for p in order:
            ok, why = self.is_configured(p)
            if not ok:
                out.append((p, why))
            elif self.breaker_open(p):
                out.append((p, "stroomonderbreker open na herhaalde fouten"))
            elif self.calls_today(p) >= calls_cap(p):
                out.append((p, "daglimiet aantal aanroepen bereikt"))
            else:
                out.append((p, "ok"))
        return out

    def complete(self, task: str, system: str, user: str, schema: dict, *, ref: str | None = None,
                 exclude: tuple[str, ...] = (), prefer_not: tuple[str, ...] = (), now: datetime | None = None) -> dict:
        pol = self.policies.get(task) if task not in DETERMINISTIC_ONLY else None
        trail: list[dict] = []
        h = hashlib.sha256(f"{system}\n{user}".encode()).hexdigest()
        for p, why in self.route(task, exclude, prefer_not):
            if why != "ok":
                trail.append({"provider": p, "status": "skipped", "reason": why})
                continue
            if self.budget_left(now) <= 0:
                trail.append({"provider": p, "status": "skipped", "reason": "dagbudget AI op"})
                break
            model = model_of(p)
            t0 = time.monotonic()
            try:
                res = self.adapters[p](system, user, schema, pol.effort, pol.timeout_s, pol.max_tokens, model)
                out, tin, tout = res[0], res[1], res[2]
                served = (res[3] if len(res) > 3 else None) or model      # het model dat echt antwoordde
                errs = validate(out, schema)
                if errs:
                    raise ValueError("antwoord volgt het schema niet: " + "; ".join(errs[:3]))
                ms = int((time.monotonic() - t0) * 1000)
                pr = price_of(p)
                cost = (tin * pr[0] + tout * pr[1]) / 1e6 if pr else None
                self._log(task, p, served, "ok", ms, tin, tout, cost, None, ref, h)
                trail.append({"provider": p, "status": "ok", "latency_ms": ms})
                return {"output": out, "provider": p, "model": served, "requested_model": model, "latency_ms": ms,
                        "tokens_in": tin,
                        "tokens_out": tout, "cost_usd": cost, "cost_known": pr is not None, "trail": trail}
            except Exception as e:  # noqa: BLE001 - volgende provider proberen, fout vastleggen
                ms = int((time.monotonic() - t0) * 1000)
                msg = _short(e)
                self._log(task, p, model, "error", ms, 0, 0, 0.0, msg, ref, h)
                trail.append({"provider": p, "status": "error", "reason": msg, "latency_ms": ms})
        raise NoProvider(task, trail)

    def _log(self, task, provider, model, status, ms, tin, tout, cost, error, ref, h):
        with self.db.session.begin() as s:
            s.add(AiCall(task=task, provider=provider, model=model, status=status, latency_ms=ms, tokens_in=tin,
                         tokens_out=tout, cost_usd=cost, error=error, ref=ref, prompt_hash=h))


def _short(e: Exception) -> str:
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code}"
    from nexus.providers import _redact
    return _redact(f"{type(e).__name__}: {e}")[:200]


def usage(db: Database, days: int = 30, now: datetime | None = None) -> list[dict]:
    """Gebruik per provider en taak: aanroepen, fouten, mediane latency, kosten."""
    now = now or datetime.now(tz=UTC)
    with db.session() as s:
        rows = s.scalars(select(AiCall).where(AiCall.created_at >= now - timedelta(days=days))).all()
    groups: dict[tuple[str, str], list[AiCall]] = {}
    for r in rows:
        groups.setdefault((r.provider, r.task), []).append(r)
    out = []
    for (p, t), xs in sorted(groups.items()):
        lat = sorted(x.latency_ms for x in xs if x.latency_ms is not None and x.status == "ok")
        out.append({"provider": p, "task": t, "calls": len(xs), "ok": sum(x.status == "ok" for x in xs),
                    "errors": sum(x.status == "error" for x in xs),
                    "median_latency_ms": lat[len(lat) // 2] if lat else None,
                    "cost_usd": sum(float(x.cost_usd or 0) for x in xs),
                    "cost_unknown_calls": sum(1 for x in xs if x.status == "ok" and x.cost_usd is None)})
    return out

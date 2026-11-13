"""Provider Control Center: welke externe bronnen zijn echt bereikbaar, en waarom niet?

Elke bron heeft een vaste, goedkope test (een lijst modellen, één feed, één token). De uitkomst wordt
opgeslagen met een *foutklasse*, zodat "werkt niet" uit elkaar valt in:

- ``credentials_missing``: geen sleutel ingesteld, er is dus ook geen verzoek gedaan
- ``network_blocked``:    de proxy of firewall van deze omgeving weigert de host (CONNECT 403/407)
- ``network_unreachable``: DNS of verbinding mislukt
- ``timeout``:            geen antwoord binnen de tijd
- ``auth_invalid``:       de bron antwoordt 401 (sleutel ontbreekt of is fout)
- ``auth_denied``:        de bron antwoordt 403 (sleutel geldig maar geen recht, of sleutel verplicht)
- ``rate_limited``:       429
- ``invalid_endpoint``:   404/410
- ``provider_outage``:    5xx
- ``parse_error``:        antwoord kwam binnen maar is onleesbaar

Sleutels worden alleen als header meegestuurd en nooit opgeslagen, gelogd of teruggegeven.
"""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from nexus.db import AiCall, Database, ProviderCheck

UA = "NEXUS-provider-check/1.0"


@dataclass(frozen=True)
class Provider:
    key: str
    name: str
    group: str                       # ai, social, onchain, news, market, broker
    host: str
    env: tuple[str, ...] = ()        # benodigde variabelen (namen, nooit waarden)
    probe_url: str | None = None
    auth: str | None = None          # bearer, x-api-key, goog, None
    expects: str = "json"            # json, feed
    note: str = ""
    optional_env: tuple[str, ...] = field(default=())


def _feed_providers() -> list[Provider]:
    from nexus import news
    out = []
    for f in news.FEEDS:
        host = f.url.split("/")[2]
        out.append(Provider(f"news:{f.key}", f.name, "news", host, ("NEXUS_SEC_USER_AGENT",) if f.needs_contact else (),
                            f.url, None, "feed", "officiële RSS/Atom-feed, geen sleutel nodig"))
    return out


PROVIDERS: list[Provider] = [
    Provider("anthropic", "Anthropic Claude", "ai", "api.anthropic.com", ("ANTHROPIC_API_KEY",),
             "https://api.anthropic.com/v1/models?limit=1", "x-api-key", note="Council, Copilot, debat"),
    Provider("openai", "OpenAI", "ai", "api.openai.com", ("OPENAI_API_KEY", "NEXUS_OPENAI_MODEL"),
             "https://api.openai.com/v1/models", "bearer", note="optioneel: tweede mening in het debat"),
    Provider("gemini", "Google Gemini", "ai", "generativelanguage.googleapis.com", ("GEMINI_API_KEY", "NEXUS_GEMINI_MODEL"),
             "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1", "goog",
             note="optioneel: tweede mening in het debat"),
    Provider("xai", "xAI Grok", "ai", "api.x.ai", ("XAI_API_KEY", "NEXUS_XAI_MODEL"),
             "https://api.x.ai/v1/models", "bearer", note="optioneel; los van de Grok-handelsvergelijking"),
    Provider("x_api", "X API v2", "social", "api.x.com", ("X_BEARER_TOKEN",),
             "https://api.x.com/2/tweets/search/recent?query=%24BTC%20-is%3Aretweet&max_results=10", "bearer",
             note="officiële API; eigen abonnement vereist voor zoeken"),
    Provider("goplus", "GoPlus token security", "onchain", "api.gopluslabs.io", (),
             "https://api.gopluslabs.io/api/v1/token_security/1?contract_addresses=0x6982508145454ce325ddbe47a25d4ec3d2311933",
             note="gratis tier zonder sleutel, met limiet"),
    Provider("dexscreener", "DexScreener", "onchain", "api.dexscreener.com", (),
             "https://api.dexscreener.com/latest/dex/tokens/0x6982508145454Ce325dDbE47a25d4ec3d2311933",
             note="openbare API, geen sleutel"),
    Provider("yahoo", "Yahoo Finance (via holding)", "market", "query1.finance.yahoo.com", (),
             "https://query1.finance.yahoo.com/v8/finance/chart/IWDA.AS?range=5d&interval=1d",
             note="de holding verzamelt dagkoersen in GitHub Actions; hier alleen een bereikbaarheidstest"),
    Provider("bitvavo", "Bitvavo (publiek)", "market", "api.bitvavo.com", (), "https://api.bitvavo.com/v2/time",
             note="publieke koersen; geen handelsrechten"),
]


def all_providers() -> list[Provider]:
    return PROVIDERS + _feed_providers()


def missing_env(p: Provider) -> list[str]:
    return [e for e in p.env if not os.environ.get(e, "").strip()]


def _headers(p: Provider) -> dict:
    h = {"User-Agent": UA}
    if p.key.startswith("news:") and "NEXUS_SEC_USER_AGENT" in p.env:
        h["User-Agent"] = os.environ.get("NEXUS_SEC_USER_AGENT", UA)
    key = os.environ.get(p.env[0], "").strip() if p.env else ""
    if p.auth == "bearer":
        h["Authorization"] = f"Bearer {key}"
    elif p.auth == "x-api-key":
        h["x-api-key"], h["anthropic-version"] = key, "2023-06-01"
    elif p.auth == "goog":
        h["x-goog-api-key"] = key
    return h


def classify(exc: BaseException) -> tuple[str, int | None]:
    """Foutklasse en eventuele HTTP-status uit een uitzondering van urllib."""
    if isinstance(exc, urllib.error.HTTPError):
        c = exc.code
        cls = {401: "auth_invalid", 403: "auth_denied", 404: "invalid_endpoint", 410: "invalid_endpoint",
               429: "rate_limited"}.get(c, "provider_outage" if c >= 500 else "http_error")
        return cls, c
    reason = getattr(exc, "reason", exc)
    text = str(reason)
    if "Tunnel connection failed" in text and ("403" in text or "407" in text):
        return "network_blocked", None
    if isinstance(reason, socket.timeout | TimeoutError) or "timed out" in text:
        return "timeout", None
    if isinstance(reason, socket.gaierror) or "Name or service not known" in text or "nodename" in text:
        return "network_unreachable", None
    if isinstance(exc, ValueError | json.JSONDecodeError):
        return "parse_error", None
    return "network_unreachable", None


def _rate(headers) -> dict:
    keys = ("x-ratelimit-remaining", "x-rate-limit-remaining", "x-ratelimit-remaining-requests",
            "anthropic-ratelimit-requests-remaining", "x-rate-limit-reset", "retry-after")
    return {k: headers.get(k) for k in keys if headers is not None and headers.get(k) is not None}


def _default_get(url: str, headers: dict, timeout: float):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, dict(r.headers.items()), r.read(2_000_000)


def probe(p: Provider, getter: Callable = _default_get, timeout: float = 12.0) -> dict:
    """Eén echte test. Zonder verplichte variabelen wordt er niets verstuurd."""
    miss = missing_env(p)
    if miss:
        return {"provider": p.key, "status": "not_configured", "error_class": "credentials_missing",
                "http_status": None, "latency_ms": None, "detail": {"missing": miss, "network": reachability(p, getter)}}
    t0 = time.monotonic()
    try:
        status, headers, body = getter(p.probe_url, _headers(p), timeout)
        ms = int((time.monotonic() - t0) * 1000)
        if p.expects == "feed":
            from nexus import news
            items = news.parse_feed(body.decode("utf-8", errors="replace"))
            detail = {"items": len(items), "newest": max((i["published_at"] for i in items), default=None)}
        else:
            parsed = json.loads(body)
            detail = {"keys": sorted(parsed)[:6] if isinstance(parsed, dict) else "list"}
        detail["rate_limit"] = _rate(headers)
        return {"provider": p.key, "status": "ok", "error_class": None, "http_status": status, "latency_ms": ms,
                "detail": _clean(detail)}
    except Exception as e:  # noqa: BLE001 - elke fout wordt geclassificeerd, nooit opgevuld
        cls, code = classify(e)
        ms = int((time.monotonic() - t0) * 1000)
        hdr = getattr(e, "headers", None)
        return {"provider": p.key, "status": "error", "error_class": cls, "http_status": code, "latency_ms": ms,
                "detail": {"error": _redact(str(e))[:240], "rate_limit": _rate(hdr)}}


def reachability(p: Provider, getter: Callable = _default_get, timeout: float = 8.0) -> str:
    """Zonder sleutel: is de host vanaf hier überhaupt bereikbaar? Een 401/403 van de bron telt als bereikbaar."""
    try:
        getter(p.probe_url, {"User-Agent": UA}, timeout)
        return "reachable"
    except urllib.error.HTTPError:
        return "reachable"
    except Exception as e:  # noqa: BLE001
        return classify(e)[0]


def _clean(d):
    if isinstance(d, datetime):
        return d.isoformat()
    if isinstance(d, dict):
        return {k: _clean(v) for k, v in d.items()}
    return d


def _redact(text: str) -> str:
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY", "X_BEARER_TOKEN"):
        v = os.environ.get(name, "").strip()
        if v and len(v) > 6:
            text = text.replace(v, "***")
    return text


def check_all(db: Database, getter: Callable = _default_get, keys: list[str] | None = None) -> list[dict]:
    out = []
    for p in all_providers():
        if keys and p.key not in keys:
            continue
        r = probe(p, getter)
        with db.session.begin() as s:
            s.add(ProviderCheck(provider=p.key, status=r["status"], error_class=r["error_class"],
                                http_status=r["http_status"], latency_ms=r["latency_ms"], detail=r["detail"]))
        out.append(r)
    return out


EXPLAIN = {
    "credentials_missing": "geen sleutel ingesteld; er is niets verstuurd",
    "network_blocked": "deze omgeving blokkeert de host (proxy); in productie toestaan",
    "network_unreachable": "geen verbinding (DNS of netwerk)",
    "timeout": "geen antwoord binnen de tijd",
    "auth_invalid": "sleutel ontbreekt of is ongeldig (401)",
    "auth_denied": "geen toegang met deze sleutel (403)",
    "rate_limited": "limiet bereikt (429)",
    "invalid_endpoint": "adres bestaat niet (meer)",
    "provider_outage": "storing bij de aanbieder (5xx)",
    "parse_error": "antwoord onleesbaar",
    "http_error": "onverwachte HTTP-fout",
}


def status(db: Database, now: datetime | None = None) -> list[dict]:
    """Per bron: laatste test, laatste geslaagde verzoek, foutklasse, limiet en AI-kosten. Geen sleutels."""
    now = now or datetime.now(tz=UTC)
    rows = []
    with db.session() as s:
        cost = {p: (float(c or 0), n) for p, c, n in s.execute(
            select(AiCall.provider, func.sum(AiCall.cost_usd), func.count()).where(
                AiCall.created_at >= now - timedelta(days=30)).group_by(AiCall.provider))}
        freshness = _freshness(s, now)
        for p in all_providers():
            last = s.scalars(select(ProviderCheck).where(ProviderCheck.provider == p.key)
                             .order_by(ProviderCheck.id.desc())).first()
            ok = s.scalars(select(ProviderCheck).where(ProviderCheck.provider == p.key, ProviderCheck.status == "ok")
                           .order_by(ProviderCheck.id.desc())).first()
            ai_ok = s.scalar(select(func.max(AiCall.created_at)).where(AiCall.provider == p.key, AiCall.status == "ok"))
            last_ok = max([t for t in (ok.checked_at if ok else None, ai_ok) if t is not None],
                          default=None, key=lambda t: t if t.tzinfo else t.replace(tzinfo=UTC))
            miss = missing_env(p)
            fail = s.scalars(select(ProviderCheck).where(ProviderCheck.provider == p.key, ProviderCheck.status == "error")
                             .order_by(ProviderCheck.id.desc())).first()
            recent_err = s.scalar(select(func.count()).select_from(AiCall).where(
                AiCall.provider == p.key, AiCall.status != "ok", AiCall.created_at >= now - timedelta(hours=1))) or 0
            state = classify_state(last, miss, recent_err)
            cls = last.error_class if last else ("credentials_missing" if miss else None)
            rows.append({
                "key": p.key, "name": p.name, "group": p.group, "host": p.host, "note": p.note,
                "required_env": list(p.env), "missing_env": miss, "state": state,
                "last_check": _iso(last.checked_at) if last else None,
                "last_success": _iso(last_ok),
                "last_failure": _iso(fail.checked_at) if fail else None,
                "last_failure_class": fail.error_class if fail else None,
                "freshness": freshness.get(p.key),
                "mode": ("geen sleutel" if miss else "live alleen-lezen" if state in ("CONNECTED", "DEGRADED")
                         else "uitgeschakeld"),
                "error_class": cls, "explain": EXPLAIN.get(cls or "", None),
                "http_status": last.http_status if last else None,
                "latency_ms": last.latency_ms if last else None,
                "rate_limit": (last.detail or {}).get("rate_limit") if last else None,
                "detail": {k: v for k, v in (last.detail or {}).items() if k not in ("rate_limit",)} if last else {},
                "ai_cost_30d_usd": cost.get(p.key, (None, 0))[0], "ai_calls_30d": cost.get(p.key, (None, 0))[1],
            })
    return rows


STATES = ("CONNECTED", "DEGRADED", "DISCONNECTED", "SIMULATED", "NOT CONFIGURED")


def classify_state(last, missing: list[str], recent_errors: int = 0) -> str:
    """Expliciete status. Groen (CONNECTED) alleen na een echte, geslaagde test tegen de aanbieder —
    nooit omdat unit-tests slagen. DEGRADED: wel bereikbaar, maar traag, bijna aan de limiet of recente fouten."""
    if missing:
        return "NOT CONFIGURED"
    if last is None or last.status != "ok":
        return "DISCONNECTED"
    rl = (last.detail or {}).get("rate_limit") or {}
    rem = [int(v) for k, v in rl.items() if k.endswith("remaining") and str(v).isdigit()]
    low = bool(rem) and min(rem) < 5
    if recent_errors >= 2 or (last.latency_ms or 0) > 5000 or low:
        return "DEGRADED"
    return "CONNECTED"


def _freshness(s, now: datetime) -> dict:
    """Leeftijd van de nieuwste échte (niet-fixture) gegevens per nieuwsbron, in uren."""
    from nexus.db import NewsEvent
    out = {}
    for src, ts in s.execute(select(NewsEvent.source, func.max(NewsEvent.fetched_at))
                             .where(NewsEvent.source_kind != "fixture").group_by(NewsEvent.source)):
        if ts is None:
            continue
        ts = ts if ts.tzinfo else ts.replace(tzinfo=UTC)
        out[f"news:{src}"] = {"newest": ts.isoformat(), "age_hours": round((now - ts).total_seconds() / 3600, 1),
                              "stale": now - ts > timedelta(hours=24)}
    return out


def simulated_services() -> list[dict]:
    """Diensten die bewust niet echt zijn: zo staat het er, in plaats van een groene status."""
    return [
        {"key": "paper_broker", "name": "Papieren broker", "group": "uitvoering", "state": "SIMULATED",
         "mode": "papier: geen echt geld", "note": "alle orders zijn gesimuleerd"},
        {"key": "live_broker", "name": "Echte broker", "group": "uitvoering", "state": "NOT CONFIGURED",
         "mode": "uit (live trading staat UIT)", "note": "bewust niet gekoppeld; vereist CEO-besluit en Risk Guardian"},
    ]


def _iso(d):
    return None if d is None else (d if d.tzinfo else d.replace(tzinfo=UTC)).isoformat()

"""Social Intelligence en Meme Coin Radar: X (officiële API), on-chain veiligheid, sociale momentum.

Bronnen, alleen via toegestane API's:
- X API v2 ``tweets/search/recent`` met een eigen Bearer-token (``X_BEARER_TOKEN``). Geen scraping. Zonder
  token: status ``not_connected`` en geen enkel getal. Limieten (429) worden gerespecteerd en gemeld.
- DexScreener (openbare API): liquiditeit, volume, leeftijd van het handelspaar.
- GoPlus Security (openbare API): honeypot, belastingen, eigenaarsrechten, houderconcentratie.

Een stijging in vermeldingen is geen koopsignaal. Een token dat een verplichte controle niet haalt,
krijgt nooit een handelsvoorstel. Wat hier staat zijn onderzoekssignalen.
"""

from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from nexus import stats
from nexus.db import Database, SocialSnapshot, TokenCheck

# ── Bekende tokens op de watchlist (contract op Ethereum; DOGE is een eigen keten) ─────────
@dataclass(frozen=True)
class Token:
    symbol: str               # instrument in de holding (koersen van Bitvavo)
    cashtag: str
    chain: str | None         # GoPlus chain id ("1" = Ethereum) of None voor een eigen keten
    address: str | None


WATCHLIST = [
    Token("DOGE-EUR", "DOGE", None, None),
    Token("SHIB-EUR", "SHIB", "1", "0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE"),
    Token("PEPE-EUR", "PEPE", "1", "0x6982508145454Ce325dDbE47a25d4ec3d2311933"),
]

# Verplichte controles. Eén ``fail`` of ``unavailable`` = geen voorstel.
MIN_LIQUIDITY_USD = 250_000
MIN_AGE_DAYS = 7
MAX_SELL_TAX = 0.10
MAX_TOP10_SHARE = 0.50

UA = "NEXUS-research/1.0"


class SourceUnavailable(Exception):
    pass


def _get(url: str, headers: dict | None = None, timeout: float = 20.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:        # noqa: S310 - vaste https-API's
            return json.loads(r.read(5_000_000))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise SourceUnavailable(f"limiet bereikt (429), opnieuw na {e.headers.get('x-rate-limit-reset', '?')}") from e
        raise SourceUnavailable(f"HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SourceUnavailable(str(e)[:200]) from e


# ── X (officiële API) ───────────────────────────────────────────────────────────────────────
def x_status() -> dict:
    tok = os.environ.get("X_BEARER_TOKEN", "").strip()
    return {"source": "x_api_v2", "connected": bool(tok),
            "detail": "Bearer-token aanwezig" if tok else "niet verbonden: zet X_BEARER_TOKEN (eigen X API-abonnement)"}


def x_search(query: str, getter=_get, max_results: int = 100) -> dict:
    """Recente openbare posts. Geeft posts + auteurs; gooit ``SourceUnavailable`` als er geen toegang is."""
    tok = os.environ.get("X_BEARER_TOKEN", "").strip()
    if not tok:
        raise SourceUnavailable("X niet verbonden (geen X_BEARER_TOKEN)")
    q = urllib.parse.urlencode({"query": f"{query} -is:retweet lang:en", "max_results": max(10, min(100, max_results)),
                                "tweet.fields": "created_at,public_metrics,author_id",
                                "expansions": "author_id", "user.fields": "created_at,public_metrics,verified"})
    d = getter(f"https://api.x.com/2/tweets/search/recent?{q}", {"Authorization": f"Bearer {tok}"})
    users = {u["id"]: u for u in (d.get("includes") or {}).get("users", [])}
    return {"posts": d.get("data", []), "users": users}


_URL = re.compile(r"https?://\S+|@\w+|\$\w+|#\w+")
POS = {"moon", "bullish", "pump", "send", "breakout", "buy", "long", "ath", "gem", "rally"}
NEG = {"dump", "rug", "scam", "bearish", "sell", "short", "crash", "honeypot", "exit", "rekt"}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", _URL.sub("", text.lower())).strip()


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def momentum(posts: list[dict], users: dict, now: datetime) -> dict:
    """Meetbare kenmerken van de discussie. Sentiment is een ruw woordenlijstje en zo gelabeld."""
    if not posts:
        return {"mentions": 0}
    times = sorted(_ts(p["created_at"]) for p in posts)
    hours = max(1 / 60, (max(times[-1], now) - times[0]).total_seconds() / 3600)
    authors = Counter(p.get("author_id") for p in posts)
    texts = Counter(_norm(p.get("text", "")) for p in posts)
    dup = sum(c for t, c in texts.items() if t and c >= 3)
    eng = sum(sum((p.get("public_metrics") or {}).get(k, 0) for k in ("like_count", "retweet_count", "reply_count",
                                                                      "quote_count")) for p in posts)
    new_acc = low_f = 0
    for a in authors:
        u = users.get(a) or {}
        if u.get("created_at") and (now - _ts(u["created_at"])).days < 30:
            new_acc += 1
        if (u.get("public_metrics") or {}).get("followers_count", 0) < 50:
            low_f += 1
    words = [w for p in posts for w in re.findall(r"[a-z]+", p.get("text", "").lower())]
    pos, neg = sum(w in POS for w in words), sum(w in NEG for w in words)
    n, na = len(posts), max(1, len(authors))
    coord = dup / n
    bot = 0.5 * coord + 0.3 * new_acc / na + 0.2 * low_f / na
    return {"mentions": n, "unique_authors": len(authors), "mentions_per_hour": n / hours,
            "engagement": eng, "engagement_per_post": eng / n, "top_author_share": authors.most_common(1)[0][1] / n,
            "duplicate_text_share": coord, "new_account_share": new_acc / na, "low_follower_share": low_f / na,
            "bot_risk": round(min(1.0, bot), 3),
            "sentiment_lexicon": (pos - neg) / max(1, pos + neg), "sentiment_note": "ruwe woordenlijst, geen model",
            "first": times[0].isoformat(), "last": times[-1].isoformat()}


def with_baseline(db: Database, topic: str, m: dict, min_history: int = 5) -> dict:
    """Vergelijk met eerdere metingen van hetzelfde onderwerp (z-score van vermeldingen per uur)."""
    with db.session() as s:
        hist = [x.metrics.get("mentions_per_hour") for x in s.scalars(
            select(SocialSnapshot).where(SocialSnapshot.topic == topic).order_by(SocialSnapshot.id.desc()).limit(48))]
    hist = [h for h in hist if h is not None]
    if len(hist) < min_history or not m.get("mentions"):
        return {**m, "baseline": {"available": False, "history": len(hist), "needed": min_history}}
    mu, sd = stats.mean(hist), stats.stdev(hist)
    z = (m["mentions_per_hour"] - mu) / sd if sd > 0 else None
    return {**m, "baseline": {"available": True, "history": len(hist), "mean": mu, "z": z,
                              "unusual": z is not None and z > 3}}


def snapshot(db: Database, token: Token, getter=_get, now: datetime | None = None) -> dict:
    now = now or datetime.now(tz=UTC)
    try:
        d = x_search(f"${token.cashtag}", getter=getter)
    except SourceUnavailable as e:
        return {"topic": f"${token.cashtag}", "status": "unavailable", "error": str(e)}
    m = with_baseline(db, f"${token.cashtag}", momentum(d["posts"], d["users"], now))
    with db.session.begin() as s:
        s.add(SocialSnapshot(topic=f"${token.cashtag}", source="x_api_v2", window_start=now - timedelta(days=7),
                             window_end=now, metrics=json.loads(json.dumps(m, default=str))))
    return {"topic": f"${token.cashtag}", "status": "ok", "metrics": m}


# ── On-chain veiligheid ─────────────────────────────────────────────────────────────────────
def _f(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def assess(goplus: dict | None, dex: dict | None, now: datetime) -> tuple[str, list[dict], dict]:
    """Verplichte controles uit GoPlus- en DexScreener-gegevens. Ontbrekende data telt als niet geslaagd."""
    checks: list[dict] = []

    def add(key, label, ok, value=None, threshold=None):
        checks.append({"key": key, "label": label, "status": "unavailable" if ok is None else ("pass" if ok else "fail"),
                       "value": value, "threshold": threshold})

    g = goplus or {}
    add("honeypot", "Geen honeypot (verkopen mogelijk)", None if "is_honeypot" not in g else g["is_honeypot"] == "0",
        g.get("is_honeypot"))
    st = _f(g.get("sell_tax"))
    add("sell_tax", "Verkoopbelasting", None if st is None else st <= MAX_SELL_TAX, st, f"≤ {MAX_SELL_TAX:.0%}")
    add("open_source", "Contractcode openbaar", None if "is_open_source" not in g else g["is_open_source"] == "1",
        g.get("is_open_source"))
    add("transfer_pause", "Overdracht niet te pauzeren", None if "transfer_pausable" not in g else g["transfer_pausable"] != "1",
        g.get("transfer_pausable"))
    owner_risk = [k for k in ("hidden_owner", "can_take_back_ownership", "owner_change_balance") if g.get(k) == "1"]
    add("owner_powers", "Geen verborgen eigenaarsmacht",
        None if not any(k in g for k in ("hidden_owner", "can_take_back_ownership")) else not owner_risk, owner_risk)
    holders = g.get("holders") or []
    lp = {(h.get("address") or "").lower() for h in g.get("lp_holders") or []}
    top = [h for h in holders if (h.get("address") or "").lower() not in lp and h.get("is_locked") != 1][:10]
    share = sum(_f(h.get("percent")) or 0 for h in top) if holders else None
    add("concentration", "Top-10 houders (zonder LP)", None if share is None else share <= MAX_TOP10_SHARE, share,
        f"≤ {MAX_TOP10_SHARE:.0%}")
    pairs = (dex or {}).get("pairs") or []
    best = max(pairs, key=lambda p: (_f((p.get("liquidity") or {}).get("usd")) or 0), default=None)
    liq = _f((best or {}).get("liquidity", {}).get("usd")) if best else None
    add("liquidity", "Liquiditeit grootste pool", None if liq is None else liq >= MIN_LIQUIDITY_USD, liq,
        f"≥ ${MIN_LIQUIDITY_USD:,.0f}")
    created = (best or {}).get("pairCreatedAt")
    age = (now - datetime.fromtimestamp(created / 1000, tz=UTC)).days if created else None
    add("age", "Leeftijd handelspaar", None if age is None else age >= MIN_AGE_DAYS, age, f"≥ {MIN_AGE_DAYS} dagen")
    market = {}
    if best:
        market = {"dex": best.get("dexId"), "pair": best.get("pairAddress"), "price_usd": _f(best.get("priceUsd")),
                  "liquidity_usd": liq, "volume_24h_usd": _f((best.get("volume") or {}).get("h24")),
                  "price_change_24h": _f((best.get("priceChange") or {}).get("h24")),
                  "txns_24h": (best.get("txns") or {}).get("h24"), "age_days": age,
                  # Constant-product pool: ~1% koersimpact bij een order van 1% van één kant van de pool.
                  "max_order_1pct_impact_usd": 0.01 * liq / 2 if liq else None}
    status = "pass" if all(c["status"] == "pass" for c in checks) else (
        "fail" if any(c["status"] == "fail" for c in checks) else "unavailable")
    return status, checks, market


def check_token(db: Database, token: Token, getter=_get, now: datetime | None = None) -> dict:
    now = now or datetime.now(tz=UTC)
    if token.address is None:
        return {"symbol": token.symbol, "status": "not_applicable",
                "detail": "eigen blockchain, geen tokencontract: contractcontroles gelden niet; handel via Bitvavo"}
    sources, gp, dx = [], None, None
    try:
        r = getter(f"https://api.gopluslabs.io/api/v1/token_security/{token.chain}?contract_addresses={token.address}")
        gp = (r.get("result") or {}).get(token.address.lower())
        sources.append({"source": "goplus", "status": "ok" if gp else "empty"})
    except SourceUnavailable as e:
        sources.append({"source": "goplus", "status": "unavailable", "error": str(e)})
    try:
        dx = getter(f"https://api.dexscreener.com/latest/dex/tokens/{token.address}")
        sources.append({"source": "dexscreener", "status": "ok"})
    except SourceUnavailable as e:
        sources.append({"source": "dexscreener", "status": "unavailable", "error": str(e)})
    status, checks, market = assess(gp, dx, now)
    with db.session.begin() as s:
        row = TokenCheck(chain=token.chain or "", address=token.address, symbol=token.symbol, status=status,
                         checks=checks, market=market, sources=sources, checked_at=now)
        s.add(row)
        s.flush()
        rid = row.id
    return {"id": rid, "symbol": token.symbol, "status": status, "checks": checks, "market": market, "sources": sources}


def tradeable(db: Database, symbol: str) -> tuple[bool, str]:
    """Mag er voor dit meme-instrument een voorstel komen? Alleen met een recente geslaagde controle."""
    tok = next((t for t in WATCHLIST if t.symbol == symbol), None)
    if tok is None or tok.address is None:
        return True, "geen tokencontract (eigen keten)"
    with db.session() as s:
        c = s.scalars(select(TokenCheck).where(TokenCheck.address == tok.address).order_by(TokenCheck.id.desc())).first()
    if c is None:
        return False, "nog geen veiligheidscontrole"
    checked = c.checked_at if c.checked_at.tzinfo else c.checked_at.replace(tzinfo=UTC)
    if datetime.now(tz=UTC) - checked > timedelta(days=1):
        return False, "veiligheidscontrole ouder dan 24 uur"
    return (c.status == "pass"), f"veiligheidscontrole: {c.status}"


# ── Leidt sociaal de koers? ─────────────────────────────────────────────────────────────────
def lead_lag(social: list[float], returns: list[float], max_lag: int = 6) -> dict:
    """Kruiscorrelatie per vertraging. Positief = sociaal vóór de koers. Met een ruwe 95%-grens."""
    n = min(len(social), len(returns))
    if n < 30:
        return {"available": False, "reason": f"te weinig gelijktijdige punten ({n} < 30)"}
    x, y = social[-n:], returns[-n:]

    def corr(a, b):
        ma, mb = stats.mean(a), stats.mean(b)
        sa, sb = stats.stdev(a), stats.stdev(b)
        if sa == 0 or sb == 0:
            return 0.0
        return sum((p - ma) * (q - mb) for p, q in zip(a, b)) / ((len(a) - 1) * sa * sb)
    rows = []
    for k in range(-max_lag, max_lag + 1):
        a, b = (x[:n - k], y[k:]) if k >= 0 else (x[-k:], y[:n + k])
        rows.append({"lag": k, "corr": corr(a, b), "n": len(a)})
    bound = 1.96 / math.sqrt(n)
    best = max(rows, key=lambda r: abs(r["corr"]))
    if abs(best["corr"]) < bound:
        kind = "none"
    elif best["lag"] > 0:
        kind = "predictive"
    elif best["lag"] == 0:
        kind = "coincident"
    else:
        kind = "lagging"
    return {"available": True, "n": n, "bound95": bound, "best": best, "classification": kind, "lags": rows,
            "note": "correlatie, geen oorzaak; na kosten en liquiditeit pas iets waard als het buiten de steekproef standhoudt"}


def influencer_scores(statements: list[dict], candles_of: dict, horizon: int = 3, min_n: int = 10) -> list[dict]:
    """Trefkans van publieke uitspraken (account, symbool, tijd, richting) na ``horizon`` periodes."""
    by: dict[str, list[dict]] = {}
    for st in statements:
        c = candles_of.get(st["symbol"]) or []
        i = next((k for k, x in enumerate(c) if x.ts >= st["ts"]), None)
        if i is None or i + horizon >= len(c):
            continue
        r = c[i + horizon].close / c[i].close - 1
        by.setdefault(st["account"], []).append({"ret": r, "hit": (r > 0) == (st["direction"] > 0)})
    out = []
    for acc, xs in by.items():
        hits = sum(x["hit"] for x in xs)
        out.append({"account": acc, "n": len(xs), "hit_rate": hits / len(xs),
                    "mean_return_after": stats.mean([x["ret"] for x in xs]),
                    "reliable": len(xs) >= min_n,
                    "note": "populariteit is geen bewijs; pas vanaf 10 afgerekende uitspraken een oordeel"})
    return sorted(out, key=lambda r: -r["n"])


def radar(db: Database, prices: dict | None = None) -> dict:
    """Alles voor de Meme Coin Radar, uit opgeslagen metingen. ``prices``: symbool → laatste dagkoersen."""
    out = []
    with db.session() as s:
        for t in WATCHLIST:
            soc = s.scalars(select(SocialSnapshot).where(SocialSnapshot.topic == f"${t.cashtag}")
                            .order_by(SocialSnapshot.id.desc())).first()
            chk = s.scalars(select(TokenCheck).where(TokenCheck.address == (t.address or "-"))
                            .order_by(TokenCheck.id.desc())).first() if t.address else None
            c = (prices or {}).get(t.symbol) or []
            px = None
            if len(c) >= 8:
                px = {"last": c[-1].close, "ts": c[-1].ts.isoformat(), "ret_1d": c[-1].close / c[-2].close - 1,
                      "ret_7d": c[-1].close / c[-8].close - 1, "volume_change": c[-1].volume / max(1e-9, stats.mean(
                          [x.volume for x in c[-8:-1]])) - 1, "label": "DELAYED"}
            out.append({"symbol": t.symbol, "cashtag": t.cashtag, "chain": t.chain, "address": t.address,
                        "price": px,
                        "social": {"status": "ok", "at": soc.created_at.isoformat(), **soc.metrics} if soc else
                                  {"status": "not_connected" if not x_status()["connected"] else "no_data"},
                        "safety": ({"status": chk.status, "checks": chk.checks, "market": chk.market,
                                    "sources": chk.sources, "at": chk.checked_at.isoformat()} if chk else
                                   {"status": "not_applicable" if t.address is None else "not_checked"}),
                        "tradeable": tradeable(db, t.symbol)})
    return {"x": x_status(), "tokens": out,
            "rule": "Onderzoekssignalen, geen handelsadvies. Zonder geslaagde veiligheidscontrole nooit een voorstel."}

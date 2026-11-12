"""Nieuwsinformatie: officiële bronnen, publicatietijd, betrokken markten en de koersreactie daarna.

Per gebeurtenis:
1. bron (en soort bron: officieel, beurs, media)       5. verwachting (alleen als er een bron voor is)
2. publicatietijd (van de bron, in UTC)                 6. mogelijke gevolgen (Council, optioneel)
3. betrokken instrumenten (vaste regels, controleerbaar) 7. koersreactie: +1 periode, +1 dag, +5 dagen
4. feit of speculatie                                   8. opgeslagen voor event-onderzoek

Alleen bronnen die openbaar en voor dit gebruik toegestaan zijn: persberichten van centrale banken
en toezichthouders, statistiekbureaus en verplichte bedrijfsmeldingen (SEC EDGAR). Geen scraping
van betaalde nieuwssites. Een bron die faalt geeft UNAVAILABLE; er wordt niets ingevuld.

Positief nieuws is niet automatisch een stijging: de event-study meet per categorie en instrument
wat er daarna echt gebeurde, met de normale beweeglijkheid als maatstaf.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

from jplh.models import Candle
from sqlalchemy import select

from nexus import stats
from nexus.db import Database, NewsEvent


@dataclass(frozen=True)
class Feed:
    key: str
    name: str
    url: str
    kind: str                     # official, exchange, media
    default_assets: tuple[str, ...]
    needs_contact: bool = False   # SEC vraagt een contact in de User-Agent


FEEDS = [
    Feed("fed", "Federal Reserve (persberichten)", "https://www.federalreserve.gov/feeds/press_all.xml", "official",
         ("EURUSD=X", "GC=F", "BTC-EUR", "IWDA.AS")),
    Feed("ecb", "Europese Centrale Bank (pers)", "https://www.ecb.europa.eu/rss/press.html", "official",
         ("EURUSD=X", "EURGBP=X", "EURCHF=X", "EURJPY=X", "IWDA.AS", "IEAG.AS")),
    Feed("bls", "US Bureau of Labor Statistics", "https://www.bls.gov/feed/bls_latest.rss", "official",
         ("EURUSD=X", "GC=F", "IWDA.AS")),
    Feed("sec_press", "SEC (persberichten)", "https://www.sec.gov/news/pressreleases.rss", "official",
         (), needs_contact=True),
    Feed("edgar_aapl", "SEC EDGAR 8-K Apple", "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000320193"
         "&type=8-K&dateb=&owner=include&count=20&output=atom", "official", ("AAPL",), needs_contact=True),
    Feed("edgar_msft", "SEC EDGAR 8-K Microsoft", "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000789019"
         "&type=8-K&dateb=&owner=include&count=20&output=atom", "official", ("MSFT",), needs_contact=True),
    Feed("edgar_nvda", "SEC EDGAR 8-K NVIDIA", "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001045810"
         "&type=8-K&dateb=&owner=include&count=20&output=atom", "official", ("NVDA",), needs_contact=True),
]

# Categorie → trefwoorden (kleine letters). Volgorde telt: de eerste treffer wint.
CATEGORIES = [
    ("rate_decision", ("federal funds rate", "monetary policy decision", "interest rates", "fomc statement",
                       "key ecb interest rates", "rate decision")),
    ("inflation", ("consumer price index", "cpi", "inflation", "hicp", "producer price")),
    ("employment", ("employment situation", "nonfarm", "unemployment", "jobs report", "payroll")),
    ("earnings", ("results of operations", "item 2.02", "quarterly results", "earnings", "financial results")),
    ("etf", (" etf", "exchange-traded", "spot bitcoin", "spot ether")),
    ("crypto_regulation", ("crypto", "digital asset", "mica", "stablecoin", "bitcoin", "token")),
    ("security_incident", ("hack", "exploit", "breach", "stolen", "vulnerability")),
    ("listing", ("listing", "delisting", "listed on")),
    ("regulation", ("enforcement", "charges", "rule", "regulation", "supervisory", "sanction")),
    ("financial_stability", ("financial stability", "stress test", "bank failure", "liquidity facility")),
    ("speech", ("speech", "remarks", "testimony", "interview")),
]
CATEGORY_ASSETS = {
    "crypto_regulation": ("BTC-EUR", "ETH-EUR", "SOL-EUR", "XRP-EUR"),
    "etf": ("BTC-EUR", "ETH-EUR"),
    "security_incident": ("BTC-EUR", "ETH-EUR"),
}
SPECULATIVE = re.compile(r"\b(may|might|could|reportedly|rumou?r|sources say|expected to|considering|plans? to|"
                         r"speculat\w*|possible|potential)\b", re.I)


def classify(title: str, summary: str, feed: Feed) -> tuple[str, tuple[str, ...], str]:
    text = f" {title} {summary} ".lower()
    cat = next((c for c, words in CATEGORIES if any(w in text for w in words)), "other")
    assets = tuple(dict.fromkeys(feed.default_assets + CATEGORY_ASSETS.get(cat, ())))
    spec = bool(SPECULATIVE.search(title))
    if feed.kind == "official":
        fact = "fact" if not spec else "mixed"        # officieel bericht; vooruitblikken blijven 'mixed'
    else:
        fact = "speculation" if spec else "mixed"
    return cat, assets, fact


def _text(el, *names) -> str:
    for n in names:
        x = el.find(n)
        if x is not None:
            if x.text and x.text.strip():
                return x.text.strip()
            if x.get("href"):
                return x.get("href")
    return ""


def _when(s: str) -> datetime | None:
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d.astimezone(UTC) if d.tzinfo else d.replace(tzinfo=UTC)


def parse_feed(xml: str) -> list[dict]:
    """RSS 2.0 en Atom. Geeft titel, link, samenvatting, publicatietijd."""
    root = ET.fromstring(xml)
    atom = "{http://www.w3.org/2005/Atom}"
    out = []
    items = root.iter("item") if root.find(".//item") is not None else root.iter(f"{atom}entry")
    for it in items:
        if it.tag == "item":
            title, link = _text(it, "title"), _text(it, "link")
            summary, when = _text(it, "description"), _when(_text(it, "pubDate", "{http://purl.org/dc/elements/1.1/}date"))
        else:
            title, summary = _text(it, f"{atom}title"), _text(it, f"{atom}summary", f"{atom}content")
            link_el = it.find(f"{atom}link")
            link = link_el.get("href") if link_el is not None else ""
            when = _when(_text(it, f"{atom}updated", f"{atom}published"))
        if title and when:
            out.append({"title": re.sub(r"\s+", " ", title)[:500], "url": link[:1000],
                        "summary": re.sub(r"<[^>]+>", " ", summary)[:2000].strip(), "published_at": when})
    return out


def fetch(feed: Feed, timeout: float = 20.0) -> str:
    ua = "NEXUS-research/1.0"
    if feed.needs_contact:
        contact = os.environ.get("NEXUS_SEC_USER_AGENT", "").strip()
        if not contact:
            raise RuntimeError("SEC vraagt een contact in de User-Agent: zet NEXUS_SEC_USER_AGENT")
        ua = contact
    req = urllib.request.Request(feed.url, headers={"User-Agent": ua, "Accept": "application/rss+xml, application/atom+xml, text/xml"})
    with urllib.request.urlopen(req, timeout=timeout) as r:       # noqa: S310 - vaste https-bronnen
        return r.read(5_000_000).decode("utf-8", errors="replace")


def ingest(db: Database, feeds: list[Feed] | None = None, fetcher=fetch, now: datetime | None = None) -> dict:
    """Haalt alle feeds op. Per bron: aantal nieuw, of UNAVAILABLE met de fout."""
    now = now or datetime.now(tz=UTC)
    report = {}
    for feed in feeds or FEEDS:
        try:
            items = parse_feed(fetcher(feed))
        except Exception as e:  # noqa: BLE001 - per bron melden, nooit opvullen
            report[feed.key] = {"status": "UNAVAILABLE", "error": str(e)[:300]}
            continue
        new = 0
        with db.session.begin() as s:
            for it in items:
                if it["published_at"] > now + timedelta(minutes=5):
                    continue                                    # tijd in de toekomst: niet vertrouwen
                h = hashlib.sha256(f"{feed.key}|{it['url']}|{it['title']}".encode()).hexdigest()
                if s.scalar(select(NewsEvent.id).where(NewsEvent.content_hash == h)):
                    continue
                cat, assets, fact = classify(it["title"], it["summary"], feed)
                s.add(NewsEvent(source=feed.key, source_kind=feed.kind, url=it["url"], title=it["title"],
                                summary=it["summary"] or None, published_at=it["published_at"], fetched_at=now,
                                category=cat, assets=list(assets), factuality=fact,
                                expectation={"available": False, "reason": "geen bron voor marktverwachtingen gekoppeld"},
                                content_hash=h))
                new += 1
        report[feed.key] = {"status": "ok", "items": len(items), "new": new}
    return report


# ── Koersreactie en event-study ────────────────────────────────────────────────────────────
def reaction(candles: list[Candle], at: datetime, horizons: dict[str, timedelta]) -> dict | None:
    """Rendement vanaf de laatste slotkoers vóór publicatie, gemeten in eenheden normale beweeglijkheid."""
    before = [c for c in candles if c.ts + _step(candles) <= at]
    if len(before) < 30:
        return None
    p0 = before[-1].close
    rets = [b.close / a.close - 1 for a, b in zip(before[-61:], before[-60:])]
    sd = stats.stdev(rets)
    step = _step(candles)
    out = {"base_ts": before[-1].ts.isoformat(), "base_price": p0, "per_period_vol": sd}
    for name, h in horizons.items():
        after = [c for c in candles if c.ts + step <= at + h and c.ts > before[-1].ts]
        if not after or after[-1].ts + step < at + h - step:
            out[name] = None
            continue
        r = after[-1].close / p0 - 1
        periods = max(1, len(after))
        out[name] = {"return": r, "z": r / (sd * math.sqrt(periods)) if sd > 0 else None}
    return out


def _step(c: list[Candle]) -> timedelta:
    return min((b.ts - a.ts for a, b in zip(c, c[1:])), default=timedelta(days=1))


def track_reactions(db: Database, candles_of: dict[str, dict[str, list[Candle]]]) -> int:
    """``candles_of[symbol][interval]``. Vult de reactie in zodra de horizon voorbij is."""
    n = 0
    with db.session.begin() as s:
        for ev in s.scalars(select(NewsEvent)):
            pub = ev.published_at if ev.published_at.tzinfo else ev.published_at.replace(tzinfo=UTC)
            reac = dict(ev.reaction or {})
            changed = False
            for sym in ev.assets or []:
                if sym in reac and all(reac[sym].get(k) is not None for k in ("d1", "d5")):
                    continue
                daily = candles_of.get(sym, {}).get("1d", [])
                hourly = candles_of.get(sym, {}).get("1h", [])
                r = {}
                if hourly:
                    h = reaction(hourly, pub, {"h1": timedelta(hours=1), "h4": timedelta(hours=4)})
                    if h:
                        r.update({"h1": h["h1"], "h4": h["h4"]})
                if daily:
                    d = reaction(daily, pub, {"d1": timedelta(days=1), "d5": timedelta(days=7)})
                    if d:
                        r.update({"d1": d["d1"], "d5": d["d5"], "base_ts": d["base_ts"]})
                if r:
                    reac[sym] = r
                    changed = True
            if changed:
                ev.reaction = reac
                n += 1
    return n


def event_study(db: Database, min_events: int = 8) -> list[dict]:
    """Per categorie en instrument: gemiddelde reactie in standaarddeviaties, richting en spreiding."""
    groups: dict[tuple[str, str], list[float]] = {}
    with db.session() as s:
        for ev in s.scalars(select(NewsEvent)):
            for sym, r in (ev.reaction or {}).items():
                d1 = (r or {}).get("d1")
                if d1 and d1.get("z") is not None:
                    groups.setdefault((ev.category, sym), []).append(d1["z"])
    out = []
    for (cat, sym), zs in sorted(groups.items()):
        n = len(zs)
        row = {"category": cat, "symbol": sym, "events": n, "mean_z": stats.mean(zs),
               "share_up": sum(1 for z in zs if z > 0) / n, "abs_mean_z": stats.mean([abs(z) for z in zs])}
        if n >= min_events:
            se = stats.stdev(zs) / math.sqrt(n)
            row["mean_z_ci95"] = [row["mean_z"] - 1.96 * se, row["mean_z"] + 1.96 * se]
            row["conclusion"] = ("gemiddeld een grotere beweging dan normaal" if row["abs_mean_z"] > 1.2 else
                                 "geen grotere beweging dan normaal")
        else:
            row["conclusion"] = f"te weinig gebeurtenissen (minstens {min_events})"
        out.append(row)
    return out


def latest(db: Database, limit: int = 50, category: str | None = None) -> list[dict]:
    with db.session() as s:
        q = select(NewsEvent).order_by(NewsEvent.published_at.desc()).limit(limit)
        if category:
            q = q.where(NewsEvent.category == category)
        return [{"id": e.id, "source": e.source, "source_kind": e.source_kind, "title": e.title, "url": e.url,
                 "published_at": (e.published_at if e.published_at.tzinfo else e.published_at.replace(tzinfo=UTC)).isoformat(),
                 "category": e.category, "assets": e.assets, "factuality": e.factuality, "expectation": e.expectation,
                 "analysis": e.analysis, "reaction": e.reaction} for e in s.scalars(q)]

"""DexScreener-radar voor memecoins. ALLEEN kijken, nooit handelen.

Nieuwe memecoins op decentrale beurzen zijn vaak oplichting (rug pulls, honeypots).
De radar slaat momentopnames op zodat het onderzoekslab kan leren welke kenmerken
(liquiditeit, leeftijd, volume) bij munten horen die later instortten of bleven bestaan.

Endpoint: ``GET https://api.dexscreener.com/latest/dex/search?q={zoekterm}``
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from datetime import UTC, datetime

from jplh.data.http import get_json

BASE_URL = "https://api.dexscreener.com"


@dataclass(frozen=True)
class PairSnapshot:
    chain: str
    pair_address: str
    base_symbol: str
    price_usd: float
    liquidity_usd: float
    volume_24h_usd: float
    price_change_24h_pct: float
    created_at: datetime | None

    def age_days(self, now: datetime) -> float | None:
        return None if self.created_at is None else (now - self.created_at).total_seconds() / 86400

    def red_flags(self, now: datetime) -> list[str]:
        """Eenvoudige waarschuwingen. Geen flags betekent NIET dat een munt veilig is."""
        flags = []
        if self.liquidity_usd < 50_000:
            flags.append("weinig liquiditeit (< $50k)")
        age = self.age_days(now)
        if age is not None and age < 7:
            flags.append("jonger dan 7 dagen")
        if self.liquidity_usd > 0 and self.volume_24h_usd / self.liquidity_usd > 20:
            flags.append("volume > 20x liquiditeit (mogelijk wash trading)")
        if abs(self.price_change_24h_pct) > 100:
            flags.append("koers >100% bewogen in 24 uur")
        return flags


def _f(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def parse_pairs(payload: dict) -> list[PairSnapshot]:
    out = []
    for p in payload.get("pairs") or []:
        created = p.get("pairCreatedAt")
        out.append(PairSnapshot(
            chain=p.get("chainId", ""),
            pair_address=p.get("pairAddress", ""),
            base_symbol=(p.get("baseToken") or {}).get("symbol", ""),
            price_usd=_f(p.get("priceUsd")),
            liquidity_usd=_f((p.get("liquidity") or {}).get("usd")),
            volume_24h_usd=_f((p.get("volume") or {}).get("h24")),
            price_change_24h_pct=_f((p.get("priceChange") or {}).get("h24")),
            created_at=datetime.fromtimestamp(created / 1000, tz=UTC) if created else None,
        ))
    return out


class DexScreener:
    name = "dexscreener"

    def __init__(self, base_url: str = BASE_URL) -> None:
        self.base_url = base_url

    def search(self, query: str) -> list[PairSnapshot]:
        url = f"{self.base_url}/latest/dex/search?q={urllib.parse.quote(query)}"
        return parse_pairs(get_json(url))

    def ping(self) -> str:
        return f"{len(self.search('PEPE'))} paren gevonden voor PEPE"

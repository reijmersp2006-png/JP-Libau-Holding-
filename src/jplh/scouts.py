"""Verkenners: elk uur kijken ze naar alle markten en melden vroeg als iets ongewoons gebeurt.

Ze vergelijken de laatste beweging met wat voor dat instrument normaal is:
- een uur met een sprong of val van meer dan 4x de normale uurbeweging;
- een dag met meer dan 3x de normale dagbeweging;
- een uur met meer dan 5x het normale volume, maar alleen als de koers in dat uur ook echt
  bewoog (anders is het vaak alleen een grote order of een beurswissel, en dus ruis);
- een nieuwe top of bodem van het afgelopen jaar.
Daarnaast kijken ze op de memecoin-radar naar munten die snel stijgen zonder rode vlaggen.

Gebeurt hetzelfde bij drie of meer instrumenten tegelijk, dan wordt het één marktmelding in
plaats van een rij losse meldingen.

Een melding is informatie, geen koopsignaal. Verkenners handelen nooit.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from jplh.store import Store

DEDUP = timedelta(hours=12)       # dezelfde melding hooguit eens per 12 uur
DEDUP_LONG = {"jaartop": timedelta(days=7), "jaarbodem": timedelta(days=7)}
MAX_AGE = timedelta(hours=3)      # alleen verse koersen tellen
VOLUME_MOVE = 2.0                 # volume telt pas mee als de koers ook 2x de normale uurbeweging deed
MARKET_WIDE = 3                   # vanaf zoveel instrumenten tegelijk wordt het één marktmelding


@dataclass
class Alert:
    ts: str
    symbol: str
    name: str
    kind: str        # sprong | val | dagbeweging | volume | jaartop | jaarbodem | radar | markt
    level: str       # info | let_op | groot
    text: str


SCHEMA = """CREATE TABLE IF NOT EXISTS alerts (
    ts TEXT NOT NULL, symbol TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
    level TEXT NOT NULL, text TEXT NOT NULL)"""


def _pct(x: float) -> str:
    return f"{x:+.1%}".replace(".", ",")



def check_symbol(market: Store, symbol: str, name: str, now: datetime) -> list[Alert]:
    out: list[Alert] = []
    hourly = market.candles(symbol, "1h", known_at=now, limit=24 * 30)
    if len(hourly) >= 72 and now - hourly[-1].ts <= MAX_AGE:
        rets = [math.log(b.close / a.close) for a, b in zip(hourly, hourly[1:]) if a.close > 0 and b.close > 0]
        base = rets[:-24]
        sigma = statistics.pstdev(base) if len(base) > 10 else 0.0
        vols = [c.volume for c in hourly[-24 * 7 - 1:-1] if c.volume > 0]
        ratio = hourly[-1].volume / statistics.median(vols) if len(vols) >= 48 and hourly[-1].volume > 0 else 0.0
        busy = f", met {ratio:.0f}x het normale volume" if ratio >= 5 else ""
        if sigma > 0:
            last = rets[-1]
            z = last / sigma
            if abs(z) >= 4:
                kind = "sprong" if z > 0 else "val"
                out.append(Alert(now.isoformat(), symbol, name, kind, "groot" if abs(z) >= 6 else "let_op",
                                 f"{name}: {kind} van {_pct(math.exp(last) - 1)} in één uur "
                                 f"({abs(z):.0f}x de normale uurbeweging{busy})"))
            elif ratio >= 5 and abs(z) >= VOLUME_MOVE:
                out.append(Alert(now.isoformat(), symbol, name, "volume", "groot" if ratio >= 10 else "let_op",
                                 f"{name}: volume {ratio:.0f}x hoger dan normaal in het laatste uur, "
                                 f"koers {_pct(math.exp(last) - 1)}"))
            day = sum(rets[-24:])
            zd = day / (sigma * math.sqrt(24))
            if abs(zd) >= 3:
                out.append(Alert(now.isoformat(), symbol, name, "dagbeweging", "groot" if abs(zd) >= 5 else "let_op",
                                 f"{name}: {_pct(math.exp(day) - 1)} in 24 uur ({abs(zd):.1f}x de normale dagbeweging)"))
    daily = market.candles(symbol, "1d", known_at=now, limit=253)
    # Alleen op de dag dat de nieuwe dagkoers net binnen is.
    if len(daily) >= 200 and now - daily[-1].ts <= timedelta(days=2):
        prev = [c.close for c in daily[:-1]]
        last = daily[-1].close
        if last > max(prev):
            out.append(Alert(now.isoformat(), symbol, name, "jaartop", "info",
                             f"{name}: hoogste slotkoers van het afgelopen jaar"))
        elif last < min(prev):
            out.append(Alert(now.isoformat(), symbol, name, "jaarbodem", "let_op",
                             f"{name}: laagste slotkoers van het afgelopen jaar"))
    return out


def check_radar(market: Store, now: datetime) -> list[Alert]:
    rows = market.db.execute(
        "SELECT base_symbol, chain, volume_24h_usd, change_24h_pct, liquidity_usd, flags FROM radar "
        "WHERE fetched_at = (SELECT MAX(fetched_at) FROM radar WHERE fetched_at <= ?)", (now.isoformat(),)).fetchall()
    out = []
    for sym, chain, vol, chg, liq, flags in rows:
        if json.loads(flags or "[]") or vol is None or chg is None:
            continue
        if vol >= 1_000_000 and chg >= 50 and (liq or 0) >= 250_000:
            out.append(Alert(now.isoformat(), f"radar:{sym}:{chain}", sym, "radar", "info",
                             f"{sym} ({chain}): {chg:+.0f}% in 24 uur met ${vol / 1e6:.1f}M volume. "
                             "Alleen kijken, hier handelen we niet."))
    return out


GROUPS = {"uur": ("sprong", "val", "volume"), "dag": ("dagbeweging",)}
GROUP_NL = {"uur": "een ongewoon uur", "dag": "een ongewone dag"}


def bundle(found: list[Alert], now: datetime) -> list[Alert]:
    """Een ongewoon uur (of dag) bij veel instrumenten tegelijk = één marktmelding."""
    out = list(found)
    for group, kinds in GROUPS.items():
        same = [a for a in found if a.kind in kinds]
        if len({a.symbol for a in same}) < MARKET_WIDE:
            continue
        out = [a for a in out if a.kind not in kinds]
        names = ", ".join(dict.fromkeys(a.name for a in same))
        level = "groot" if sum(a.level == "groot" for a in same) * 2 >= len(same) else "let_op"
        out.append(Alert(now.isoformat(), f"markt:{group}", "Markt", "markt", level,
                         f"Hele markt in beweging: {len({a.symbol for a in same})} instrumenten tegelijk "
                         f"met {GROUP_NL[group]} ({names})"))
    return out


def scan(market: Store, watch: list[tuple[str, str]], now: datetime | None = None) -> list[Alert]:
    """Zoekt nieuwe meldingen en bewaart ze. ``watch`` = lijst van (symbool, naam)."""
    now = now or datetime.now(tz=UTC)
    market.db.execute(SCHEMA)
    found: list[Alert] = []
    for symbol, name in watch:
        found += check_symbol(market, symbol, name, now)
    found = bundle(found, now) + check_radar(market, now)
    new = []
    for a in found:
        since = (now - DEDUP_LONG.get(a.kind, DEDUP)).isoformat()
        seen = market.db.execute("SELECT 1 FROM alerts WHERE symbol=? AND kind=? AND ts > ?",
                                 (a.symbol, a.kind, since)).fetchone()
        if seen:
            continue
        market.db.execute("INSERT INTO alerts VALUES (?,?,?,?,?,?)", tuple(asdict(a).values()))
        new.append(a)
    market.db.commit()
    return new


def recent(market: Store, limit: int = 30) -> list[dict]:
    market.db.execute(SCHEMA)
    rows = market.db.execute("SELECT ts, symbol, name, kind, level, text FROM alerts ORDER BY ts DESC LIMIT ?",
                             (limit,)).fetchall()
    return [dict(zip(("ts", "symbol", "name", "kind", "level", "text"), r)) for r in rows]

"""De schaduw-arena: andere strategieën draaien op papier mee naast de echte afdelingen.

Elke uitdager krijgt per afdeling hetzelfde startgeld en dezelfde echte koersen als de afdeling
zelf, en telt pas mee vanaf de dag dat de holding begon. Er wordt dus alleen vooruit gekeken:
niemand kan winnen door achteraf het verleden te passen.

De arena handelt nooit en verandert nooit iets aan de afdelingen. Wint een uitdager lang genoeg
op rendement én op Sharpe, dan wordt hij voorgedragen. Alleen Phil beslist of hij promoveert,
en ook dan moet hij eerst in ``jplh backtest --desks`` winnen (de spelregel)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime

from jplh.config import HoldingConfig
from jplh.deskbacktest import VARIANTS, compare, live_variant
from jplh.desks import ALL_CANDIDATES, DESK_NAMES
from jplh.store import Store

LIVE = "gekozen (live)"
CONTENDERS = (
    "vasthouden (maatlat)",
    "oude versie",
    "2+3",
    "2+3+6",
    "7 vasthouden + marktweer",
    "8 rotatie top 2 (6 mnd)",
    "9b vasthouden + marktweer, marge 5%",
    "alles",
)
NICE = {
    LIVE: "huidige regels (live)",
    "vasthouden (maatlat)": "gewoon vasthouden",
    "oude versie": "actief kiezen (oude versie)",
    "2+3": "actief, minder wisselen + marktweer",
    "2+3+6": "actief, minder wisselen + marktweer + strenge drempel",
    "7 vasthouden + marktweer": "vasthouden met marktweer",
    "8 rotatie top 2 (6 mnd)": "rotatie: alleen de 2 sterkste",
    "9b vasthouden + marktweer, marge 5%": "vasthouden met marktweer, 5% marge",
    "alles": "alle trucs tegelijk",
}
PROMOTE_DAYS = 90       # zo lang moet een uitdager winnen voor hij wordt voorgedragen
MIN_EDGE = 0.01         # en dan minstens 1 procentpunt meer rendement


def arena_start(home_books: list[Store]) -> date | None:
    """De eerste dag dat de holding handelde: daar begint de arena."""
    firsts = [c[0][0].date() for c in (b.equity_curve() for b in home_books) if c]
    return min(firsts) if firsts else None


def run_arena(config: HoldingConfig, market: Store, start: date, now: datetime) -> dict:
    """Ranglijst per afdeling, alleen over de dagen sinds ``start``."""
    candles_of = {i.symbol: market.candles(i.symbol, "1d", known_at=now) for i in config.instruments}
    variants = [v for v in VARIANTS if v.name in CONTENDERS]
    res = compare(config, candles_of, ALL_CANDIDATES, variants, start=start)
    by_name = {v.name: v for v in variants}
    desks = {}
    for cls, rows in res.items():
        live_rules = replace(live_variant(config.desk_modes.get(cls, "actief")), name="")
        board = []
        for name, m in rows.items():
            if name in by_name and replace(by_name[name], name="") == live_rules:
                continue          # dezelfde regels als live: geen echte uitdager
            board.append({"name": NICE.get(name, name), "variant": name, "live": name == LIVE,
                          "return": m["return"], "sharpe": m["sharpe"], "max_dd": m["max_dd"],
                          "trades": m["trades"], "days": m["days"]})
        board.sort(key=lambda r: (-r["return"], -r["sharpe"], not r["live"]))   # gelijk: live eerst
        live = next((r for r in board if r["live"]), None)
        for r in board:
            r["promote"] = bool(live and not r["live"] and r["days"] >= PROMOTE_DAYS
                                and r["return"] >= live["return"] + MIN_EDGE and r["sharpe"] > live["sharpe"])
        desks[cls] = {"name": DESK_NAMES.get(cls, cls), "board": board,
                      "live_rank": next((i + 1 for i, r in enumerate(board) if r["live"]), None)}
    return {"start": start.isoformat(), "computed_at": now.isoformat(), "promote_days": PROMOTE_DAYS,
            "desks": desks}


def maybe_run_arena(config: HoldingConfig, market: Store, books: list[Store], now: datetime, log=print) -> dict | None:
    """Eén keer per dag de arena bijwerken (de dagkoersen veranderen maar één keer per dag)."""
    old = market.get_state("arena")
    today = now.date().isoformat()
    if old and old.get("computed_at", "")[:10] == today:
        return old
    start = arena_start(books)
    if start is None:
        return old
    try:
        new = run_arena(config, market, start, now)
    except (ValueError, KeyError, ZeroDivisionError) as exc:   # de arena mag de ronde nooit stoppen
        log(f"arena mislukt: {type(exc).__name__}: {exc}")
        return old
    market.set_state("arena", new)
    for d in new["desks"].values():
        top = d["board"][0] if d["board"] else None
        if top:
            log(f"arena {d['name']}: koploper {top['name']} {top['return']:+.1%}, echte afdeling op plek {d['live_rank']}")
    return new

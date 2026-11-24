"""Master Prompt 9.2: vingerafdruk van de stand, om een verhuizing te bewijzen.

``fingerprint(home)`` leest alleen: sha256 van elk bestand in ``data/`` en ``logs/`` (plus
``jarvis.json`` en ``KILL``), ``PRAGMA integrity_check`` per database, en een samenvatting per
afdeling (vermogen, cash, posities, pauze, aantal trades). Twee kopieën zijn gelijk als hun
``digest`` gelijk is. Er staan geen geheimen of identificatienummers in: van de Telegram-stand
alleen de namen van de velden.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _files(home: Path) -> list[Path]:
    out = [p for d in ("data", "logs") for p in sorted((home / d).rglob("*")) if p.is_file()]
    out += [home / n for n in ("jarvis.json", "KILL", "noodstop-log.jsonl") if (home / n).is_file()]
    return out


def _integrity(db: Path) -> str:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return con.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        con.close()


def fingerprint(home: Path, summary: bool = True) -> dict:
    """Alleen-lezen. De hashes worden berekend vóór er iets geopend wordt."""
    files = {p.relative_to(home).as_posix(): _sha(p) for p in _files(home)}
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    dbs = {k: _integrity(home / k) for k in files if k.endswith(".sqlite3")}
    journals = {k: sum(1 for _ in (home / k).open(encoding="utf-8")) for k in files if k.endswith(".jsonl")}
    out = {
        "digest": digest,
        "files": len(files),
        "bytes": sum((home / k).stat().st_size for k in files),
        "integrity": dbs,
        "integrity_ok": bool(dbs) and all(v == "ok" for v in dbs.values()),
        "journals": {"files": len(journals), "lines": sum(journals.values())},
        "kill": (home / "KILL").is_file(),
        "has_data": (home / "data" / "holding.sqlite3").is_file() and any(k.startswith("data/desks/") for k in files),
    }
    if summary and out["has_data"]:
        out.update(_summary(home))
    return out


def _summary(home: Path) -> dict:
    """Vermogen per afdeling zoals het dashboard het rekent. Opent kopieën alleen-lezen genoeg:
    de hashes hierboven zijn dan al vastgelegd."""
    from jplh.config import load_config
    from jplh.desks import open_desks
    from jplh.site import build_state
    from jplh.store import Store

    cfg = load_config(home / "config" / "holding.toml")
    market = Store(home / "data" / "holding.sqlite3")
    try:
        desks = open_desks(cfg, home, market)
        state = build_state(cfg, desks, market, home, datetime.now(tz=UTC))
        tg = market.get_state("telegram", {})
    finally:
        market.close()
    desk_rows = {d["id"]: {"equity_eur": round(d["equity_eur"], 2), "cash_eur": round(d["cash_eur"], 2),
                           "positions": len(d["positions"]),
                           "positions_eur": round(sum(p["value_eur"] for p in d["positions"]), 2),
                           "paused": bool(d.get("paused_reason")), "trades": d.get("trades")}
                 for d in state["desks"]}
    curve = state["total"].get("equity_curve") or []
    return {
        "equity_eur": round(sum(r["equity_eur"] for r in desk_rows.values()), 2),
        "last_round_at": curve[-1][0] if curve else None,
        "desks": desk_rows,
        "paused": sorted(k for k, r in desk_rows.items() if r["paused"]),
        "telegram_fields": sorted(tg),          # alleen namen, nooit waarden
    }


def compare(a: dict, b: dict) -> list[str]:
    """Verschillen tussen twee vingerafdrukken; leeg = identiek."""
    keys = ("digest", "files", "bytes", "integrity_ok", "journals", "kill", "equity_eur", "paused", "desks")
    return [f"{k}: {a.get(k)!r} != {b.get(k)!r}" for k in keys if a.get(k) != b.get(k)]

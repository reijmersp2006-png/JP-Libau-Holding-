"""SQLite-opslag. Elke koers krijgt het tijdstip van ophalen mee (``fetched_at``), zodat een
backtest alleen data gebruikt die op dat moment echt bekend was."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from jplh.models import Candle, Fill, Side

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    symbol TEXT NOT NULL, interval TEXT NOT NULL, ts TEXT NOT NULL,
    open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
    volume REAL NOT NULL, source TEXT NOT NULL, fetched_at TEXT NOT NULL,
    PRIMARY KEY (symbol, interval, ts)
);
CREATE TABLE IF NOT EXISTS fx_reference (
    day TEXT NOT NULL, currency TEXT NOT NULL, rate REAL NOT NULL, fetched_at TEXT NOT NULL,
    PRIMARY KEY (day, currency)
);
CREATE TABLE IF NOT EXISTS radar (
    fetched_at TEXT NOT NULL, chain TEXT, pair_address TEXT, base_symbol TEXT,
    price_usd REAL, liquidity_usd REAL, volume_24h_usd REAL, change_24h_pct REAL,
    created_at TEXT, flags TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, instrument TEXT NOT NULL,
    side TEXT NOT NULL, quantity REAL NOT NULL, price_eur REAL NOT NULL, fee_eur REAL NOT NULL,
    strategy TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS equity (ts TEXT PRIMARY KEY, equity_eur REAL NOT NULL);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


class Store:
    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------ koersen
    def save_candles(self, symbol: str, interval: str, candles: list[Candle], source: str,
                     fetched_at: datetime) -> int:
        """Bewaart nieuwe candles. Bestaande worden NIET overschreven: de eerste waarneming telt."""
        before = self.db.total_changes
        self.db.executemany(
            "INSERT OR IGNORE INTO candles VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(symbol, interval, _iso(c.ts), c.open, c.high, c.low, c.close, c.volume, source,
              _iso(fetched_at)) for c in candles],
        )
        self.db.commit()
        return self.db.total_changes - before

    def candles(self, symbol: str, interval: str = "1h", known_at: datetime | None = None,
                limit: int | None = None) -> list[Candle]:
        """Candles oud naar nieuw. ``known_at``: alleen wat op dat moment al opgehaald was."""
        sql = "SELECT ts, open, high, low, close, volume FROM candles WHERE symbol=? AND interval=?"
        args: list = [symbol, interval]
        if known_at is not None:
            sql += " AND fetched_at <= ?"
            args.append(_iso(known_at))
        sql += " ORDER BY ts DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = self.db.execute(sql, args).fetchall()
        return [Candle(_dt(r[0]), *r[1:]) for r in reversed(rows)]

    def latest_close(self, symbol: str, interval: str = "1h") -> tuple[datetime, float] | None:
        row = self.db.execute(
            "SELECT ts, close FROM candles WHERE symbol=? AND interval=? ORDER BY ts DESC LIMIT 1",
            (symbol, interval)).fetchone()
        return (_dt(row[0]), row[1]) if row else None

    def candle_counts(self) -> dict[str, int]:
        return dict(self.db.execute("SELECT symbol, COUNT(*) FROM candles GROUP BY symbol"))

    def save_fx_reference(self, currency: str, rows: list[tuple[date, float]], fetched_at: datetime) -> None:
        self.db.executemany("INSERT OR IGNORE INTO fx_reference VALUES (?,?,?,?)",
                            [(d.isoformat(), currency, r, _iso(fetched_at)) for d, r in rows])
        self.db.commit()

    def save_radar(self, snapshots, fetched_at: datetime) -> None:
        self.db.executemany("INSERT INTO radar VALUES (?,?,?,?,?,?,?,?,?,?)", [
            (_iso(fetched_at), s.chain, s.pair_address, s.base_symbol, s.price_usd, s.liquidity_usd,
             s.volume_24h_usd, s.price_change_24h_pct,
             _iso(s.created_at) if s.created_at else None, json.dumps(s.red_flags(fetched_at)))
            for s in snapshots])
        self.db.commit()

    # ------------------------------------------------------------ logboek en boekhouding
    def add_event(self, ts: datetime, kind: str, payload: dict) -> None:
        self.db.execute("INSERT INTO events (ts, kind, payload) VALUES (?,?,?)",
                        (_iso(ts), kind, json.dumps(payload, ensure_ascii=False, default=str)))
        self.db.commit()

    def events(self, kind: str | None = None, limit: int = 50) -> list[tuple[datetime, str, dict]]:
        sql, args = "SELECT ts, kind, payload FROM events", []
        if kind:
            sql, args = sql + " WHERE kind=?", [kind]
        rows = self.db.execute(sql + f" ORDER BY id DESC LIMIT {int(limit)}", args).fetchall()
        return [(_dt(t), k, json.loads(p)) for t, k, p in rows]

    def add_fill(self, fill: Fill) -> None:
        self.db.execute(
            "INSERT INTO fills (ts, instrument, side, quantity, price_eur, fee_eur, strategy) VALUES (?,?,?,?,?,?,?)",
            (_iso(fill.ts), fill.instrument, fill.side.value, fill.quantity, fill.price_eur, fill.fee_eur,
             fill.strategy))
        self.db.commit()

    def fills(self) -> list[Fill]:
        rows = self.db.execute(
            "SELECT ts, instrument, side, quantity, price_eur, fee_eur, strategy FROM fills ORDER BY id").fetchall()
        return [Fill(r[1], Side(r[2]), r[3], r[4], r[5], _dt(r[0]), r[6]) for r in rows]

    def fills_on(self, day: date) -> int:
        return self.db.execute("SELECT COUNT(*) FROM fills WHERE substr(ts, 1, 10) = ?",
                               (day.isoformat(),)).fetchone()[0]

    def add_equity(self, ts: datetime, equity: float) -> None:
        self.db.execute("INSERT OR REPLACE INTO equity VALUES (?,?)", (_iso(ts), equity))
        self.db.commit()

    def equity_curve(self) -> list[tuple[datetime, float]]:
        return [(_dt(t), e) for t, e in self.db.execute("SELECT ts, equity_eur FROM equity ORDER BY ts")]

    def get_state(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_state(self, key: str, value) -> None:
        self.db.execute("INSERT OR REPLACE INTO state VALUES (?,?)", (key, json.dumps(value)))
        self.db.commit()

"""Externe vergelijking: resultaten van een ander systeem (bijv. de Grok-bot) naast NEXUS.

Import in CSV of JSON. Herkende velden (hoofdletters en synoniemen maken niet uit):
``timestamp``, ``asset``, ``direction``, ``entry``, ``exit``, ``size``, ``fees``, ``slippage``,
``realized_pnl``, ``equity``, ``strategy``. Ontbreekt de lijst met trades en staan er alleen totalen in
(bijv. ``{"net_pnl": 42, "trades": 7}``), dan is de vergelijking **onvolledig** en zegt NEXUS niet wie
beter is.

Eerlijk vergelijken betekent: hetzelfde startkapitaal, dezelfde periode, dezelfde instrumenten,
dezelfde kosten en hetzelfde risicobudget. Wat niet gelijk is, staat in ``comparability``. Eén
winstgevende dag bewijst niets: onder ``MIN_TRADES`` trades of ``MIN_DAYS`` handelsdagen geeft de
vergelijking geen oordeel.
"""

from __future__ import annotations

import csv
import io
import json
import math
from datetime import UTC, datetime

from nexus import stats

MIN_TRADES = 30
MIN_DAYS = 20

ALIASES = {
    "ts": ("timestamp", "time", "date", "datetime", "ts", "exit_time", "closed_at"),
    "symbol": ("asset", "symbol", "instrument", "pair", "ticker", "market"),
    "direction": ("direction", "side", "type"),
    "entry": ("entry", "entry_price", "open_price", "buy_price"),
    "exit": ("exit", "exit_price", "close_price", "sell_price"),
    "size": ("size", "position_size", "notional", "quantity", "qty", "amount"),
    "fees": ("fees", "fee", "commission"),
    "slippage": ("slippage", "slip"),
    "pnl": ("realized_pnl", "pnl", "profit", "realized", "net_pnl_trade"),
    "equity": ("equity", "account_equity", "balance"),
    "strategy": ("strategy", "strategy_id", "strategy_identifier", "bot"),
}
AGGREGATE_KEYS = ("net_pnl", "total_pnl", "profit", "win_rate", "trades", "return", "total_return")


def _key(row: dict, field: str):
    low = {str(k).strip().lower(): v for k, v in row.items()}
    for a in ALIASES[field]:
        if a in low and low[a] not in (None, ""):
            return low[a]
    return None


def _num(x) -> float | None:
    if x is None:
        return None
    try:
        v = float(str(x).replace("€", "").replace("$", "").replace(",", "").strip())
        return v if math.isfinite(v) else None
    except ValueError:
        return None


def _ts(x) -> datetime | None:
    if x is None:
        return None
    s = str(x).strip()
    try:
        if s.replace(".", "").isdigit():
            v = float(s)
            return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, tz=UTC)
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except ValueError:
        return None


def parse(content: str, fmt: str) -> dict:
    """Geeft ``{"completeness", "trades", "aggregate", "issues"}``."""
    issues: list[str] = []
    rows: list[dict] = []
    aggregate: dict = {}
    if fmt == "json":
        data = json.loads(content)
        if isinstance(data, dict):
            if isinstance(data.get("trades"), list):
                rows = data["trades"]
                aggregate = {k: v for k, v in data.items() if k != "trades"}
            else:
                aggregate = data
        elif isinstance(data, list):
            rows = data
        else:
            raise ValueError("JSON moet een lijst trades of een object zijn")
    elif fmt == "csv":
        rows = list(csv.DictReader(io.StringIO(content)))
    else:
        raise ValueError("formaat moet csv of json zijn")
    trades = []
    for k, r in enumerate(rows):
        if not isinstance(r, dict):
            issues.append(f"rij {k + 1}: geen object")
            continue
        t = {"ts": _ts(_key(r, "ts")), "symbol": (_key(r, "symbol") or "?"), "direction": str(_key(r, "direction") or "").lower(),
             "entry": _num(_key(r, "entry")), "exit": _num(_key(r, "exit")), "size": _num(_key(r, "size")),
             "fees": _num(_key(r, "fees")), "slippage": _num(_key(r, "slippage")), "pnl": _num(_key(r, "pnl")),
             "equity": _num(_key(r, "equity")), "strategy": _key(r, "strategy")}
        if t["ts"] is None:
            issues.append(f"rij {k + 1}: tijdstip ontbreekt of is onleesbaar")
            continue
        if t["pnl"] is None and None not in (t["entry"], t["exit"], t["size"]):
            sign = -1 if t["direction"] in ("short", "sell") else 1
            t["pnl"] = sign * (t["exit"] - t["entry"]) * t["size"] - (t["fees"] or 0) - (t["slippage"] or 0)
            t["pnl_derived"] = True
        if t["pnl"] is None:
            issues.append(f"rij {k + 1}: geen resultaat en niet af te leiden")
            continue
        if t["fees"] is None:
            t["fees_missing"] = True
        trades.append(t)
    trades.sort(key=lambda t: t["ts"])
    if any(t.get("fees_missing") for t in trades):
        issues.append(f"{sum(1 for t in trades if t.get('fees_missing'))} trades zonder kosten: resultaat mogelijk te gunstig")
    completeness = "trades" if trades else ("aggregate" if any(k in aggregate for k in AGGREGATE_KEYS) else "empty")
    return {"completeness": completeness, "trades": trades, "aggregate": aggregate, "issues": issues}


def metrics(trades: list[dict], capital: float) -> dict:
    """Prestatie uit een trade-lijst, geschaald naar ``capital``."""
    if not trades:
        return {"trades": 0}
    pnls = [t["pnl"] for t in trades]
    eq, curve = capital, []
    for t in trades:
        eq += t["pnl"]
        curve.append((t["ts"], eq))
    peak, mdd = capital, 0.0
    for _, e in curve:
        peak = max(peak, e)
        mdd = max(mdd, 1 - e / peak if peak > 0 else 0)
    days: dict = {}
    for ts, e in curve:
        days[ts.date()] = e
    vals = [capital, *days.values()]
    daily = [b / a - 1 for a, b in zip(vals, vals[1:]) if a > 0]
    ev = stats.expected_value(pnls)
    gw = sum(p for p in pnls if p > 0)
    gl = -sum(p for p in pnls if p <= 0)
    span = (trades[-1]["ts"] - trades[0]["ts"]).days + 1
    return {"trades": len(trades), "first": trades[0]["ts"].isoformat(), "last": trades[-1]["ts"].isoformat(),
            "days": len(days), "span_days": span, "net_pnl": sum(pnls), "net_return": sum(pnls) / capital,
            "win_rate": ev["win_rate"], "profit_factor": gw / gl if gl > 0 else None,
            "expectancy": ev["expected_value"], "avg_win": ev["avg_win"], "avg_loss": ev["avg_loss"],
            "largest_loss": ev["largest_loss"], "max_drawdown": mdd,
            "sharpe_daily": stats.sharpe(daily, 365) if len(daily) >= MIN_DAYS else None,
            "fees": sum(t["fees"] or 0 for t in trades), "symbols": sorted({t["symbol"] for t in trades})}


def compare(external: dict, nexus_trades: list[dict], capital: float, nexus_label: str,
            external_capital: float | None = None, nexus_fee_pct: float | None = None) -> dict:
    """Zet beide naast elkaar op hetzelfde kapitaal en dezelfde periode; zegt wat niet vergelijkbaar is."""
    notes = list(external.get("issues", []))
    if external["completeness"] != "trades":
        return {"status": "incomplete", "verdict": "Onvolledig: alleen totalen, geen trades. Geen oordeel mogelijk.",
                "external_aggregate": external.get("aggregate"), "notes": notes}
    ext = external["trades"]
    scale = capital / external_capital if external_capital else 1.0
    if external_capital is None:
        notes.append("startkapitaal van het externe systeem onbekend: resultaten niet geschaald")
    ext_scaled = [{**t, "pnl": t["pnl"] * scale} for t in ext]
    start, end = ext[0]["ts"], ext[-1]["ts"]
    nx = [t for t in nexus_trades if start <= t["ts"] <= end]
    m_ext, m_nx = metrics(ext_scaled, capital), metrics(nx, capital)
    overlap = set(m_ext.get("symbols", [])) & set(m_nx.get("symbols", []))
    comparability = {
        "same_period": True, "period": [start.isoformat(), end.isoformat()],
        "same_capital": external_capital is not None, "capital_eur": capital,
        "instrument_overlap": sorted(overlap),
        "instruments_only_external": sorted(set(m_ext.get("symbols", [])) - overlap),
        "fees_known": not any(t.get("fees_missing") for t in ext),
        "nexus_fee_pct": nexus_fee_pct,
        "nexus_source": nexus_label,
    }
    enough = m_ext["trades"] >= MIN_TRADES and m_ext["days"] >= MIN_DAYS and m_nx.get("trades", 0) >= MIN_TRADES
    if not enough:
        verdict = (f"Te weinig om te oordelen: extern {m_ext['trades']} trades over {m_ext['days']} dagen, NEXUS "
                   f"{m_nx.get('trades', 0)} trades (minimaal {MIN_TRADES} trades en {MIN_DAYS} dagen elk).")
        status = "insufficient"
    elif not overlap:
        verdict = "Geen gemeenschappelijke instrumenten: de cijfers staan naast elkaar, maar een oordeel is niet eerlijk."
        status = "not_comparable"
    else:
        better = (m_ext.get("sharpe_daily") or -9) > (m_nx.get("sharpe_daily") or -9)
        verdict = (f"{'Extern' if better else 'NEXUS'} had in deze periode de betere verhouding rendement/risico "
                   "(dagelijkse Sharpe). Dit is één periode; geen bewijs van een blijvend verschil.")
        status = "compared"
    return {"status": status, "verdict": verdict, "external": m_ext, "nexus": m_nx,
            "comparability": comparability, "notes": notes}


def trades_from_executions(execs: list[dict]) -> list[dict]:
    """Echte paper-vullingen → gesloten trades (gemiddelde kostprijs; elke verkoop sluit een deel).

    Alleen verkopen leveren een gerealiseerd resultaat; de aankoopkosten gaan naar rato mee.
    """
    pos: dict[str, list[float]] = {}  # symbool → [aantal, kostenbasis incl. aankoopkosten]
    out = []
    for e in sorted(execs, key=lambda x: (x["ts"], x.get("id", 0))):
        sym, qty, px, fee = e["symbol"], float(e["quantity"]), float(e["price_eur"]), float(e.get("fee_eur") or 0)
        q, basis = pos.get(sym, [0.0, 0.0])
        if e["side"] == "buy":
            pos[sym] = [q + qty, basis + qty * px + fee]
            continue
        if q <= 0:
            continue
        sold = min(qty, q)
        cost = basis * sold / q
        ts = e["ts"] if isinstance(e["ts"], datetime) else _ts(e["ts"])
        out.append({"ts": ts, "symbol": sym, "direction": "long", "pnl": sold * px - fee - cost,
                    "fees": fee, "size": sold * px})
        pos[sym] = [q - sold, basis - cost]
    return out

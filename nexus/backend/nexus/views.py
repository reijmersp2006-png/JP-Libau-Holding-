"""De payloads voor de frontend. Elke getoonde waarde heeft een herkomstlabel."""

from __future__ import annotations

from datetime import UTC, datetime

from nexus import agents as agents_mod
from nexus.bridge import Snapshot
from nexus.controls import Controls
from nexus.guardian import RiskLimits
from nexus.provenance import DataLabel
from nexus.settings import Settings

DESK_NAMES = {"crypto": "Crypto", "meme": "Memecoins", "stocks": "Aandelen", "metals": "Goud & zilver", "fx": "Valuta"}


def environment(settings: Settings, snap: Snapshot | None) -> str:
    if settings.demo:
        return "demo"
    return "paper" if snap else "unconfigured"


def controls_view(controls: Controls) -> dict:
    return {"mode": controls.mode().value, "kill": controls.kill_status(), "live_enabled": False,
            "live_gate": controls.live_gate()}


def portfolio(snap: Snapshot) -> dict:
    t = snap.state["total"]
    curve = t.get("equity_curve") or []
    return {
        "label": DataLabel.SIMULATED.value,          # paper trading: echte koersen, nepgeld
        "as_of": curve[-1][0] if curve else None,
        "equity_eur": t["equity_eur"], "capital_eur": t["capital_eur"], "cash_eur": snap.cash_eur,
        "pnl_eur": t["pnl_eur"], "pnl_pct": t["pnl_pct"],
        "realized_eur": snap.realized_eur, "unrealized_eur": snap.unrealized_eur,
        "buy_fees_eur": snap.buy_fees_eur, "fees_eur": snap.fees_eur,
        "benchmark_eur": t.get("benchmark_eur"), "peak_eur": t["peak_eur"], "drawdown": t["drawdown"],
        "day_pnl_pct": t["day_pnl_pct"], "equity_curve": curve, "days_active": snap.state.get("days_active", 0),
    }


def allocation(snap: Snapshot) -> list[dict]:
    equity = snap.state["total"]["equity_eur"] or 1.0
    by: dict[str, float] = {}
    for p in snap.positions:
        by[p["desk"]] = by.get(p["desk"], 0.0) + p["value_eur"]
    rows = [{"key": k, "name": DESK_NAMES.get(k, k), "value_eur": v, "pct": v / equity} for k, v in by.items()]
    rows.sort(key=lambda r: -r["value_eur"])
    rows.append({"key": "cash", "name": "Cash", "value_eur": snap.cash_eur, "pct": snap.cash_eur / equity})
    return rows


def risk_utilization(snap: Snapshot, limits: RiskLimits) -> list[dict]:
    view = snap.portfolio_view()
    eq = view.equity_eur or 1.0
    largest = max(view.position_value.values(), default=0.0)
    corr = view.class_exposure.get("crypto", 0.0) + view.class_exposure.get("meme", 0.0)
    rows = [
        ("drawdown", "Daling vanaf top", view.drawdown, limits.max_drawdown_pct),
        ("daily_loss", "Dagverlies", max(0.0, -view.day_pnl_pct), limits.max_daily_loss_pct),
        ("largest_position", "Grootste positie", largest / eq, limits.max_position_pct),
        ("correlated", "Crypto + memes", corr / eq, limits.max_correlated_pct),
        ("meme", "Memecoins", view.class_exposure.get("meme", 0.0) / eq, limits.max_meme_pct),
        ("positions", "Open posities", float(sum(1 for v in view.position_value.values() if v > 0)),
         float(limits.max_open_positions)),
    ]
    return [{"key": k, "label": lab, "used": u, "limit": lim, "utilization": (u / lim) if lim else 0.0,
             "breached": u >= lim} for k, lab, u, lim in rows]


def connections(snap: Snapshot | None, settings: Settings) -> list[dict]:
    out = []
    if snap:
        by_source: dict[str, list[str]] = {}
        for q in snap.quotes.values():
            by_source.setdefault(q["source"], []).append(q["label"])
        names = {"bitvavo": ("Bitvavo", "crypto & memecoins, uurkoersen, publiek (geen sleutel)"),
                 "yahoo": ("Yahoo Finance", "aandelen, goud/zilver, valuta, uurkoersen (onofficieel, kan haperen)")}
        for src, labels in by_source.items():
            name, what = names.get(src, (src, ""))
            fresh = sum(1 for lab in labels if lab in ("DELAYED", "SIMULATED", "LIVE"))
            status = "ok" if fresh == len(labels) else ("degraded" if fresh else "down")
            label = "SIMULATED" if snap.demo else ("DELAYED" if fresh else "HISTORICAL")
            out.append({"name": name, "kind": "marktdata", "status": status, "label": label,
                        "detail": f"{what}; {fresh} van {len(labels)} koersen vers"})
        out.append({"name": "DexScreener", "kind": "meme-radar", "status": "ok" if snap.radar_at else "down",
                    "label": "SIMULATED" if snap.demo else ("DELAYED" if snap.radar_at else "UNAVAILABLE"),
                    "detail": f"alleen kijken, laatst opgehaald {(snap.radar_at or 'nooit')[:16].replace('T', ' ')} UTC"})
        out.append({"name": "Paper-broker (holding)", "kind": "broker", "status": "ok", "label": "SIMULATED",
                    "detail": "vult tegen de laatste koers met kosten en slippage; geen echt geld"})
    else:
        out.append({"name": "JP-libau Holding", "kind": "bron", "status": "down", "label": "UNAVAILABLE",
                    "detail": "geen holding-data gevonden: zet NEXUS_HOLDING_HOME of start met NEXUS_DEMO=1"})
    out.append({"name": "Live broker", "kind": "broker", "status": "disabled", "label": "UNAVAILABLE",
                "detail": "bestaat niet in deze versie (fase 6); live handelen staat uit"})
    out.append({"name": "Anthropic API", "kind": "ai", "status": "configured" if settings.anthropic_key_present else "not_configured",
                "label": "DELAYED" if settings.anthropic_key_present else "UNAVAILABLE",
                "detail": "sleutel aanwezig: Council en Copilot kunnen Claude gebruiken (binnen het dagbudget)"
                if settings.anthropic_key_present else "geen sleutel: Council draait niet, Copilot antwoordt zonder taalmodel"})
    return out


def command_center(snap: Snapshot | None, controls: Controls, settings: Settings, limits: RiskLimits,
                   proposals: list[dict]) -> dict:
    council = agents_mod.council(snap)
    base = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "environment": environment(settings, snap),
        "controls": controls_view(controls),
        "agents": {"summary": agents_mod.summary(council), "items": council},
        "connections": connections(snap, settings),
        "proposals": proposals,
        "limits": limits.describe(),
    }
    if snap is None:
        base.update({"available": False, "portfolio": None, "allocation": [], "positions": [], "regime": None,
                     "findings": [], "decisions": [], "risk": [], "market": [], "radar": [], "health": None})
        return base
    s = snap.state
    feed = s.get("feed", [])
    rd = s.get("risk")
    market = []
    for tk in s.get("ticker", []):
        q = snap.quotes.get(tk["symbol"])
        market.append({**tk, "label": q["label"] if q else ("SIMULATED" if snap.demo else "UNAVAILABLE"),
                       "ts": q["ts"] if q else None})
    base.update({
        "available": True,
        "as_of": snap.now.isoformat(),
        "portfolio": portfolio(snap),
        "allocation": allocation(snap),
        "positions": snap.positions,
        "regime": {"label": "SIMULATED" if snap.demo else "DELAYED", "weather": s.get("market_weather", []),
                   "vix": s.get("vix"),
                   "risk_director": None if not rd else {
                       "vol": rd.get("vol"), "target": rd.get("target"), "exposure": rd.get("exposure"),
                       "computed_at": rd.get("computed_at")}},
        "findings": [f for f in feed if f["kind"] in ("alert", "reflection", "weekreport")][:10],
        "decisions": [f for f in feed if f["kind"] in ("trade", "refused")][:12],
        "risk": risk_utilization(snap, limits),
        "market": market,
        "radar": s.get("radar", []),
        "health": s.get("jarvis", {}).get("health"),
        "fills_today": snap.fills_today,
    })
    return base

"""Jarvis: de stem van de holding. Maakt van de stand een korte briefing en bewaakt of alles
gezond draait. Werkt alleen met wat in de stand staat; Jarvis handelt zelf nooit."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

AMS = ZoneInfo("Europe/Amsterdam")
ALWAYS_OPEN = ("crypto", "meme")     # deze markten sluiten nooit, dus oude koersen = probleem


def _eur(x: float) -> str:
    return f"€{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(x: float) -> str:
    return f"{x:+.1%}".replace(".", ",")


def health(state: dict, problems: list[str] | None = None) -> dict:
    """Gezondheid in drie standen: ok, let op, alarm. Met per punt een uitleg in gewone taal."""
    issues: list[dict] = []
    for p in problems or []:
        issues.append({"level": "let op", "text": f"databron mislukt: {p}"})
    limits = state.get("limits", {})
    max_dd = limits.get("max_drawdown_pct", 0.15)
    if state.get("kill"):
        issues.append({"level": "alarm", "text": "de noodstop (KILL) staat aan: er wordt niet gehandeld"})
    for d in state.get("desks", []):
        name = d.get("name", d["id"])
        if d.get("paused_reason"):
            issues.append({"level": "alarm", "text": f"{name} is gepauzeerd: {d['paused_reason']}"})
        elif d.get("drawdown", 0) >= max_dd * 0.7:
            issues.append({"level": "let op", "text": f"{name} staat {_pct(-d['drawdown'])} onder de top, "
                                                      f"dicht bij de pauzegrens van {_pct(-max_dd)}"})
        stale = [i["symbol"] for i in d.get("instruments", []) if not i.get("fresh")]
        if d["id"] in ALWAYS_OPEN and stale:
            issues.append({"level": "alarm" if len(stale) == len(d.get("instruments", [])) else "let op",
                           "text": f"{name} heeft oude koersen voor {', '.join(stale)}"})
    level = "alarm" if any(i["level"] == "alarm" for i in issues) else ("let op" if issues else "ok")
    return {"status": level, "issues": issues}


def briefing(state: dict, now: datetime, h: dict | None = None) -> dict:
    """Een korte briefing zoals een assistent die zou geven: eerst het belangrijkste."""
    local = now.astimezone(AMS)
    hello = "Goedemorgen" if 5 <= local.hour < 12 else ("Goedemiddag" if local.hour < 18 else "Goedenavond")
    t = state["total"]
    lines = []
    vs = ""
    if t.get("benchmark_eur"):
        diff = t["equity_eur"] - t["benchmark_eur"]
        vs = f", {_eur(abs(diff))} {'beter' if diff >= 0 else 'slechter'} dan gewoon vasthouden"
    lines.append(f"De schatkist staat op {_eur(t['equity_eur'])}: {_pct(t['pnl_pct'])} sinds de start, "
                 f"{_pct(t['day_pnl_pct'])} in de laatste 24 uur{vs}.")
    weather = state.get("market_weather", [])
    if weather:
        parts = [f"{w['name'].split(' ')[0].lower()} {'goed' if w['ok'] else 'slecht'}" for w in weather]
        lines.append("Marktweer: " + ", ".join(parts) + ".")
    desks = sorted(state.get("desks", []), key=lambda d: d.get("pnl_pct", 0), reverse=True)
    if len(desks) >= 2:
        best, worst = desks[0], desks[-1]
        lines.append(f"Beste afdeling: {best['name']} ({_pct(best['pnl_pct'])}). "
                     f"Achterblijver: {worst['name']} ({_pct(worst['pnl_pct'])}).")
    since = (now - timedelta(hours=24)).isoformat()
    trades = [f for f in state.get("feed", []) if f["kind"] == "trade" and f["ts"] >= since]
    if trades:
        last = trades[0]
        lines.append(f"{len(trades)} trade{'s' if len(trades) != 1 else ''} in de laatste 24 uur. "
                     f"Laatste: {last['text']}" + (f", omdat {last['why'][0].lower()}{last['why'][1:]}" if last.get("why") else "") + ".")
    else:
        lines.append("Geen trades in de laatste 24 uur: de afdelingen houden vast en er was niets dat de kosten waard was.")
    alerts = [a for a in state.get("lab", {}).get("alerts", []) if a.get("level") == "groot"][:2]
    if alerts:
        lines.append("Verkenners: " + "; ".join(a["text"] for a in alerts) + ".")
    h = h or {"status": "ok", "issues": []}
    if h["status"] == "ok":
        lines.append("Alle systemen draaien normaal.")
    else:
        lines.append(f"Aandacht nodig ({h['status']}): " + "; ".join(i["text"] for i in h["issues"][:3]) + ".")
    speech = f"{hello} Phil. " + " ".join(lines)
    return {"hello": hello, "lines": lines, "speech": speech, "at": now.isoformat()}

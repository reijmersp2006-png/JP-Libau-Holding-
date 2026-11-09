"""Jarvis luistert: commando's van Phil via Telegram.

Alleen berichten uit de chat die bij het verbinden is vastgelegd tellen; van iedereen anders
wordt niets uitgevoerd. Commando's veranderen nooit een strategie. Ze lezen de stand, of ze
zetten de noodstop aan of uit (het bestand ``KILL``, dat elke order blokkeert)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from jplh.config import HoldingConfig
from jplh.desks import DESK_NAMES, DESK_ORDER, open_desks
from jplh.jarvis import _eur, _pct, briefing, health
from jplh.site import build_state
from jplh.store import Store

HELP = ("Commando's:\n"
        "/stand - de stand van de holding nu\n"
        "/briefing - de volledige briefing\n"
        "/waarom BTC - waarom de laatste trade in dat instrument\n"
        "/noodstop - direct alles stil (geen enkele order meer)\n"
        "/hervat - noodstop weer uit\n"
        "/help - dit lijstje")


def _state(config: HoldingConfig, home: Path, market: Store, now: datetime) -> dict:
    desks = open_desks(config, home, market)
    return build_state(config, desks, market, home, now)


def answer(text: str, config: HoldingConfig, home: Path, market: Store, now: datetime) -> str:
    """Het antwoord van Jarvis op één bericht."""
    parts = text.strip().split()
    if not parts:
        return HELP
    cmd = parts[0].lower().split("@")[0]
    kill = home / "KILL"
    if cmd in ("/start", "/help", "help"):
        return "🤖 Tot je dienst.\n" + HELP
    if cmd == "/noodstop":
        kill.write_text(f"noodstop via Telegram {now.isoformat()}\n", encoding="utf-8")
        return ("🛑 Noodstop staat AAN. Er gaat geen enkele order meer uit, ook geen verkoop, "
                "tot je /hervat stuurt. Posities blijven staan zoals ze staan.")
    if cmd == "/hervat":
        was = kill.exists()
        kill.unlink(missing_ok=True)
        return "✅ Noodstop is uit. De volgende ronde handelt weer." if was else "De noodstop stond al uit."
    if cmd in ("/stand", "/briefing"):
        st = _state(config, home, market, now)
        h = health(st)
        if cmd == "/briefing":
            b = briefing(st, now, h)
            return f"🤖 {b['hello']} Phil.\n" + "\n".join(f"• {x}" for x in b["lines"])
        t = st["total"]
        lines = [f"💰 Schatkist {_eur(t['equity_eur'])} ({_pct(t['pnl_pct'])} sinds start, "
                 f"{_pct(t['day_pnl_pct'])} laatste 24 uur)"]
        if t.get("benchmark_eur"):
            lines.append(f"Vasthouden zou {_eur(t['benchmark_eur'])} zijn")
        for d in st["desks"]:
            lines.append(f"• {d['name']}: {_eur(d['equity_eur'])} ({_pct(d['pnl_pct'])})")
        lines.append("🛑 Noodstop staat AAN" if kill.exists() else f"Status: {h['status']}")
        return "\n".join(lines)
    if cmd == "/waarom":
        if len(parts) < 2:
            return "Welk instrument? Bijvoorbeeld: /waarom BTC"
        want = parts[1].upper()
        best = None
        for cls in DESK_ORDER:
            book = home / "data" / "desks" / f"{cls}.sqlite3"
            if not book.exists():
                continue
            for ts, _, p in Store(book).events("decision", limit=300):
                sym = p["instrument"].upper()
                if (sym == want or sym.split("-")[0] == want or sym.split("=")[0] == want) and p.get("approved"):
                    if best is None or ts > best[0]:
                        best = (ts, cls, p)
                    break
        if not best:
            return f"Ik vind geen uitgevoerde trade in {want}."
        ts, cls, p = best
        verb = "kocht" if p["side"] == "buy" else "verkocht"
        return (f"{DESK_NAMES.get(cls, cls)} {verb} {p['instrument']} op {ts:%d-%m %H:%M} UTC "
                f"voor ca. {_eur(p['size_eur'])}.\nWaarom: {p.get('signal_reason') or 'onbekend'}.\n"
                f"Risico-check: {p['reason']}.")
    return "Dat commando ken ik niet.\n" + HELP


def listen(config: HoldingConfig, home: Path, client, log=print, now: datetime | None = None) -> int:
    """Nieuwe berichten ophalen en beantwoorden. Geeft het aantal uitgevoerde commando's terug."""
    now = now or datetime.now(tz=UTC)
    market = Store(home / "data" / "holding.sqlite3")
    chat = market.get_state("telegram", {}).get("chat")
    if not chat:
        log("Jarvis: nog geen chat verbonden")
        return 0
    memo_path = home / "jarvis.json"
    memo = json.loads(memo_path.read_text()) if memo_path.exists() else {}
    updates = client.call("getUpdates", {"offset": memo.get("offset", 0), "timeout": 0}).get("result", [])
    done = 0
    for upd in updates:
        memo["offset"] = upd["update_id"] + 1
        msg = upd.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != str(chat):
            log("Jarvis: bericht van een onbekende chat genegeerd")
            continue
        text = msg.get("text") or ""
        try:
            reply = answer(text, config, home, market, now)
        except Exception as exc:   # een fout in één antwoord mag Jarvis niet stilleggen
            reply = f"Er ging iets mis bij dat commando ({type(exc).__name__})."
        client.send(chat, reply)
        done += 1
        log(f"Jarvis: commando {text.split()[0] if text else '?'} beantwoord")
    memo_path.write_text(json.dumps(memo), encoding="utf-8")
    return done

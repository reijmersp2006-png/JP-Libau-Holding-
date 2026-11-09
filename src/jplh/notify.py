"""Jarvis op je telefoon: meldingen via een eigen Telegram-bot.

Zet de token van je bot in de omgevingsvariabele ``TELEGRAM_TOKEN`` (op GitHub: een repository
secret). Stuur je bot één bericht; Jarvis vindt daarmee zelf je chat en onthoudt die.
Meldingen gaan alleen naar die ene chat. Een mislukte melding stopt het handelen nooit."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from jplh.data.http import USER_AGENT, ssl_context
from jplh.jarvis import AMS
from jplh.store import Store

API = "https://api.telegram.org/bot{token}/{method}"
BRIEFING_HOUR = 8          # dagbriefing bij de eerste ronde na 08:00 Nederlandse tijd


class Telegram:
    def __init__(self, token: str, timeout: float = 10.0) -> None:
        self.token = token
        self.timeout = timeout

    def call(self, method: str, params: dict | None = None) -> dict:
        url = API.format(token=self.token, method=method)
        data = urllib.parse.urlencode(params or {}).encode()
        req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=ssl_context()) as resp:
                out = json.loads(resp.read())
        except Exception as exc:   # de token staat in de url: nooit de url in een foutmelding
            raise RuntimeError(f"Telegram {method} mislukt: {type(exc).__name__}") from None
        if not out.get("ok"):
            raise RuntimeError(f"Telegram {method} geweigerd: {out.get('description', '?')}")
        return out

    def find_chat(self) -> str | None:
        """De chat van de laatste persoon die de bot een bericht stuurde (alleen privéchats)."""
        for upd in reversed(self.call("getUpdates").get("result", [])):
            chat = (upd.get("message") or {}).get("chat") or {}
            if chat.get("type") == "private":
                return str(chat["id"])
        return None

    def send(self, chat: str, text: str) -> None:
        self.call("sendMessage", {"chat_id": chat, "text": text[:4000], "disable_web_page_preview": "true"})


def messages(state: dict, memory: dict, now: datetime) -> list[str]:
    """Wat er sinds de vorige ronde het melden waard is. ``memory`` wordt bijgewerkt."""
    out = []
    names = {d["id"]: d.get("name", d["id"]) for d in state.get("desks", [])}
    seen = memory.get("seen_ts") or (now - timedelta(hours=1)).isoformat()
    trades = [f for f in state.get("feed", []) if f["kind"] == "trade" and f["ts"] > seen]
    for f in reversed(trades[:8]):
        why = f" Waarom: {f['why']}." if f.get("why") else ""
        out.append(f"💱 {names.get(f['desk'], f['desk'])}: {f['text']}.{why}")
    if len(trades) > 8:
        out.append(f"…en nog {len(trades) - 8} trades, zie het dashboard.")
    alerts = [a for a in state.get("lab", {}).get("alerts", []) if a.get("level") == "groot" and a["ts"] > seen]
    for a in alerts[:3]:
        out.append(f"🔭 Verkenners: {a['text']}")
    memory["seen_ts"] = state.get("generated_at", now.isoformat())

    weather = {w["name"]: w["ok"] for w in state.get("market_weather", [])}
    for name, ok in weather.items():
        before = memory.get("weather", {}).get(name)
        if before is not None and before != ok:
            out.append(f"{'☀️' if ok else '⛈️'} Marktweer {name} is omgeslagen naar {'goed' if ok else 'slecht'}.")
    memory["weather"] = weather

    h = state.get("jarvis", {}).get("health", {"status": "ok", "issues": []})
    if h["status"] != memory.get("health", "ok"):
        if h["status"] == "ok":
            out.append("✅ Alles draait weer normaal.")
        else:
            icon = "🚨" if h["status"] == "alarm" else "⚠️"
            out.append(f"{icon} {h['status'].capitalize()}: " + "; ".join(i["text"] for i in h["issues"][:4]))
    memory["health"] = h["status"]

    local = now.astimezone(AMS)
    today = local.date().isoformat()
    if local.hour >= BRIEFING_HOUR and memory.get("briefing_day") != today:
        b = state.get("jarvis", {}).get("briefing")
        if b:
            out.insert(0, f"🤖 {b['hello']} Phil. Dagbriefing:\n" + "\n".join(f"• {x}" for x in b["lines"]))
        memory["briefing_day"] = today
    return out


def notify(state: dict, market: Store, now: datetime, log=print, token: str | None = None,
           client: Telegram | None = None) -> int:
    """Stuurt de meldingen van deze ronde. Geeft het aantal verstuurde berichten terug."""
    token = token or os.environ.get("TELEGRAM_TOKEN")
    if not token and client is None:
        return 0
    if state.get("demo"):
        return 0
    tg = client or Telegram(token)
    memory = market.get_state("telegram", {})
    try:
        chat = os.environ.get("TELEGRAM_CHAT_ID") or memory.get("chat") or tg.find_chat()
        if not chat:
            log("Telegram: nog geen chat gevonden. Stuur je bot eerst een bericht.")
            return 0
        first = "chat" not in memory
        memory["chat"] = chat
        msgs = messages(state, memory, now)
        if first:
            msgs.insert(0, "🤖 Jarvis van JP-libau Holding is verbonden. Je krijgt hier trades, "
                           "noodremmen, waarschuwingen en elke ochtend een briefing.")
        for m in msgs:
            tg.send(chat, m)
        market.set_state("telegram", memory)
        if msgs:
            log(f"Telegram: {len(msgs)} melding(en) verstuurd")
        return len(msgs)
    except RuntimeError as exc:
        log(f"Telegram: {exc}")
        return 0

"""Jarvis luistert: commando's van Phil via Telegram.

Alleen berichten uit de chat die bij het verbinden is vastgelegd tellen; van iedereen anders
wordt niets uitgevoerd. Commando's veranderen nooit een strategie. Ze lezen de stand, zetten
de noodstop aan of uit (het bestand ``KILL``, dat elke order blokkeert) of zetten koersalarmen.
Een alarm is alleen een melding: het koopt of verkoopt nooit iets."""

from __future__ import annotations

import json
import math
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
        "/afdeling crypto - één afdeling: posities, cash en waarom\n"
        "/stress - wat als het misgaat (slechtste maand, crashscenario's)\n"
        "/lessen - wat de holding de laatste tijd leerde\n"
        "/leren - wat de Academie weet: voorspellingen, scores en de toeval-toets\n"
        "/coach meme - wat de coach van een afdeling weet, getoetst op onze koersen\n"
        "/maand - de maandafsluiting (of /maand oktober)\n"
        "/alarm BTC 80000 - seintje zodra BTC die koers raakt\n"
        "/alarmen - je alarmen bekijken\n"
        "/alarm weg BTC - alarmen voor BTC weghalen (/alarm weg alles: allemaal)\n"
        "/noodstop - direct alles stil (geen enkele order meer)\n"
        "/hervat - noodstop weer uit\n"
        "/help - dit lijstje")


MAX_ALARMS = 10


def _find(config: HoldingConfig, want: str):
    """Een instrument of verkenner-symbool bij een korte naam als BTC, ASML of GC."""
    want = want.upper()
    for item in list(config.instruments) + list(config.watch):
        sym = item.symbol.upper()
        if want in (sym, sym.split("-")[0], sym.split("=")[0], sym.split(".")[0], sym.lstrip("^")):
            return item
    return None


def _unit(item) -> str:
    cur = getattr(item, "currency", None)
    if item.source == "bitvavo" or cur == "EUR":
        return "€"
    return f"{cur} " if cur else ""


def _num(x: float, unit: str = "") -> str:
    """Een koers leesbaar in Nederlandse notatie, met genoeg decimalen voor kleine munten."""
    d = 2 if x <= 0 else min(10, max(2, 4 - math.floor(math.log10(x))))
    if x >= 1000:
        d = 2 if x < 10_000 else 0
    txt = f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{unit}{txt}"


def _parse_level(raw: str, near: float) -> float | None:
    """'80000', '80.000', '1,085' en '0,00001' worden allemaal goed gelezen. Bij twijfel
    (is '80.000' tachtigduizend of tachtig?) kiezen we wat het dichtst bij de koers nu ligt."""
    raw = raw.replace("€", "").replace("$", "").strip()
    options = set()
    for cand in (raw.replace(",", "."), raw.replace(".", "").replace(",", "."), raw.replace(",", "")):
        try:
            v = float(cand)
        except ValueError:
            continue
        if v > 0 and math.isfinite(v):
            options.add(v)
    if not options:
        return None
    return min(options, key=lambda v: abs(math.log(v / near)) if near > 0 else 0)


def live_price(item, sources) -> float:
    """De koers van nu: de slotkoers van de lopende uurcandle."""
    candles = sources[item.source].candles(item.symbol, "1h", 3)
    if not candles:
        raise ValueError("geen koers")
    return candles[-1].close


def _alarm(parts: list[str], config: HoldingConfig, memo: dict, sources, now: datetime) -> str:
    alarms = memo.setdefault("alarms", [])
    if len(parts) < 2 or parts[0].lower() in ("/alarmen",):
        if not alarms:
            return "Je hebt geen alarmen. Zet er een met bijvoorbeeld /alarm BTC 80000"
        return "🔔 Je alarmen:\n" + "\n".join(
            f"• {a['symbol']} {a['dir']} {_num(a['level'], a['unit'])}" for a in alarms)
    if parts[1].lower() in ("weg", "wis", "uit", "stop"):
        if len(parts) < 3:
            return "Welke? Bijvoorbeeld: /alarm weg BTC, of /alarm weg alles"
        if parts[2].lower() == "alles":
            n = len(alarms)
            alarms.clear()
            return f"Alle {n} alarm(en) weggehaald." if n else "Er stonden geen alarmen."
        item = _find(config, parts[2])
        sym = item.symbol if item else parts[2].upper()
        keep = [a for a in alarms if a["symbol"] != sym]
        gone = len(alarms) - len(keep)
        alarms[:] = keep
        return f"{gone} alarm(en) voor {sym} weggehaald." if gone else f"Er stond geen alarm voor {sym}."
    if len(parts) < 3:
        return "Op welke koers? Bijvoorbeeld: /alarm BTC 80000"
    item = _find(config, parts[1])
    if item is None:
        return f"{parts[1].upper()} ken ik niet. Ik volg alleen de instrumenten van de holding en de verkenners."
    if len(alarms) >= MAX_ALARMS:
        return f"Je hebt al {MAX_ALARMS} alarmen. Haal er eerst een weg met /alarm weg ..."
    price = live_price(item, sources)
    level = _parse_level(parts[2], price)
    if level is None:
        return f"'{parts[2]}' is geen koers die ik kan lezen. Bijvoorbeeld: /alarm BTC 80000"
    unit = _unit(item)
    direction = "boven" if level > price else "onder"
    alarms.append({"symbol": item.symbol, "level": level, "dir": direction, "unit": unit,
                   "set_at": now.isoformat()})
    return (f"🔔 Genoteerd. {item.symbol} staat nu op {_num(price, unit)}. Ik meld het zodra hij "
            f"{'stijgt tot boven' if direction == 'boven' else 'zakt tot onder'} {_num(level, unit)}. "
            "Ik kijk elke 10 minuten. Een alarm koopt of verkoopt niets.")


def check_alarms(memo: dict, config: HoldingConfig, sources, log=print) -> list[str]:
    """Alarmen die geraakt zijn: melding terug, en het alarm gaat weg (één keer melden)."""
    alarms = memo.get("alarms") or []
    if not alarms:
        return []
    prices: dict[str, float | None] = {}
    out, keep = [], []
    for a in alarms:
        sym = a["symbol"]
        if sym not in prices:
            item = _find(config, sym)
            try:
                prices[sym] = live_price(item, sources) if item else None
            except Exception as exc:   # een koers die even niet lukt: volgende keer opnieuw
                log(f"Jarvis: koers {sym} mislukt ({type(exc).__name__})")
                prices[sym] = None
        px = prices[sym]
        hit = px is not None and (px >= a["level"] if a["dir"] == "boven" else px <= a["level"])
        if hit:
            out.append(f"🔔 Alarm: {sym} staat op {_num(px, a['unit'])}, {a['dir']} je grens van "
                       f"{_num(a['level'], a['unit'])}. Het alarm is nu uit.")
        else:
            keep.append(a)
    memo["alarms"] = keep
    return out


DESK_ALIASES = {"crypto": "crypto", "meme": "meme", "memes": "meme", "memecoins": "meme", "stocks": "stocks",
                "aandelen": "stocks", "beurs": "stocks", "beurstoren": "stocks", "metals": "metals",
                "metalen": "metals", "goud": "metals", "kluis": "metals", "fx": "fx", "valuta": "fx",
                "wisselhaven": "fx"}
MODE_NL = {"vasthouden": "vasthouden", "vasthouden_marktweer": "vasthouden, met marktweer",
           "actief": "actief handelen"}


def desk_text(state: dict, want: str) -> str:
    cls = DESK_ALIASES.get(want.lower())
    d = next((x for x in state.get("desks", []) if x["id"] == cls), None)
    if d is None:
        return "Welke afdeling? Kies uit: crypto, meme, aandelen, metalen, fx."
    lines = [f"🏢 {d['name']}: {_eur(d['equity_eur'])} ({_pct(d['pnl_pct'])} sinds start)",
             f"Werkwijze: {MODE_NL.get(d.get('mode'), d.get('mode') or '?')}. Status: {d['status']}."]
    if d.get("weather"):
        lines.append(f"🌤 {d['weather'][:1].upper()}{d['weather'][1:]}.")
    if d.get("paused_reason"):
        lines.append(f"⏸ Op pauze: {d['paused_reason']}")
    for p in sorted(d.get("positions", []), key=lambda p: -p["value_eur"]):
        lines.append(f"• {p['symbol']}: {_eur(p['value_eur'])} ({_pct(p['pnl_pct'])})")
    eq = d["equity_eur"] or 1
    lines.append(f"• cash: {_eur(d['cash_eur'])} ({d['cash_eur'] / eq:.0%})")
    lines.append(f"Kosten tot nu: {_eur(d.get('fees_eur', 0))}, {d.get('trades', 0)} {'trade' if d.get('trades') == 1 else 'trades'}.")
    return "\n".join(lines)


def stress_text(state: dict) -> str:
    st = state.get("stress")
    if not st:
        return "De stresstest is nog niet gedraaid. Probeer het na de volgende ronde."
    short = {k: DESK_NAMES[k] for k in DESK_NAMES}
    lines = [f"🧯 Stresstest op de holding van nu ({_eur(st['equity_eur'])}, {st['cash_pct']:.0%} cash)"]
    for r in st.get("real", []):
        what = "maand" if r["days"] <= 31 else "kwartaal"
        lines.append(f"• Slechtste echte {what}: {_pct(r['return'])} ({r['from']} tot {r['to']})")
    for sc in st.get("scenarios", []):
        paused = ", ".join(short.get(c, c) for c in sc["paused"])
        lines.append(f"• {sc['name']} ({sc['when']}): {_pct(sc['return'])}, over {_eur(sc['after_eur'])}"
                     + (f". Op pauze: {paused}" if paused else ""))
    lines.append(f"Een afdeling die meer dan {st['limit']:.0%} zakt, gaat op pauze tot jij haar hervat. "
                 "De scenario's zijn afgeronde aannames, geen metingen.")
    return "\n".join(lines)


def lessons_text(state: dict, n: int = 6) -> str:
    book = state.get("lessons") or {}
    items = book.get("items") or []
    if not items:
        return "Het lessenboek is nog leeg. De eerste lessen komen een week na de eerste weigeringen en aankopen."
    n_all = book.get("count", len(items))
    lines = [f"📚 Lessenboek ({n_all} {'les' if n_all == 1 else 'lessen'}). De nieuwste:"]
    lines += [f"• {x['ts'][8:10]}-{x['ts'][5:7]}: {x['text']}" for x in items[:n]]
    summ = book.get("summary") or {}
    for r in (summ.get("rules") or [])[:3]:
        lines.append(f"Regel {r['rule']}: {r['n']}x geweigerd, {r['saved']}x bespaarde dat geld "
                     f"(koers gemiddeld {_pct(r['avg_move'])} een week later).")
    if summ.get("entry"):
        e = summ["entry"]
        lines.append(f"Instappen: gemiddeld {_pct(abs(e['avg_gap'])).lstrip('+')} "
                     f"{'duurder' if e['avg_gap'] > 0 else 'goedkoper'} dan de twee weken erna ({e['n']} aankopen).")
    lines.append("Lessen veranderen zelf niets: een wijziging moet eerst winnen in de backtest.")
    return "\n".join(lines)


def short(label: str) -> str:
    """'trend(fast=20, slow=200, band=0.01)' -> 'trend 20/200', zoals op het dashboard."""
    import re
    out = re.sub(r"trend\(fast=(\d+), slow=(\d+)[^)]*\)", r"trend \1/\2", label)
    out = re.sub(r"momentum\(lookback=(\d+)[^)]*\)", r"momentum \1d", out)
    out = re.sub(r"uitbraak\(entry=(\d+), exit=(\d+)\)", r"uitbraak \1/\2", out)
    out = re.sub(r"terugkeer\(period=\d+, low=(\d+), high=(\d+)\)", r"terugkeer \1/\2", out)
    return out.replace("koop_en_houd", "koop-en-houd")


VERDICT_ICON = {"klopt": "✅", "klopt niet": "❌", "deels": "➖", "niet aangetoond": "❔", "te weinig data": "⏳"}


def coach_text(state: dict, want: str) -> str:
    cls = DESK_ALIASES.get(want.lower())
    C = state.get("coach")
    if not C:
        return "De coaches beginnen na de volgende ronde."
    if cls is None:
        return "Welke afdeling? Kies uit: crypto, meme, aandelen, metalen, fx."
    rules = C["desks"].get(cls, [])
    lines = [f"🧑‍🏫 {C['coaches'].get(cls, 'Coach')} ({DESK_NAMES.get(cls, cls)}): elke vuistregel getoetst op onze koersen."]
    for r in rules:
        tip = f" (tip van {C['coaches'].get(r['from'], r['from'])})" if r.get("from") else ""
        lines.append(f"{VERDICT_ICON.get(r['verdict'], '•')} {r['title']}{tip}: {r.get('text') or r['verdict']}")
    lines.append("Een coach handelt nooit. Wat hij leert, gaat alleen live als het wint in de backtest en jij ja zegt.")
    return "\n".join(lines)


def academy_text(state: dict) -> str:
    A = state.get("academy")
    if not A:
        return "De Academie opent na de volgende ronde. Dan schrijft ze de eerste voorspellingen op."
    h = A["h"]
    lines = [f"🎓 Academie: {A['forecasts']} voorspellingen in het boek sinds {A.get('first') or '–'}."]
    a = (A.get("live") or {}).get("all")
    if a:
        lines.append(f"Live klopten de strategieën in {a['hit']:.0%} van {a['n']} voorspellingen over {h} dagen "
                     f"(gewoon vasthouden: {a['base']:.0%}). Oordeel: {a['verdict']}.")
    else:
        lines.append(f"De eerste live-scores over {h} dagen komen een week na de eerste voorspelling.")
    for r in A.get("team", []):
        if r["strategy"] == "koop_en_houd":
            continue
        lines.append(f"• {DESK_NAMES.get(r['desk'], r['desk'])}, {short(r['strategy'])}: in het verleden "
                     f"{_pct(r['edge'])} per {h} dagen t.o.v. vasthouden ({r['verdict']})")
    lucky = [(d["name"], r) for d in ((state.get("arena") or {}).get("desks") or {}).values()
             for r in d.get("board", []) if r.get("luck") is not None]
    for name, r in lucky[:4]:
        lines.append(f"• Arena {name}: {r['name']} ligt voor, kans op geluk {r['luck']:.0%}")
    lines.append("De Academie verandert zelf niets: een verandering moet eerst winnen in de backtest, en jij beslist.")
    return "\n".join(lines)


def month_text(state: dict, now: datetime, want: str | None = None) -> str:
    from jplh.notify import MONTHS, month_close
    if want:
        w = want.lower()
        if len(w) == 7 and w[4] == "-":
            month = w
        elif w in MONTHS:
            m = MONTHS.index(w) + 1
            month = f"{now.year if m <= now.month else now.year - 1}-{m:02d}"
        else:
            return "Welke maand? Bijvoorbeeld /maand oktober of /maand 2026-10."
    else:
        month = f"{now.year}-{now.month:02d}"
    text = month_close(state, month)
    if text is None:
        return f"Over {month} heb ik nog geen cijfers."
    if month == f"{now.year}-{now.month:02d}":
        text = text.replace("Maandafsluiting", "Lopende maand").replace(", eindstand", ", stand nu")
    return text


def _state(config: HoldingConfig, home: Path, market: Store, now: datetime) -> dict:
    desks = open_desks(config, home, market)
    return build_state(config, desks, market, home, now)


def answer(text: str, config: HoldingConfig, home: Path, market: Store, now: datetime,
           memo: dict | None = None, sources=None) -> str:
    """Het antwoord van Jarvis op één bericht. ``memo`` (alarmen) wordt bijgewerkt."""
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
    if cmd in ("/afdeling", "/stress", "/lessen", "/leren", "/maand", "/coach"):
        if cmd in ("/afdeling", "/coach") and len(parts) < 2:
            return f"Welke afdeling? Bijvoorbeeld {cmd} crypto (of meme, aandelen, metalen, fx)."
        st = _state(config, home, market, now)
        if cmd == "/afdeling":
            return desk_text(st, parts[1])
        if cmd == "/stress":
            return stress_text(st)
        if cmd == "/lessen":
            return lessons_text(st)
        if cmd == "/leren":
            return academy_text(st)
        if cmd == "/coach":
            return coach_text(st, parts[1])
        return month_text(st, now, parts[1] if len(parts) > 1 else None)
    if cmd in ("/alarm", "/alarmen"):
        if sources is None:
            from jplh.data import live_sources
            sources = live_sources()
        return _alarm(parts, config, memo if memo is not None else {}, sources, now)
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


def listen(config: HoldingConfig, home: Path, client, log=print, now: datetime | None = None,
           sources=None) -> int:
    """Nieuwe berichten ophalen en beantwoorden, en alarmen nalopen.
    Geeft het aantal uitgevoerde commando's terug."""
    now = now or datetime.now(tz=UTC)
    if sources is None:
        from jplh.data import live_sources
        sources = live_sources()
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
            reply = answer(text, config, home, market, now, memo, sources)
        except Exception as exc:   # een fout in één antwoord mag Jarvis niet stilleggen
            reply = f"Er ging iets mis bij dat commando ({type(exc).__name__})."
        client.send(chat, reply)
        done += 1
        log(f"Jarvis: commando {text.split()[0] if text else '?'} beantwoord")
    for m in check_alarms(memo, config, sources, log):
        client.send(chat, m)
        log("Jarvis: alarm gemeld")
    memo_path.write_text(json.dumps(memo), encoding="utf-8")
    return done

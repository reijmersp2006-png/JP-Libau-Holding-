"""Lessenboek: alles wat de holding leert, op één plek.

Tot nu toe leerde alleen een afdeling die actief handelt iets, en alleen na een verkoop. Het
lessenboek kijkt ook naar wat de andere afdelingen doen:

1. Weigeringen. Een week nadat de Wachttoren een aankoop weigerde, kijkt het lab wat de koers
   deed. Steeg die, dan kostte de weigering rendement. Daalde die, dan bespaarde ze geld. Per
   regel wordt zo bijgehouden of hij zijn geld waard is.
2. Instapmoment. Twee weken na elke aankoop vergelijkt het lab de aankoopprijs met de gemiddelde
   koers van die twee weken. Zo zie je of een afdeling stelselmatig te duur instapt.
3. Backtests. Elke week komen de backtestcijfers van de holding en de stand van de arena in het
   boek. Zo is terug te zien hoe een idee zich ontwikkelt, en verdwijnt er niets.

Alles gebruikt alleen koersen die op het moment van beoordelen bekend waren. Lessen veranderen
zelf niets aan de handel: wie iets wil veranderen, moet eerst winnen in de backtest (de spelregel).
"""

from __future__ import annotations

from datetime import datetime, timedelta

REVIEW_AFTER = timedelta(days=7)    # zo lang na een weigering kijken we wat de koers deed
ENTRY_WINDOW = timedelta(days=14)   # zo lang na een aankoop vergelijken we de prijs
BACKTEST_EVERY = timedelta(days=7)
KIND = "lesson"


def add(market, now: datetime, topic: str, text: str, desk: str = "holding", **data) -> dict:
    lesson = {"topic": topic, "desk": desk, "text": text, **data}
    market.add_event(now, KIND, lesson)
    return lesson


def lessons(market, limit: int = 40) -> list[dict]:
    return [{"ts": ts.isoformat(), **p} for ts, _, p in market.events(kind=KIND, limit=limit)]


def _close_at(candles, t: datetime) -> float | None:
    """Slotkoers van de laatste periode die vóór ``t`` begon."""
    last = None
    for c in candles:
        if c.ts > t:
            break
        last = c.close
    return last


def _num(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def _pct(x: float) -> str:
    return f"{x * 100:+.1f}%".replace(".", ",")


def review_refusals(desk, market, now: datetime) -> list[dict]:
    """Een week na elke geweigerde aankoop: bespaarde de weigering geld, of kostte ze rendement?
    Dezelfde weigering die elk uur terugkomt, telt één keer per dag."""
    done = set(desk.meta.get("refusals_reviewed", []))
    out, seen = [], set()
    for ts, _, p in reversed(desk.holding.store.events(kind="decision", limit=5000)):
        if p.get("approved") or p.get("side") != "buy":
            continue
        rules = sorted(c["rule"] for c in p.get("checks", []) if not c["passed"])
        sym = p["instrument"]
        key = f"{sym}@{ts.date().isoformat()}@{'+'.join(rules)}"
        if key in done or key in seen or ts + REVIEW_AFTER > now:
            continue
        seen.add(key)
        candles = desk.market.candles(sym, "1h", known_at=now)
        p0, p1 = _close_at(candles, ts), _close_at(candles, ts + REVIEW_AFTER)
        if not p0 or not p1:
            continue
        move = p1 / p0 - 1
        verdict = "bespaarde geld" if move < 0 else "kostte rendement"
        rule = ", ".join(rules) or "onbekend"
        out.append(add(market, now, "weigering",
                       f"{sym}: de Wachttoren weigerde ({rule}); een week later stond de koers {_pct(move)}, "
                       f"dus de weigering {verdict}.", desk=desk.cls, instrument=sym, rules=rules, move=round(move, 4)))
        done.add(key)
    if out:
        desk.meta["refusals_reviewed"] = sorted(done)[-2000:]
        desk.holding._save()
    return out


def review_entries(desk, market, now: datetime) -> list[dict]:
    """Twee weken na elke aankoop: kocht de afdeling duur of goedkoop t.o.v. de weken erna?"""
    done = set(desk.meta.get("entries_reviewed", []))
    out = []
    for f in desk.holding.store.fills():
        if f.side.value != "buy":
            continue
        key = f"{f.instrument}@{f.ts.isoformat()}"
        if key in done or f.ts + ENTRY_WINDOW > now:
            continue
        candles = [c for c in desk.market.candles(f.instrument, "1h", known_at=now)
                   if f.ts < c.ts <= f.ts + ENTRY_WINDOW]
        done.add(key)
        if len(candles) < 24:
            continue
        p0 = _close_at(desk.market.candles(f.instrument, "1h", known_at=now), f.ts)
        if not p0:
            continue
        avg = sum(c.close for c in candles) / len(candles)
        gap = p0 / avg - 1          # > 0: duurder gekocht dan het gemiddelde erna
        word = "duurder" if gap > 0 else "goedkoper"
        out.append(add(market, now, "instap",
                       f"{f.instrument}: gekocht {_pct(abs(gap)).lstrip('+')} {word} dan de gemiddelde koers "
                       f"van de twee weken erna.", desk=desk.cls, instrument=f.instrument, gap=round(gap, 4)))
    if out or done - set(desk.meta.get("entries_reviewed", [])):
        desk.meta["entries_reviewed"] = sorted(done)[-2000:]
        desk.holding._save()
    return out


def record_backtests(market, now: datetime, arena: dict | None, risk: dict | None) -> dict | None:
    """Eén keer per week de backtest- en arenacijfers in het boek, met het verschil t.o.v. vorige keer."""
    last = market.get_state("lessons_backtest_at")
    if last and now - datetime.fromisoformat(last) < BACKTEST_EVERY:
        return None
    bt = (risk or {}).get("backtest")
    if not bt:
        return None
    prev = market.get_state("lessons_backtest") or {}
    base = bt["base"]
    change = ""
    if prev.get("sharpe") is not None:
        d = base["sharpe"] - prev["sharpe"]
        change = f" (vorige week {_num(prev['sharpe'])}, {'beter' if d > 0 else 'slechter' if d < 0 else 'gelijk'})"
    leaders = []      # alleen waar een uitdager voor ligt op wat live draait: dat is het nieuws
    for d in ((arena or {}).get("desks") or {}).values():
        if d.get("board") and not d["board"][0].get("live"):
            leaders.append(f"{d['name']}: {d['board'][0]['name']}")
    text = (f"Backtest hele holding: {_pct(base['return'])}, Sharpe {_num(base['sharpe'])}{change}, "
            f"diepste daling {_pct(-base['max_dd'])}. Risicodirecteur {'wint' if bt['wins'] else 'wint niet'}.")
    text += (" Uitdagers die nu voorliggen in de arena: " + "; ".join(leaders) + "." if leaders
             else " In de arena ligt nergens een uitdager voor op wat live draait.")
    lesson = add(market, now, "backtest", text, sharpe=round(base["sharpe"], 3), ret=round(base["return"], 4),
                 max_dd=round(base["max_dd"], 4), director_wins=bool(bt["wins"]))
    market.set_state("lessons_backtest", {"sharpe": base["sharpe"]})
    market.set_state("lessons_backtest_at", now.isoformat())
    return lesson


def summary(items: list[dict]) -> dict:
    """Wat het boek per onderwerp zegt: per regel of hij zijn geld waard is, en hoe goed we instappen."""
    rules: dict[str, list[float]] = {}
    for x in items:
        if x.get("topic") == "weigering":
            for r in x.get("rules") or ["onbekend"]:
                rules.setdefault(r, []).append(x["move"])
    gaps = [x["gap"] for x in items if x.get("topic") == "instap"]
    return {
        "rules": [{"rule": r, "n": len(m), "avg_move": sum(m) / len(m), "saved": sum(1 for v in m if v < 0)}
                  for r, m in sorted(rules.items(), key=lambda kv: -len(kv[1]))],
        "entry": {"n": len(gaps), "avg_gap": sum(gaps) / len(gaps)} if gaps else None,
    }

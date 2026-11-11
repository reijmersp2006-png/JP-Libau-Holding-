"""De Academie: de leerafdeling. Ze leert elke dag van alle medewerkers, niet alleen na een verkoop.

1. Voorspellingsboek. Na elke nieuwe dagkoers schrijft de Academie per instrument op wat élke
   strategie nu wil: erin (verwacht stijging) of eruit (verwacht daling of niets). Dat gebeurt
   vóórdat bekend is wat de koers doet, en het boek wordt nooit aangepast.
2. Scoren. Na 1, 7 en 30 dagen kijkt de Academie wat er echt gebeurde. Klopte "erin" (koers
   omhoog) of "eruit" (koers niet omhoog)? En wat leverde het signaal op t.o.v. gewoon vasthouden?
   Per strategie, per afdeling en per marktweer.
3. Belofte tegen praktijk. Hetzelfde wordt op het verleden uitgerekend (de backtest). Doet een
   strategie het live duidelijk slechter dan in het verleden, dan is dat een teken dat de
   backtest te mooi was.

Eerlijk blijven:
- Voorspellingen die elkaar overlappen (elke dag een voorspelling voor 7 dagen) zijn niet
  onafhankelijk. Voor de onzekerheid tellen we daarom maar één voorspelling per horizon.
- Zolang de onzekerheid te groot is, zegt de Academie "nog toeval" en trekt ze geen conclusie.
- De Academie verandert zelf niets aan de handel. Wie iets wil veranderen, moet eerst winnen
  in de backtest en dan beslist Phil (de spelregel).
"""

from __future__ import annotations

import json
import math
from bisect import bisect_left
from datetime import date, datetime, timedelta

from jplh.backtest import unit_prices
from jplh.strategies import BuyHold

HORIZONS = (1, 7, 30)
MAIN = 7                     # de horizon waar het dashboard en Jarvis mee werken
MIN_EFFECTIVE = 8            # minder onafhankelijke metingen dan dit: "nog toeval"
Z = 1.645                    # 90%-betrouwbaarheid
LEADER = {"crypto": "BTC-EUR", "meme": "BTC-EUR", "stocks": "IWDA.AS"}
HOLD = BuyHold().label

SCHEMA = """CREATE TABLE IF NOT EXISTS forecasts (
    day TEXT NOT NULL, symbol TEXT NOT NULL, desk TEXT NOT NULL, live TEXT, bull INTEGER,
    price REAL NOT NULL, wants TEXT NOT NULL, written_at TEXT NOT NULL, PRIMARY KEY (day, symbol))"""


def _weather(market, cls: str, now: datetime) -> int | None:
    """Marktweer zonder marge: staat de leider boven zijn 200-dagengemiddelde? (1/0/None)"""
    sym = LEADER.get(cls)
    if not sym:
        return None
    daily = market.candles(sym, "1d", known_at=now, limit=200)
    if len(daily) < 200:
        return None
    return int(daily[-1].close > sum(c.close for c in daily) / len(daily))


def write_forecasts(desks: dict, market, strategies, now: datetime) -> int:
    """Schrijft de voorspellingen voor de laatste dagkoers op, één keer per instrument per dag."""
    market.db.execute(SCHEMA)
    n = 0
    for cls, desk in desks.items():
        bull = _weather(market, cls, now)
        live = desk.selection()
        for inst in desk.instruments:
            daily = market.candles(inst.symbol, "1d", known_at=now)
            if len(daily) < 30:
                continue
            day = daily[-1].ts.date().isoformat()
            if market.db.execute("SELECT 1 FROM forecasts WHERE day=? AND symbol=?", (day, inst.symbol)).fetchone():
                continue
            unit = unit_prices(daily, inst)
            wants = {s.label: int(s.targets(unit)[-1]) for s in strategies}
            market.db.execute("INSERT OR IGNORE INTO forecasts VALUES (?,?,?,?,?,?,?,?)",
                              (day, inst.symbol, cls, live.get(inst.symbol), bull, unit[-1].close,
                               json.dumps(wants), now.isoformat()))
            n += 1
    market.db.commit()
    return n


def wilson(hits: float, n: float) -> tuple[float, float]:
    """90%-interval voor een trefkans."""
    if n <= 0:
        return 0.0, 1.0
    p = hits / n
    d = 1 + Z * Z / n
    mid = (p + Z * Z / (2 * n)) / d
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return max(0.0, mid - half), min(1.0, mid + half)


class Tally:
    """Telt voorspellingen: trefkans en opbrengst t.o.v. vasthouden."""

    __slots__ = ("n", "hits", "edge", "edge_sq", "base_hits", "days")

    def __init__(self):
        self.n, self.hits, self.edge, self.edge_sq, self.base_hits, self.days = 0, 0, 0.0, 0.0, 0, set()

    def add(self, want: int, r: float, day) -> None:
        self.n += 1
        self.hits += (r > 0) if want else (r <= 0)
        self.base_hits += r > 0                  # wat gewoon vasthouden had "voorspeld"
        self.edge += want * r - r                # opbrengst van het signaal min vasthouden
        self.edge_sq += (want * r - r) ** 2
        self.days.add(day)

    def out(self, h: int) -> dict:
        eff = max(1.0, len(self.days) / h)       # overlappende voorspellingen tellen als één
        frac = eff / self.n if self.n else 0.0
        hit = self.hits / self.n if self.n else None
        lo, hi = wilson(self.hits * frac, eff)
        base = self.base_hits / self.n if self.n else None
        edge = self.edge / self.n if self.n else None
        e_lo = e_hi = None
        if self.n > 1:
            var = max(0.0, self.edge_sq / self.n - edge * edge)
            half = Z * math.sqrt(var / eff)
            e_lo, e_hi = edge - half, edge + half
        # Het oordeel gaat over geld: levert het signaal meer op dan gewoon vasthouden?
        verdict = "nog toeval"
        if eff >= MIN_EFFECTIVE and e_lo is not None:
            if e_lo > 0:
                verdict = "beter dan vasthouden"
            elif e_hi < 0:
                verdict = "slechter dan vasthouden"
            else:
                verdict = "niet te onderscheiden van vasthouden"
        return {"n": self.n, "effective": round(eff, 1), "hit": hit, "lo": lo, "hi": hi, "base": base,
                "edge": edge, "edge_lo": e_lo, "edge_hi": e_hi, "verdict": verdict}


def _close_after(dates: list[date], closes: list[float], d: date) -> float | None:
    i = bisect_left(dates, d)
    return closes[i] if i < len(dates) else None


def score_live(market, config, now: datetime) -> dict:
    """Scoort het voorspellingsboek: alleen voorspellingen waarvan de horizon voorbij is."""
    market.db.execute(SCHEMA)
    rows = market.db.execute("SELECT day, symbol, desk, live, bull, price, wants FROM forecasts ORDER BY day").fetchall()
    insts = {i.symbol: i for i in config.instruments}
    series = {}
    tallies: dict[tuple, Tally] = {}

    def t(*key) -> Tally:
        return tallies.setdefault(key, Tally())

    today = now.date()
    for day, sym, cls, live, bull, price, wants in rows:
        if sym not in insts:
            continue
        if sym not in series:
            c = unit_prices(market.candles(sym, "1d", known_at=now), insts[sym])
            series[sym] = ([x.ts.date() for x in c], [x.close for x in c])
        d0 = date.fromisoformat(day)
        wants = json.loads(wants)
        weather = {1: "goed", 0: "slecht"}.get(bull, "geen")
        for h in HORIZONS:
            d1 = d0 + timedelta(days=h)
            if d1 > today:
                continue
            p1 = _close_after(*series[sym], d1)
            if p1 is None or not price:
                continue
            r = p1 / price - 1
            for label, w in wants.items():
                t(h, "strategy", label).add(w, r, day)
                t(h, "weather", label, weather).add(w, r, day)
            if live in wants:
                t(h, "live", cls).add(wants[live], r, day)
                t(h, "live_all").add(wants[live], r, day)
    out: dict = {"forecasts": len(rows), "first": rows[0][0] if rows else None,
                 "last": rows[-1][0] if rows else None, "horizons": {}}
    for h in HORIZONS:
        g = {k[1:]: v.out(h) for k, v in tallies.items() if k[0] == h}
        out["horizons"][str(h)] = {
            "all_live": g.get(("live_all",)),
            "desks": {k[1]: v for k, v in g.items() if k[0] == "live"},
            "strategies": {k[1]: v for k, v in g.items() if k[0] == "strategy"},
            "weather": {f"{k[1]}|{k[2]}": v for k, v in g.items() if k[0] == "weather"},
        }
    return out


def score_history(market, config, strategies, now: datetime, until: date | None = None,
                  h: int = MAIN) -> dict:
    """Dezelfde score op het verleden (de backtest), tot ``until`` (de start van het boek).
    Ook per instrument en per signaal (erin/eruit), voor de uitleg bij een trade."""
    strat_t: dict[str, Tally] = {}
    weather_t: dict[str, Tally] = {}
    desk_t: dict[str, Tally] = {}
    signal: dict[str, dict[str, dict]] = {}
    bull_of: dict[str, dict[date, int]] = {}
    for sym in set(LEADER.values()):
        c = market.candles(sym, "1d", known_at=now)
        closes, run = [x.close for x in c], {}
        for i in range(199, len(c)):
            run[c[i].ts.date()] = int(closes[i] > sum(closes[i - 199:i + 1]) / 200)
        bull_of[sym] = run
    for inst in config.instruments:
        leader = LEADER.get(inst.asset_class.value)
        daily = unit_prices(market.candles(inst.symbol, "1d", known_at=now), inst)
        if len(daily) < 250:
            continue
        dates = [c.ts.date() for c in daily]
        closes = [c.close for c in daily]
        per = signal.setdefault(inst.symbol, {})
        for s in strategies:
            tg = s.targets(daily)
            ins, outs = [0, 0], [0, 0]
            for i in range(200, len(daily)):
                d0 = dates[i]
                if until and d0 >= until:
                    break
                p1 = _close_after(dates, closes, d0 + timedelta(days=h))
                if p1 is None:
                    break
                r = p1 / closes[i] - 1
                w = tg[i]
                strat_t.setdefault(s.label, Tally()).add(w, r, d0)
                b = bull_of.get(leader, {}).get(d0) if leader else None
                wkey = f"{s.label}|{ {1: 'goed', 0: 'slecht'}.get(b, 'geen') }"
                weather_t.setdefault(wkey, Tally()).add(w, r, d0)
                desk_t.setdefault(f"{inst.asset_class.value}|{s.label}", Tally()).add(w, r, d0)
                box = ins if w else outs
                box[0] += 1
                box[1] += (r > 0) if w else (r <= 0)
            per[s.label] = {"in": ins, "out": outs}
    # Instrumenten bewegen vaak samen (crypto vooral), dus voor de onzekerheid telt per horizon
    # maar één meting, hoeveel instrumenten er die dag ook waren. Liever te voorzichtig dan te blij.
    return {"h": h, "strategies": {k: v.out(h) for k, v in strat_t.items()},
            "weather": {k: v.out(h) for k, v in weather_t.items()},
            "desks": {k: v.out(h) for k, v in desk_t.items()}, "signal": signal}


def promise_vs_practice(live: dict, history: dict) -> list[dict]:
    """Per strategie: wat beloofde de backtest, wat doet hij live? Alleen met genoeg live-data."""
    out = []
    lh = (live.get("horizons") or {}).get(str(MAIN), {}).get("strategies", {})
    for label, past in history.get("strategies", {}).items():
        now_ = lh.get(label)
        if not now_ or not now_["n"] or past["hit"] is None:
            continue
        if now_["effective"] < MIN_EFFECTIVE:
            verdict = "nog toeval"
        elif now_["hi"] < past["hit"]:
            verdict = "live slechter dan beloofd"
        else:
            verdict = "houdt zich aan de belofte"
        out.append({"strategy": label, "past": past["hit"], "live": now_["hit"], "lo": now_["lo"],
                    "hi": now_["hi"], "n": now_["n"], "verdict": verdict})
    out.sort(key=lambda r: (r["verdict"] == "nog toeval", -(r["n"])))
    return out


def signal_note(academy: dict | None, symbol: str, label: str, want: int) -> str:
    """Eén zin bij een trade: hoe vaak klopte dit signaal, en hoe vaak gewoon vasthouden?"""
    if not academy:
        return ""
    per = ((academy.get("history") or {}).get("signal") or {}).get(symbol) or {}
    mine, hold = per.get(label), per.get(HOLD)
    if label == HOLD or not mine or not hold:
        return ""
    n, hits = mine["in" if want else "out"]
    hn, hh = hold["in"]
    if n < 30 or not hn:
        return ""
    p, base = hits / n, hh / hn
    if want:
        return (f"Academie: als dit signaal 'erin' zei, stond {symbol} een week later in {_pc(p)} van de "
                f"{n} keer hoger (gewoon: {_pc(base)})")
    return (f"Academie: als dit signaal 'eruit' zei, stond {symbol} een week later in {_pc(p)} van de "
            f"{n} keer niet hoger (gewoon: {_pc(1 - base)})")


LUCK_BLOCK = 10       # dagen per blok: koersbewegingen hangen een paar dagen aan elkaar
LUCK_DRAWS = 1000
MAX_LUCK = 0.10       # een uitdager wordt pas voorgedragen als zijn voorsprong < 10% kans op geluk heeft


def luck(challenger: list[float], live: list[float], seed: int = 7) -> float | None:
    """Hoe groot is de kans dat de voorsprong van een uitdager puur geluk is?

    Blok-bootstrap op het dagelijkse verschil in rendement: we trekken duizenden keren een nieuwe
    geschiedenis uit stukken van 10 echte dagen, en kijken hoe vaak de uitdager dan níet wint."""
    import random
    n = min(len(challenger), len(live))
    if n < 2 * LUCK_BLOCK:
        return None
    diff = [a - b for a, b in zip(challenger[-n:], live[-n:])]
    if not any(diff):
        return 1.0
    mean = sum(diff) / n
    centred = [d - mean for d in diff]          # de wereld waarin er géén voorsprong is
    rng = random.Random(seed)
    blocks = n // LUCK_BLOCK
    sums = [sum(centred[i:i + LUCK_BLOCK]) for i in range(n - LUCK_BLOCK + 1)]
    need = mean * blocks * LUCK_BLOCK
    hits = sum(1 for _ in range(LUCK_DRAWS) if sum(rng.choices(sums, k=blocks)) >= need)
    return hits / LUCK_DRAWS


def _pc(x: float) -> str:
    return f"{x:.0%}"


def maybe_study(desks: dict, market, config, strategies, now: datetime, log=print) -> dict | None:
    """Elke ronde: voorspellingen opschrijven. Eén keer per dag: alles scoren en een les noteren."""
    try:
        n = write_forecasts(desks, market, strategies, now)
    except (ValueError, KeyError, ZeroDivisionError) as exc:      # de Academie mag de ronde nooit stoppen
        log(f"academie: voorspellen mislukt ({type(exc).__name__}: {exc})")
        n = 0
    if n:
        log(f"academie: {n} nieuwe voorspellingen in het boek")
    old = market.get_state("academy")
    if old and old.get("computed_at", "")[:10] == now.date().isoformat():
        return old
    try:
        live = score_live(market, config, now)
        until = date.fromisoformat(live["first"]) if live["first"] else None
        hist = score_history(market, config, strategies, now, until)
    except (ValueError, KeyError, ZeroDivisionError) as exc:
        log(f"academie: scoren mislukt ({type(exc).__name__}: {exc})")
        return old
    new = {"computed_at": now.isoformat(), "live": live, "history": hist,
           "promise": promise_vs_practice(live, hist)}
    market.set_state("academy", new)
    from jplh.lessons import add
    text = day_lesson(new)
    if text:
        add(market, now, "academie", text)
        log("lessenboek: " + text)
    return new


def day_lesson(academy: dict) -> str | None:
    live = academy.get("live") or {}
    h = (live.get("horizons") or {}).get(str(MAIN), {})
    a = h.get("all_live")
    if not live.get("forecasts"):
        return None
    if not a:
        return (f"Academie: {live['forecasts']} voorspellingen in het boek. De eerste {MAIN}-daagse "
                "scores komen een week na de eerste voorspelling.")
    text = (f"Academie: de live strategieën klopten in {a['hit']:.0%} van {a['n']} voorspellingen over "
            f"{MAIN} dagen (gewoon vasthouden: {a['base']:.0%}). Oordeel: {a['verdict']}.")
    bad = [p for p in academy.get("promise", []) if p["verdict"] == "live slechter dan beloofd"]
    if bad:
        text += f" Live slechter dan de backtest beloofde: {', '.join(p['strategy'] for p in bad[:3])}."
    return text


def for_dashboard(academy: dict | None, desks: dict) -> dict | None:
    """Het deel van de Academie dat het dashboard en Jarvis nodig hebben (zonder de grote tabellen)."""
    if not academy:
        return None
    live = academy.get("live") or {}
    main = (live.get("horizons") or {}).get(str(MAIN), {})
    hist = academy.get("history") or {}
    in_use = sorted({label for d in desks.values() for label in d.selection().values()})
    weather = {}
    for key, v in (hist.get("weather") or {}).items():
        label, w = key.split("|")
        if label in in_use or label == HOLD:
            weather.setdefault(label, {})[w] = v
    strategies = sorted(hist.get("strategies", {}).items(), key=lambda kv: -(kv[1]["edge"] or 0))
    team = []      # elke live keuze, beoordeeld in haar eigen afdeling
    for cls, d in desks.items():
        for label in sorted(set(d.selection().values())):
            v = (hist.get("desks") or {}).get(f"{cls}|{label}")
            hold = (hist.get("desks") or {}).get(f"{cls}|{HOLD}")
            if v:
                team.append({"desk": cls, "strategy": label, **v, "hold_hit": hold["hit"] if hold else None})
    return {
        "computed_at": academy.get("computed_at"), "h": MAIN,
        "forecasts": live.get("forecasts", 0), "first": live.get("first"),
        "live": {"all": main.get("all_live"), "desks": main.get("desks", {}),
                 "by_horizon": {h: (live.get("horizons") or {}).get(h, {}).get("all_live")
                                for h in map(str, HORIZONS)}},
        "history": [{"strategy": k, **v} for k, v in strategies],
        "in_use": in_use, "weather": weather, "team": team,
        "promise": academy.get("promise", [])[:12],
    }

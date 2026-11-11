"""Coaches: per afdeling een expert die de vakkennis van die markt kent, en een teamoverleg.

Een coach kent de vuistregels die ervaren handelaren in zijn markt gebruiken ("na een pomp volgt
een dump", "goud is een schuilplaats"). Hij neemt ze niet blind over: elke vuistregel wordt
getoetst op onze eigen koersen. Pas als de data hem steunt, heet hij "klopt". Spreekt de data
hem tegen, dan zegt de coach dat ook. Zo worden de afdelingen experts zonder bijgeloof.

Samenwerking: een deel van de vuistregels gaat over twee afdelingen tegelijk (bitcoin en memes,
de beurs en crypto, crypto en goud). Gebeurt zoiets vandaag, dan waarschuwt de ene coach de
andere afdeling. Eén keer per week is er teamoverleg: elke coach deelt zijn sterkste les, en
de Academie laat zien welke strategie waar werkt, zodat afdelingen van elkaar leren.

Coaches handelen nooit en veranderen niets aan de regels. Een tip staat alleen bij de uitleg
van een trade. Wie iets wil veranderen, moet eerst winnen in de backtest (de spelregel).
"""

from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass
from datetime import date, datetime, timedelta

Z = 1.645                 # 90%-betrouwbaarheid
MIN_EVENTS = 5
TEAM_EVERY = timedelta(days=7)
DESK_NAMES = {"crypto": "Crypto Lab", "meme": "Meme Arcade", "stocks": "Beurstoren", "metals": "De Kluis",
              "fx": "Wisselhaven"}
COACHES = {"crypto": "Coach Satoshi", "meme": "Coach Pepe", "stocks": "Coach Warren", "metals": "Coach Goudhaan",
           "fx": "Coach Forex"}


# ------------------------------------------------------------------ rekenwerk

class Series:
    """Slotkoersen per dag, alleen wat op ``now`` bekend was."""

    def __init__(self, market, symbol: str, now: datetime, invert: bool = False):
        cs = market.candles(symbol, "1d", known_at=now)
        self.dates = [c.ts.date() for c in cs]
        self.closes = [(1 / c.close if invert else c.close) for c in cs if c.close > 0]
        self.dates = self.dates[:len(self.closes)]
        self.by = dict(zip(self.dates, self.closes))

    def __len__(self):
        return len(self.dates)

    def at_or_after(self, d: date) -> float | None:
        i = bisect_left(self.dates, d)
        return self.closes[i] if i < len(self.dates) else None

    def ret(self, d0: date, days: int) -> float | None:
        p0, p1 = self.by.get(d0), self.at_or_after(d0 + timedelta(days=days))
        if not p0 or not p1 or d0 + timedelta(days=days) > self.dates[-1]:
            return None
        return p1 / p0 - 1

    def daily(self) -> dict[date, float]:
        return {d: b / a - 1 for d, a, b in zip(self.dates[1:], self.closes, self.closes[1:])}

    def back(self, d: date, days: int) -> float | None:
        """Rendement over de ``days`` dagen tot en met ``d``."""
        p1 = self.by.get(d)
        i = bisect_left(self.dates, d - timedelta(days=days))
        if not p1 or i >= len(self.dates):
            return None
        return p1 / self.closes[i] - 1


def _mean_sd(xs: list[float]) -> tuple[float, float]:
    n = len(xs)
    m = sum(xs) / n
    return m, math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0


def event_study(events: list[date], target: Series, days: int, expect: int) -> dict:
    """Wat deed ``target`` in de ``days`` dagen na elk moment uit ``events``, vergeleken met normaal?
    Momenten die dichter dan ``days`` bij elkaar liggen tellen als één (anders tel je hetzelfde dubbel).
    ``expect`` = +1 als de vuistregel stijging voorspelt, -1 bij daling."""
    kept, last = [], None
    for d in sorted(events):
        if last is None or (d - last).days >= days:
            r = target.ret(d, days)
            if r is not None:
                kept.append(r)
                last = d
    base = [r for d in target.dates[::max(1, days)] if (r := target.ret(d, days)) is not None]
    if len(kept) < MIN_EVENTS or len(base) < 10:
        return {"n": len(kept), "verdict": "te weinig data"}
    m, sd = _mean_sd(kept)
    b, _ = _mean_sd(base)
    half = Z * sd / math.sqrt(len(kept))
    diff = m - b
    if abs(diff) <= half:
        verdict = "niet aangetoond"
    else:
        verdict = "klopt" if (diff > 0) == (expect > 0) else "klopt niet"
    return {"n": len(kept), "avg": m, "base": b, "lo": diff - half, "hi": diff + half, "verdict": verdict}


def beta(y: dict[date, float], x: dict[date, float]) -> dict:
    """Hoe hard beweegt y mee met x? (1 = even hard, 2 = twee keer zo hard)"""
    common = [d for d in y if d in x]
    if len(common) < 60:
        return {"n": len(common), "verdict": "te weinig data"}
    xs, ys = [x[d] for d in common], [y[d] for d in common]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((a - mx) ** 2 for a in xs)
    if sxx <= 0:
        return {"n": len(common), "verdict": "te weinig data"}
    b = sum((a - mx) * (c - my) for a, c in zip(xs, ys)) / sxx
    resid = sum((c - my - b * (a - mx)) ** 2 for a, c in zip(xs, ys))
    se = math.sqrt(resid / (len(xs) - 2) / sxx)
    sy = math.sqrt(sum((c - my) ** 2 for c in ys))
    corr = b * math.sqrt(sxx) / sy if sy > 0 else 0.0
    return {"n": len(common), "beta": b, "lo": b - Z * se, "hi": b + Z * se, "corr": corr}


def _p(x: float, d: int = 1) -> str:
    return f"{x * 100:+.{d}f}%".replace(".", ",")


def _f(x: float, d: int = 2) -> str:
    return f"{x:.{d}f}".replace(".", ",")


def _days(series: Series, test) -> list[date]:
    return [d for d in series.dates if test(d)]


# ------------------------------------------------------------------ de vuistregels

@dataclass
class Rule:
    id: str
    desk: str                 # van welke coach (bij samenwerking: de afdeling die waarschuwt)
    title: str                # de vuistregel, zoals een expert hem zegt
    why: str                  # de achtergrond
    test: callable            # (market, now, config) -> dict met verdict en tekst
    partner: str | None = None  # samenwerking: welke afdeling hoort het ook


def _sector(market, now, syms):
    return {s: Series(market, s, now) for s in syms}


def t_alts_follow_btc(market, now, config):
    btc = Series(market, "BTC-EUR", now).daily()
    res = [beta(Series(market, s, now).daily(), btc) for s in ("ETH-EUR", "SOL-EUR", "XRP-EUR")]
    res = [r for r in res if "beta" in r]
    if not res:
        return {"verdict": "te weinig data"}
    avg = sum(r["beta"] for r in res) / len(res)
    lo = min(r["lo"] for r in res)
    verdict = "klopt" if lo > 1 else "klopt niet" if max(r["hi"] for r in res) < 1 else "deels"
    return {"verdict": verdict, "value": avg,
            "text": f"ETH, SOL en XRP bewegen gemiddeld {_f(avg)} keer zo hard als bitcoin."}


def t_btc_dip_recovers(market, now, config):
    btc = Series(market, "BTC-EUR", now)
    r1 = btc.daily()
    ev = event_study([d for d, r in r1.items() if r <= -0.06], btc, 7, +1)
    return _event_text(ev, "na een dag met -6% of meer stond bitcoin een week later gemiddeld", "een gewone week")


def t_crypto_weekend(market, now, config):
    r = Series(market, "BTC-EUR", now).daily()
    we = [abs(v) for d, v in r.items() if d.weekday() >= 5]
    wd = [abs(v) for d, v in r.items() if d.weekday() < 5]
    if len(we) < 30:
        return {"verdict": "te weinig data"}
    a, sa = _mean_sd(we)
    b, sb = _mean_sd(wd)
    half = Z * math.sqrt(sa * sa / len(we) + sb * sb / len(wd))
    verdict = "klopt" if b - a > half else "klopt niet" if a - b > half else "niet aangetoond"
    return {"verdict": verdict, "value": a / b,
            "text": f"In het weekend beweegt bitcoin gemiddeld {_p(a, 2).lstrip('+')} per dag, "
                    f"doordeweeks {_p(b, 2).lstrip('+')}."}


def t_meme_pump_dump(market, now, config):
    rets, base = [], []
    for sym in ("DOGE-EUR", "SHIB-EUR", "PEPE-EUR"):
        ser = Series(market, sym, now)
        base += [r for d in ser.dates[::14] if (r := ser.ret(d, 14)) is not None]
        last = None
        for d in ser.dates:
            week = ser.back(d, 7)
            if week is None or week < 0.5 or (last and (d - last).days < 14):
                continue                     # dezelfde pomp niet dubbel tellen
            r = ser.ret(d, 14)
            if r is not None:
                rets.append(r)
                last = d
    if len(rets) < MIN_EVENTS or len(base) < 10:
        return {"verdict": "te weinig data", "n": len(rets),
                "text": f"Nog te weinig pompen om te toetsen ({len(rets)})."}
    m, sd = _mean_sd(rets)
    b, _ = _mean_sd(base)
    half = Z * sd / math.sqrt(len(rets))
    verdict = "niet aangetoond" if abs(m - b) <= half else "klopt" if m < b else "klopt niet"
    return {"verdict": verdict, "n": len(rets), "avg": m, "base": b,
            "text": f"Na een week met +50% of meer deed een memecoin de twee weken erna gemiddeld {_p(m)} "
                    f"(normaal {_p(b)}), gemeten op {len(rets)} pompen."}


def t_meme_beta(market, now, config):
    btc = Series(market, "BTC-EUR", now).daily()
    res = [beta(Series(market, s, now).daily(), btc) for s in ("DOGE-EUR", "SHIB-EUR", "PEPE-EUR")]
    res = [r for r in res if "beta" in r]
    if not res:
        return {"verdict": "te weinig data"}
    avg = sum(r["beta"] for r in res) / len(res)
    verdict = "klopt" if min(r["lo"] for r in res) > 1.3 else "deels" if avg > 1.3 else "klopt niet"
    return {"verdict": verdict, "value": avg,
            "text": f"Memecoins bewegen gemiddeld {_f(avg)} keer zo hard als bitcoin."}


def t_meme_deep_falls(market, now, config):
    falls = {}
    for s in ("DOGE-EUR", "SHIB-EUR", "PEPE-EUR"):
        cl = Series(market, s, now).closes
        if len(cl) < 200:
            continue
        peak, dd = cl[0], 0.0
        for c in cl:
            peak = max(peak, c)
            dd = max(dd, 1 - c / peak)
        falls[s.split("-")[0]] = dd
    if not falls:
        return {"verdict": "te weinig data"}
    verdict = "klopt" if all(v >= 0.7 for v in falls.values()) else "deels" if any(v >= 0.7 for v in falls.values()) else "klopt niet"
    txt = ", ".join(f"{k} -{v:.0%}" for k, v in falls.items())
    return {"verdict": verdict, "text": f"Diepste val sinds we koersen hebben: {txt}."}


def t_meme_needs_btc(market, now, config):
    btc = Series(market, "BTC-EUR", now)
    up = set()
    for i in range(199, len(btc.closes)):
        if btc.closes[i] > sum(btc.closes[i - 199:i + 1]) / 200:
            up.add(btc.dates[i])
    good, bad = [], []
    for s in ("DOGE-EUR", "SHIB-EUR", "PEPE-EUR"):
        for d, r in Series(market, s, now).daily().items():
            if d >= btc.dates[min(199, len(btc.dates) - 1)]:
                (good if d in up else bad).append(r)
    if len(good) < 60 or len(bad) < 60:
        return {"verdict": "te weinig data"}
    a, sa = _mean_sd(good)
    b, sb = _mean_sd(bad)
    half = Z * math.sqrt(sa * sa / len(good) + sb * sb / len(bad))
    verdict = "klopt" if a - b > half else "klopt niet" if b - a > half else "niet aangetoond"
    return {"verdict": verdict,
            "text": f"Bij goed bitcoin-weer deden memes gemiddeld {_p(a * 30)} per maand, bij slecht weer {_p(b * 30)}."}


def t_world_dip(market, now, config):
    w = Series(market, "IWDA.AS", now)
    ev = event_study([d for d, r in w.daily().items() if r <= -0.02], w, 30, +1)
    return _event_text(ev, "na een beursdag met -2% of meer stond de wereldindex een maand later gemiddeld",
                       "een gewone maand")


def t_spread_is_calmer(market, now, config):
    def vol(s):
        r = list(Series(market, s, now).daily().values())
        return _mean_sd(r)[1] * math.sqrt(252) if len(r) > 60 else None
    idx = vol("IWDA.AS")
    singles = [v for s in ("ASML.AS", "AAPL", "MSFT", "NVDA") if (v := vol(s))]
    if not idx or not singles:
        return {"verdict": "te weinig data"}
    avg = sum(singles) / len(singles)
    verdict = "klopt" if idx < avg * 0.8 else "niet aangetoond"
    return {"verdict": verdict, "text": f"De wereldindex beweegt {idx:.0%} per jaar, losse aandelen gemiddeld {avg:.0%}."}


def _fee_share(config, cls: str) -> tuple[float, float] | None:
    insts = [i for i in config.instruments if i.asset_class.value == cls]
    cost = config.costs[cls]
    if not insts:
        return None
    pot = config.start_capital_eur * config.desks.get(cls, 0) / len(insts)
    if pot <= 0:
        return None
    fee = max(cost.min_fee_eur, pot * cost.fee_pct) + pot * cost.slippage_pct
    return pot, fee / pot


def t_fees_eat_small_pots(market, now, config):
    got = _fee_share(config, "stocks")
    if not got:
        return {"verdict": "te weinig data"}
    pot, share = got
    moves = [abs(r) for d in Series(market, "IWDA.AS", now).dates[::30]
             if (r := Series(market, "IWDA.AS", now).ret(d, 30)) is not None]
    if not moves:
        return {"verdict": "te weinig data"}
    m = sum(moves) / len(moves)
    verdict = "klopt" if 2 * share > m / 4 else "klopt niet"
    return {"verdict": verdict,
            "text": f"Per aandeel zit er ongeveer €{pot:.0f} in. Kopen en verkopen kost samen {_p(2 * share, 2).lstrip('+')}, "
                    f"een gewone maand beweegt {_p(m, 1).lstrip('+')}. Daarom handelt de Beurstoren weinig."}


def t_gold_haven(market, now, config):
    w = Series(market, "IWDA.AS", now).daily()
    g = Series(market, "GC=F", now).daily()
    bad = [g[d] for d, r in w.items() if r <= -0.02 and d in g]
    allg = list(g.values())
    if len(bad) < MIN_EVENTS:
        return {"verdict": "te weinig data"}
    a, sa = _mean_sd(bad)
    b, _ = _mean_sd(allg)
    half = Z * sa / math.sqrt(len(bad))
    verdict = "klopt" if a - b > half else "klopt niet" if b - a > half else "niet aangetoond"
    return {"verdict": verdict, "n": len(bad),
            "text": f"Op {len(bad)} slechte beursdagen (-2% of meer) deed goud gemiddeld {_p(a, 2)} (normaal {_p(b, 2)})."}


def t_silver_wilder(market, now, config):
    r = beta(Series(market, "SI=F", now).daily(), Series(market, "GC=F", now).daily())
    if "beta" not in r:
        return {"verdict": "te weinig data"}
    verdict = "klopt" if r["lo"] > 1 else "klopt niet" if r["hi"] < 1 else "niet aangetoond"
    return {"verdict": verdict, "text": f"Zilver beweegt {_f(r['beta'])} keer zo hard als goud."}


def t_gold_dollar(market, now, config):
    r = beta(Series(market, "GC=F", now).daily(), Series(market, "EURUSD=X", now).daily())
    if "beta" not in r:
        return {"verdict": "te weinig data"}
    # EURUSD omhoog = zwakkere dollar. De vuistregel zegt: zwakke dollar, duur goud (in dollars).
    verdict = "klopt" if r["lo"] > 0 else "klopt niet" if r["hi"] < 0 else "niet aangetoond"
    return {"verdict": verdict,
            "text": f"Als de euro 1% duurder wordt tegen de dollar, beweegt goud (in dollars) gemiddeld {_p(r['beta'] / 100, 2)}; "
                    f"samenhang {_f(r['corr'])}."}


def t_fx_calm(market, now, config):
    got = _fee_share(config, "fx")
    if not got:
        return {"verdict": "te weinig data"}
    pot, share = got
    ser = Series(market, "EURUSD=X", now)
    moves = [abs(r) for d in ser.dates[::7] if (r := ser.ret(d, 7)) is not None]
    if not moves:
        return {"verdict": "te weinig data"}
    m = sum(moves) / len(moves)
    verdict = "klopt" if 2 * share > m / 2 else "klopt niet"
    return {"verdict": verdict,
            "text": f"Euro-dollar beweegt in een gewone week {_p(m, 2).lstrip('+')}; een order heen en terug kost "
                    f"{_p(2 * share, 2).lstrip('+')}. Daarom is vasthouden hier de baas."}


def t_chf_haven(market, now, config):
    w = Series(market, "IWDA.AS", now).daily()
    chf = Series(market, "EURCHF=X", now, invert=True).daily()    # omhoog = frank wordt sterker
    bad = [chf[d] for d, r in w.items() if r <= -0.02 and d in chf]
    if len(bad) < MIN_EVENTS:
        return {"verdict": "te weinig data"}
    a, sa = _mean_sd(bad)
    b, _ = _mean_sd(list(chf.values()))
    half = Z * sa / math.sqrt(len(bad))
    verdict = "klopt" if a - b > half else "klopt niet" if b - a > half else "niet aangetoond"
    return {"verdict": verdict, "n": len(bad),
            "text": f"Op slechte beursdagen werd de frank gemiddeld {_p(a, 2)} waard t.o.v. de euro (normaal {_p(b, 2)})."}


# samenwerking: regels die over twee afdelingen gaan

def t_btc_crash_memes(market, now, config):
    btc = Series(market, "BTC-EUR", now).daily()
    days = [d for d, r in btc.items() if r <= -0.05]
    rets, base = [], []
    for s in ("DOGE-EUR", "SHIB-EUR", "PEPE-EUR"):
        ser = Series(market, s, now)
        rets += [r for d in days if (r := ser.ret(d, 1)) is not None]
        base += [r for d in ser.dates if (r := ser.ret(d, 1)) is not None]
    if len(rets) < MIN_EVENTS:
        return {"verdict": "te weinig data"}
    m, sd = _mean_sd(rets)
    b, _ = _mean_sd(base)
    half = Z * sd / math.sqrt(len(rets) / 3)       # drie munten op dezelfde dag tellen als één
    verdict = "klopt" if b - m > half else "klopt niet" if m - b > half else "niet aangetoond"
    return {"verdict": verdict, "avg": m,
            "text": f"Na een bitcoin-dag van -5% of meer deden memes de dag erna gemiddeld {_p(m, 2)} (normaal {_p(b, 2)})."}


def t_stocks_to_crypto(market, now, config):
    w = Series(market, "IWDA.AS", now).daily()
    btc = Series(market, "BTC-EUR", now)
    ev = event_study([d for d, r in w.items() if r <= -0.02], btc, 3, -1)
    return _event_text(ev, "na een slechte beursdag (-2% of meer) deed bitcoin de drie dagen erna gemiddeld",
                       "drie gewone dagen")


def t_gold_when_crypto_crashes(market, now, config):
    btc = Series(market, "BTC-EUR", now).daily()
    g = Series(market, "GC=F", now)
    ev = event_study([d for d, r in btc.items() if r <= -0.06], g, 7, +1)
    return _event_text(ev, "na een crypto-crash (bitcoin -6% op een dag) deed goud de week erna gemiddeld",
                       "een gewone week")


def _event_text(ev: dict, lead: str, normal: str) -> dict:
    if "avg" not in ev:
        return {"verdict": ev["verdict"], "n": ev.get("n", 0),
                "text": f"Nog te weinig momenten om te toetsen ({ev.get('n', 0)})."}
    return {**ev, "text": f"{lead[0].upper()}{lead[1:]} {_p(ev['avg'])}, tegen {_p(ev['base'])} voor {normal} "
                          f"({ev['n']} keer gemeten)."}


RULES = [
    Rule("alts_volgen_btc", "crypto", "Bitcoin leidt, de rest volgt harder",
         "Bij crypto is bitcoin de grote broer. Als hij beweegt, bewegen kleinere munten mee, en meestal harder.",
         t_alts_follow_btc),
    Rule("btc_dip", "crypto", "Na een harde val bij bitcoin volgt herstel",
         "Veel handelaren 'kopen de dip'. De vraag is of dat bij bitcoin echt loont.", t_btc_dip_recovers),
    Rule("weekend", "crypto", "In het weekend is crypto rustiger",
         "Beurzen zijn dicht en grote partijen handelen minder. Crypto gaat door, maar met minder volume.",
         t_crypto_weekend),
    Rule("pomp_dump", "meme", "Na een pomp volgt een dump",
         "Memecoins stijgen vaak op hype. Als de hype uitdooft, verkopen de vroege kopers.", t_meme_pump_dump),
    Rule("meme_beta", "meme", "Memes bewegen veel harder dan bitcoin",
         "Memecoins zijn de wildste hoek van crypto: er zit geen bedrijf of netwerk achter, alleen aandacht.",
         t_meme_beta),
    Rule("diepe_val", "meme", "Bijna elke memecoin zakt ooit meer dan 70%",
         "Daarom houdt de Meme Arcade een klein potje en mag ze er snel uit.", t_meme_deep_falls),
    Rule("meme_weer", "meme", "Memes doen het alleen goed als bitcoin goed staat",
         "Memes zijn speelgeld van de markt. Als bitcoin zwak is, droogt dat speelgeld op.", t_meme_needs_btc),
    Rule("beurs_dip", "stocks", "Na een slechte beursdag herstelt de wereldindex",
         "Een brede index als de wereldindex valt vaak terug op lange termijn groei.", t_world_dip),
    Rule("spreiden", "stocks", "Spreiden maakt rustiger",
         "Eén bedrijf kan tegenvallen, duizenden bedrijven samen schommelen minder.", t_spread_is_calmer),
    Rule("vaste_kosten", "stocks", "Bij kleine bedragen eten vaste kosten de winst op",
         "Elke order kost minstens €1,25. Bij een potje van een paar tientjes is dat veel.", t_fees_eat_small_pots),
    Rule("goud_schuilplaats", "metals", "Goud is een schuilplaats als de beurs valt",
         "Als beleggers bang worden, zoeken ze iets dat niet failliet kan gaan.", t_gold_haven),
    Rule("zilver_wilder", "metals", "Zilver beweegt harder dan goud",
         "Zilver is ook een industriemetaal, dus het reageert ook op de economie.", t_silver_wilder),
    Rule("goud_dollar", "metals", "Zwakke dollar, duur goud",
         "Goud wordt in dollars verhandeld: als de dollar daalt, kost goud in dollars meer.", t_gold_dollar),
    Rule("valuta_rustig", "fx", "Valuta bewegen weinig, dus kosten wegen zwaar",
         "Grote munten bewegen meestal minder dan een procent per week.", t_fx_calm),
    Rule("frank_schuilplaats", "fx", "De Zwitserse frank is een schuilplaats",
         "Zwitserland is stabiel en heeft weinig schulden. In paniek kopen beleggers frank.", t_chf_haven),
    Rule("btc_crash_memes", "crypto", "Als bitcoin hard valt, krijgen memes de dag erna de klap",
         "De Crypto Lab ziet het eerst: memes reageren vaak een dag later en harder.", t_btc_crash_memes,
         partner="meme"),
    Rule("beurs_naar_crypto", "stocks", "Een slechte beursdag slaat over op crypto",
         "Als beleggers risico afbouwen, verkopen ze ook crypto.", t_stocks_to_crypto, partner="crypto"),
    Rule("goud_bij_cryptocrash", "crypto", "Goud houdt stand als crypto crasht",
         "Crypto en goud worden allebei 'digitaal en echt goud' genoemd, maar gedragen ze zich zo?",
         t_gold_when_crypto_crashes, partner="metals"),
]


def study(market, config, now: datetime) -> dict:
    """Alle vuistregels toetsen op de koersen van nu."""
    out = []
    for rule in RULES:
        try:
            res = rule.test(market, now, config)
        except (ValueError, KeyError, ZeroDivisionError, IndexError, AttributeError) as exc:   # een coach mag nooit de ronde stoppen
            res = {"verdict": "te weinig data", "text": f"kon niet toetsen ({type(exc).__name__})"}
        out.append({"id": rule.id, "desk": rule.desk, "partner": rule.partner, "title": rule.title,
                    "why": rule.why, **{k: v for k, v in res.items() if k in ("verdict", "text", "n", "avg", "base")}})
    return {"computed_at": now.isoformat(), "rules": out}


# ------------------------------------------------------------------ samenwerking vandaag

def today_warnings(market, now: datetime, coach: dict) -> list[dict]:
    """Gebeurt er vandaag iets waar een andere afdeling van moet weten? Alleen bij een getoetste regel."""
    by = {r["id"]: r for r in coach.get("rules", [])}
    out = []
    btc = Series(market, "BTC-EUR", now)
    if len(btc) >= 2:
        d, r = btc.dates[-1], btc.closes[-1] / btc.closes[-2] - 1
        rule = by.get("btc_crash_memes")
        if r <= -0.05 and rule and rule["verdict"] == "klopt":
            out.append({"day": d.isoformat(), "rule": rule["id"], "from": "crypto", "to": "meme",
                        "text": f"Crypto Lab aan Meme Arcade: bitcoin viel gisteren {_p(r)}. {rule['text']}"})
        rule = by.get("goud_bij_cryptocrash")
        if r <= -0.06 and rule and rule["verdict"] == "klopt":
            out.append({"day": d.isoformat(), "rule": rule["id"], "from": "crypto", "to": "metals",
                        "text": f"Crypto Lab aan De Kluis: bitcoin viel {_p(r)}. {rule['text']}"})
    w = Series(market, "IWDA.AS", now)
    if len(w) >= 2:
        d, r = w.dates[-1], w.closes[-1] / w.closes[-2] - 1
        rule = by.get("beurs_naar_crypto")
        if r <= -0.02 and rule and rule["verdict"] in ("klopt",):
            out.append({"day": d.isoformat(), "rule": rule["id"], "from": "stocks", "to": "crypto",
                        "text": f"Beurstoren aan Crypto Lab: de wereldindex viel {_p(r)}. {rule['text']}"})
    return out


def trade_tip(coach: dict | None, market, cls: str, symbol: str, now: datetime) -> str:
    """Een tip van de coach bij een aankoop, alleen als een getoetste regel nu van toepassing is."""
    if not coach:
        return ""
    by = {r["id"]: r for r in coach.get("rules", [])}
    if cls == "meme":
        ser = Series(market, symbol, now)
        week = ser.back(ser.dates[-1], 7) if len(ser) else None
        rule = by.get("pomp_dump")
        if week is not None and week >= 0.5 and rule and rule["verdict"] == "klopt":
            return f"{COACHES['meme']}: deze munt staat {_p(week)} in een week. {rule['text']}"
    return ""


# ------------------------------------------------------------------ dagelijks en wekelijks

def maybe_coach(market, config, now: datetime, academy: dict | None = None, log=print) -> dict | None:
    """Eén keer per dag de vuistregels toetsen en waarschuwingen tussen afdelingen doorgeven;
    één keer per week teamoverleg in het lessenboek."""
    from jplh.lessons import add
    old = market.get_state("coach")
    if old and old.get("computed_at", "")[:10] == now.date().isoformat():
        return old
    new = study(market, config, now)
    told = set((old or {}).get("told", []))
    for w in today_warnings(market, now, new):
        key = f"{w['rule']}@{w['day']}"
        if key in told:
            continue
        told.add(key)
        add(market, now, "samenwerking", w["text"], desk=w["from"], to=w["to"])
        log("samenwerking: " + w["text"])
    new["told"] = sorted(told)[-200:]
    new["team_at"] = (old or {}).get("team_at")
    if not new["team_at"] or now - datetime.fromisoformat(new["team_at"]) >= TEAM_EVERY:
        text = team_meeting(new, academy)
        if text:
            add(market, now, "teamoverleg", text)
            log("teamoverleg: " + text)
            new["team_at"] = now.isoformat()
    market.set_state("coach", new)
    return new


def cross_learning(academy: dict | None) -> list[str]:
    """Leren van elkaar: welke strategiefamilie doet het bij welke afdeling het best (uit de Academie)?"""
    if not academy:
        return []
    desks = ((academy.get("history") or {}).get("desks") or {})
    fam: dict[str, dict[str, float]] = {}
    for key, v in desks.items():
        cls, label = key.split("|", 1)
        name = label.split("(")[0]
        if name == "koop_en_houd" or v.get("edge") is None:
            continue
        best = fam.setdefault(name, {})
        best[cls] = max(best.get(cls, -1.0), v["edge"])
    out = []
    for name, per in sorted(fam.items()):
        if len(per) < 2:
            continue
        top = max(per, key=per.get)
        low = min(per, key=per.get)
        if per[top] - per[low] > 0.002:
            out.append(f"{name} werkt het best bij {DESK_NAMES.get(top, top)} ({_p(per[top], 2)} per week t.o.v. "
                       f"vasthouden) en het slechtst bij {DESK_NAMES.get(low, low)} ({_p(per[low], 2)})")
    return out


def team_meeting(coach: dict, academy: dict | None) -> str | None:
    rules = coach.get("rules", [])
    parts = []
    for cls in DESK_NAMES:
        mine = [r for r in rules if r["desk"] == cls and r["verdict"] in ("klopt", "klopt niet")]
        if mine:
            r = mine[0]
            word = "klopt" if r["verdict"] == "klopt" else "klopt NIET"
            parts.append(f"{COACHES[cls]}: '{r['title']}' {word}. {r.get('text', '')}")
    learn = cross_learning(academy)
    if learn:
        parts.append("Van elkaar leren: " + learn[0] + ".")
    if not parts:
        return None
    return "Teamoverleg. " + " ".join(parts)


def for_dashboard(coach: dict | None, market=None, now: datetime | None = None) -> dict | None:
    if not coach:
        return None
    per = {}
    for r in coach.get("rules", []):
        per.setdefault(r["desk"], []).append(r)
    for r in coach.get("rules", []):
        if r.get("partner"):
            per.setdefault(r["partner"], []).append({**r, "from": r["desk"]})
    return {"computed_at": coach.get("computed_at"), "coaches": COACHES, "desks": per,
            "team": [r for r in coach.get("rules", []) if r.get("partner")]}

"""NEXUS Alpha Research Engine: zoekt naar een voorsprong die de toetsen overleeft.

Opbouw per dataset (instrument × tijdschaal):

    | opwarmtijd | ontwikkeling (walk-forward)                  | HOLDOUT (afgesloten) |
                 | train → test | train → test | train → test |

- **Ontwikkeling**: per vak worden parameters gekozen op alleen de trainingsdata (beste Sharpe in
  een klein rooster) en getest op het volgende, ongeziene stuk. Alleen die testvakken samen tellen.
- **Holdout**: de laatste 20% van de data wordt tijdens het onderzoek niet bekeken. Alleen een
  bevroren kandidaat (vaste parameters, gekozen op de hele ontwikkelperiode) mag er één keer op
  getest worden. Elke blik wordt vastgelegd in een register (``holdout-ledger.jsonl``); wie
  dezelfde holdout vaker gebruikt, ziet dat terug in het oordeel.
- **Strategieën geven een gewicht** van 0 tot 1 (nooit hefboom, nooit short). Een gewicht tussen 0 en
  1 betekent een kleinere positie in plaats van alles of niets.
- **Uitvoering**: gewicht op de slotkoers van periode i, uitgevoerd op de opening van i+1, met
  fee (en minimumfee per order), halve spread en slippage. Kleine verschuivingen onder de
  ``band`` worden niet verhandeld, om kosten te sparen.
- **Elke poging telt**: het aantal geteste combinaties gaat mee in de gedefleerde Sharpe.

Families waarvoor de data ontbreekt (funding/open interest, gebeurtenissen zonder historie) worden
niet gesimuleerd maar als ``data_unavailable`` gerapporteerd, met de reden.
"""

from __future__ import annotations

import itertools
import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from jplh.config import CostModel
from jplh.models import Candle, Instrument
from jplh.strategies import rsi_series

from nexus import stats
from nexus.datasets import DEFENSIVE, Dataset, ResearchData, universe

SPREAD = {"stocks": 0.001, "crypto": 0.001, "meme": 0.003, "metals": 0.0005, "fx": 0.0002}


# ── Indicatoren (O(n), alleen verleden en heden) ───────────────────────────────────────────
def closes(c: list[Candle]) -> list[float]:
    return [x.close for x in c]


def rolling_mean(xs: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(xs)
    s = 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n:
            s -= xs[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def rolling_std(xs: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(xs)
    s = s2 = 0.0
    for i, x in enumerate(xs):
        s += x
        s2 += x * x
        if i >= n:
            s -= xs[i - n]
            s2 -= xs[i - n] ** 2
        if i >= n - 1 and n > 1:
            var = max(0.0, (s2 - s * s / n) / (n - 1))
            out[i] = math.sqrt(var)
    return out


def returns(xs: list[float]) -> list[float]:
    return [0.0] + [xs[i] / xs[i - 1] - 1 if xs[i - 1] > 0 else 0.0 for i in range(1, len(xs))]


def rolling_max(xs: list[float], n: int) -> list[float | None]:
    """Maximum van de ``n`` perioden VÓÓR i (exclusief i)."""
    from collections import deque
    out: list[float | None] = [None] * len(xs)
    dq: deque[int] = deque()
    for i in range(len(xs)):
        if i >= n:
            out[i] = xs[dq[0]]
        while dq and xs[dq[-1]] <= xs[i]:
            dq.pop()
        dq.append(i)
        while dq[0] <= i - n:
            dq.popleft()
    return out


def rolling_min(xs: list[float], n: int) -> list[float | None]:
    neg = rolling_max([-x for x in xs], n)
    return [None if v is None else -v for v in neg]


# ── Families: één instrument ────────────────────────────────────────────────────────────────
def f_tsmom_multi(c, ppy, lookbacks=(21, 63, 126, 252), scale=1):
    """Multi-timeframe momentum: gewicht = deel van de horizons met een positief rendement."""
    px = closes(c)
    lb = [int(x * scale) for x in lookbacks]
    m = max(lb)
    return [0.0 if i < m else sum(px[i] > px[i - k] for k in lb) / len(lb) for i in range(len(px))]


def f_vol_target(c, ppy, target=0.10, window=20, trend=0):
    """Volatiliteitsdoel: positie = doelvolatiliteit / gemeten volatiliteit (max 1).
    ``trend`` > 0: alleen als de koers boven zijn ``trend``-gemiddelde staat."""
    px = closes(c)
    sd = rolling_std(returns(px), window)
    ma = rolling_mean(px, trend) if trend else None
    out = []
    for i in range(len(px)):
        if sd[i] is None or sd[i] == 0 or (ma is not None and ma[i] is None):
            out.append(0.0)
            continue
        w = min(1.0, target / (sd[i] * math.sqrt(ppy)))
        if ma is not None and px[i] < ma[i]:
            w = 0.0
        out.append(w)
    return out


def f_trend_strength(c, ppy, fast=50, slow=200, floor=0.5):
    """Trend met graduele blootstelling: boven beide gemiddelden 1, boven alleen het lange ``floor``, anders 0."""
    px = closes(c)
    mf, ms = rolling_mean(px, fast), rolling_mean(px, slow)
    out = []
    for i in range(len(px)):
        if ms[i] is None:
            out.append(0.0)
        elif px[i] > ms[i] and mf[i] > ms[i]:
            out.append(1.0)
        elif px[i] > ms[i] or mf[i] > ms[i]:
            out.append(floor)
        else:
            out.append(0.0)
    return out


def f_volfilter_v2(c, ppy, fast=50, slow=200, window=20, lookback=252, quantile=0.8, min_hold=10):
    """Uitdager van volfilter v1: eruit pas boven het 80e percentiel van de beweeglijkheid (niet de
    mediaan), een band tussen in- en uitstap, en een minimale houdperiode tegen heen-en-weer."""
    px = closes(c)
    mf, ms = rolling_mean(px, fast), rolling_mean(px, slow)
    sd = rolling_std(returns(px), window)
    out, state, held = [], 0, 0
    for i in range(len(px)):
        if ms[i] is None or sd[i] is None or i < lookback + window:
            out.append(0.0)
            continue
        hist = sorted(x for x in sd[i - lookback:i] if x is not None)
        hi = hist[int(len(hist) * quantile) - 1] if hist else sd[i]
        lo = hist[int(len(hist) * (quantile - 0.2)) - 1] if hist else sd[i]
        trend_up = mf[i] > ms[i] * 1.01
        trend_dn = mf[i] < ms[i] * 0.99
        if state == 0 and trend_up and sd[i] <= lo:
            state, held = 1, 0
        elif state == 1 and held >= min_hold and (trend_dn or sd[i] > hi):
            state = 0
        held += 1
        out.append(float(state))
    return out


def f_breakout_confirm(c, ppy, entry=55, exit=20, confirm=2, vol_mult=1.0):
    """Uitbraak met bevestiging: ``confirm`` slotkoersen boven de top en volume boven gemiddeld."""
    px = closes(c)
    vol = [x.volume for x in c]
    top = rolling_max([x.high for x in c], entry)
    bot = rolling_min([x.low for x in c], exit)
    vavg = rolling_mean(vol, 20)
    out, state, streak = [], 0, 0
    for i in range(len(px)):
        if top[i] is None or bot[i] is None:
            out.append(0.0)
            continue
        streak = streak + 1 if px[i] > top[i] else 0
        vol_ok = vavg[i] is None or vavg[i] == 0 or vol[i] >= vol_mult * vavg[i]
        if state == 0 and streak >= confirm and vol_ok:
            state = 1
        elif state == 1 and px[i] < bot[i]:
            state = 0
        out.append(float(state))
    return out


def f_mr_oversold(c, ppy, rsi_n=2, low=10, exit_ma=5, trend=200):
    """Korte termijn oversold binnen een stijgende trend: RSI(2) laag en koers boven het 200-gemiddelde;
    uit zodra de koers boven het 5-gemiddelde sluit."""
    px = closes(c)
    rsi = rsi_series(px, rsi_n)
    mt, mx = rolling_mean(px, trend), rolling_mean(px, exit_ma)
    out, state = [], 0
    for i in range(len(px)):
        if mt[i] is None or rsi[i] is None or mx[i] is None:
            out.append(0.0)
            continue
        if state == 0 and rsi[i] < low and px[i] > mt[i]:
            state = 1
        elif state == 1 and (px[i] > mx[i] or px[i] < mt[i] * 0.95):
            state = 0
        out.append(float(state))
    return out


def f_mr_zscore(c, ppy, window=20, entry_z=2.0, exit_z=0.0, range_filter=0.0):
    """Volatiliteits-genormaliseerde afwijking: koop als de koers ``entry_z`` standaarddeviaties onder
    het gemiddelde staat. ``range_filter`` > 0: alleen als de trend vlak is (helling < filter per jaar)."""
    px = closes(c)
    ma, sd = rolling_mean(px, window), rolling_std(px, window)
    ma_long = rolling_mean(px, 100)
    out, state = [], 0
    for i in range(len(px)):
        if ma[i] is None or not sd[i]:
            out.append(0.0)
            continue
        z = (px[i] - ma[i]) / sd[i]
        flat = True
        if range_filter and ma_long[i] is not None and i >= 120 and ma_long[i - 20]:
            slope = (ma_long[i] / ma_long[i - 20] - 1) * ppy / 20
            flat = abs(slope) < range_filter
        if state == 0 and z < -entry_z and flat:
            state = 1
        elif state == 1 and z > exit_z:
            state = 0
        out.append(float(state))
    return out


def f_reversal_after_move(c, ppy, window=5, k=2.5, hold=5, vol_window=60):
    """Terugveren na een uitzonderlijke daling: ``window``-rendement lager dan −k × normale beweeglijkheid,
    dan ``hold`` perioden aanhouden."""
    px = closes(c)
    sd = rolling_std(returns(px), vol_window)
    out, left = [], 0
    for i in range(len(px)):
        if left > 0:
            left -= 1
            out.append(1.0)
            continue
        if i >= window and sd[i]:
            move = px[i] / px[i - window] - 1
            if move < -k * sd[i] * math.sqrt(window):
                left = hold - 1
                out.append(1.0)
                continue
        out.append(0.0)
    return out


def f_volume_shift(c, ppy, window=20, z=2.0, hold=10, trend=50):
    """Liquiditeitsverschuiving: volume ``z`` standaarddeviaties boven normaal op een stijgende dag
    binnen een opwaartse trend; ``hold`` perioden aanhouden."""
    px = closes(c)
    lv = [math.log1p(x.volume) for x in c]
    ma, sd = rolling_mean(lv, window), rolling_std(lv, window)
    mt = rolling_mean(px, trend)
    out, left = [], 0
    for i in range(len(px)):
        if left > 0:
            left -= 1
            out.append(1.0)
            continue
        if ma[i] is not None and sd[i] and mt[i] is not None and i >= 1:
            if (lv[i] - ma[i]) / sd[i] > z and px[i] > px[i - 1] and px[i] > mt[i]:
                left = hold - 1
                out.append(1.0)
                continue
        out.append(0.0)
    return out


# ── Families: portefeuille (meerdere instrumenten, zelfde kalender) ────────────────────────
def p_dual_momentum(panel, ppy, risky=(), safe=(), lookback=252, top=1, rebalance=21):
    """Relatieve sterkte + absolute momentum: de ``top`` sterkste risicobeleggingen als hun rendement
    boven dat van de veilige haven ligt, anders de veilige haven."""
    syms = list(panel)
    n = len(next(iter(panel.values())))
    px = {s: closes(panel[s]) for s in syms}
    out, cur = [], {}
    for i in range(n):
        if i < lookback:
            out.append({})
            continue
        if (i - lookback) % rebalance == 0:
            mom = {s: px[s][i] / px[s][i - lookback] - 1 for s in risky}
            hurdle = max((px[s][i] / px[s][i - lookback] - 1 for s in safe), default=0.0)
            best = [s for s in sorted(mom, key=lambda s: -mom[s])[:top] if mom[s] > hurdle]
            if best:
                cur = {s: 1.0 / top for s in best}
            else:
                cur = {safe[0]: 1.0} if safe else {}
        out.append(dict(cur))
    return out


def p_risk_parity(panel, ppy, assets=(), window=60, rebalance=21, trend=0):
    """Risicogebaseerde verdeling: gewicht omgekeerd evenredig met beweeglijkheid. ``trend`` > 0:
    een belegging onder zijn ``trend``-gemiddelde krijgt 0 (dat deel blijft cash)."""
    n = len(next(iter(panel.values())))
    sd = {s: rolling_std(returns(closes(panel[s])), window) for s in assets}
    ma = {s: rolling_mean(closes(panel[s]), trend) for s in assets} if trend else None
    out, cur = [], {}
    start = max(window, trend)
    for i in range(n):
        if i < start:
            out.append({})
            continue
        if (i - start) % rebalance == 0:
            inv = {s: 1 / sd[s][i] for s in assets if sd[s][i]}
            tot = sum(inv.values())
            cur = {s: v / tot for s, v in inv.items()} if tot else {}
            if ma is not None:
                cur = {s: w for s, w in cur.items() if closes(panel[s])[i] >= (ma[s][i] or 0)}
        out.append(dict(cur))
    return out


def p_regime_switch(panel, ppy, risky="", safe="", trend=200, vol_window=20, vol_cap=0.25):
    """Defensieve regimewissel: in het risicovolle deel als het boven zijn trend staat en de gemeten
    beweeglijkheid onder ``vol_cap`` (jaarbasis) ligt, anders in de veilige haven."""
    px = closes(panel[risky])
    ma = rolling_mean(px, trend)
    sd = rolling_std(returns(px), vol_window)
    out = []
    for i in range(len(px)):
        if ma[i] is None or sd[i] is None:
            out.append({})
        elif px[i] > ma[i] and sd[i] * math.sqrt(ppy) < vol_cap:
            out.append({risky: 1.0})
        else:
            out.append({safe: 1.0} if safe else {})
    return out


@dataclass(frozen=True)
class Family:
    key: str
    name: str
    group: str
    kind: str                                 # single | portfolio | unavailable
    asset_classes: tuple[str, ...]
    fn: Callable | None
    grid: dict
    hypothesis: str
    data_needs: str
    unavailable_reason: str = ""

    def combos(self) -> list[dict]:
        keys = list(self.grid)
        return [dict(zip(keys, v)) for v in itertools.product(*self.grid.values())] or [{}]


ALL = ("stocks", "crypto", "meme", "metals", "fx")
FAMILIES: list[Family] = [
    Family("tsmom_multi", "Multi-timeframe momentum", "trend_momentum", "single", ALL, f_tsmom_multi,
           {"scale": [0.5, 1, 2]},
           "Trends houden aan op meerdere horizons; een gedeeltelijke positie verkleint de kosten van een fout signaal.",
           "slotkoersen, 1 jaar opwarmtijd"),
    Family("vol_target", "Volatiliteits-gecorrigeerde blootstelling", "trend_momentum", "single", ALL, f_vol_target,
           {"target": [0.10, 0.15, 0.20], "window": [20, 60], "trend": [0, 200]},
           "Hypothese A: kleiner in onrust in plaats van eruit; houdt de drift vast en verlaagt dalingen.",
           "slotkoersen, 200 perioden opwarmtijd"),
    Family("trend_strength", "Trend met graduele blootstelling", "trend_momentum", "single", ALL, f_trend_strength,
           {"fast": [20, 50], "slow": [100, 200], "floor": [0.0, 0.5]},
           "Trendpersistentie: halve positie als het beeld gemengd is, in plaats van alles of niets.",
           "slotkoersen, 200 perioden opwarmtijd"),
    Family("volfilter_v2", "Volatiliteitsfilter v2 (uitdager)", "trend_momentum", "single", ALL, f_volfilter_v2,
           {"quantile": [0.7, 0.8, 0.9], "min_hold": [5, 10, 20]},
           "Hypothese B: alleen bij echt extreme onrust eruit, met houdtijd; minder trades dan v1.",
           "slotkoersen, ~275 perioden opwarmtijd"),
    Family("breakout_confirm", "Bevestigde uitbraak", "trend_momentum", "single", ALL, f_breakout_confirm,
           {"entry": [20, 55], "exit": [10, 20], "confirm": [1, 3]},
           "Een uitbraak die bevestigd wordt (meerdere slotkoersen, volume) is vaker echt.",
           "OHLCV, 55 perioden opwarmtijd"),
    Family("mr_oversold", "Korte oversold in een stijgende trend", "mean_reversion", "single", ALL, f_mr_oversold,
           {"low": [5, 10, 20], "exit_ma": [3, 5]},
           "Korte dalingen in een stijgende markt herstellen vaak; de trendfilter vermijdt vallende messen.",
           "slotkoersen, 200 perioden opwarmtijd"),
    Family("mr_zscore", "Genormaliseerde afwijking", "mean_reversion", "single", ALL, f_mr_zscore,
           {"window": [10, 20], "entry_z": [1.5, 2.0, 2.5], "range_filter": [0.0, 0.10]},
           "Afwijkingen van het gemiddelde in een zijwaartse markt keren terug.",
           "slotkoersen, 120 perioden opwarmtijd"),
    Family("reversal_after_move", "Herstel na een uitzonderlijke daling", "mean_reversion", "single", ALL,
           f_reversal_after_move, {"k": [2.0, 2.5, 3.0], "hold": [3, 5, 10]},
           "Na paniekverkopen (ver buiten de normale beweeglijkheid) volgt vaak een gedeeltelijk herstel.",
           "slotkoersen, 60 perioden opwarmtijd"),
    Family("volume_shift", "Liquiditeitsverschuiving", "crypto", "single", ("crypto", "meme"), f_volume_shift,
           {"z": [1.5, 2.0, 3.0], "hold": [5, 10]},
           "Een plotselinge volumestijging in een opwaartse trend kondigt instroom aan.",
           "OHLCV (Bitvavo-volume in euro)"),
    Family("dual_momentum", "Dubbel momentum met veilige haven", "portfolio", "portfolio", ("stocks",), p_dual_momentum,
           {"lookback": [126, 252], "top": [1, 2]},
           "Hypothese D: de sterkste belegging houden en bij zwakte naar geldmarkt in plaats van 0%.",
           "dagkoersen van alle Euronext/Xetra-ETF's en aandelen in euro"),
    Family("risk_parity", "Risicogebaseerde verdeling", "portfolio", "portfolio", ("stocks",), p_risk_parity,
           {"window": [60, 120], "trend": [0, 200]},
           "Spreiding naar risico (en optioneel trend) geeft een betere verhouding rendement/daling.",
           "dagkoersen van de spreidingsbeleggingen"),
    Family("regime_switch", "Defensieve regimewissel", "portfolio", "portfolio", ("stocks",), p_regime_switch,
           {"trend": [100, 200], "vol_cap": [0.18, 0.25, 0.35]},
           "Alleen in aandelen bij een rustige stijgende markt; anders obligaties of geldmarkt.",
           "dagkoersen IWDA, IEAG, XEON"),
    Family("crypto_rotation", "Crypto relatieve sterkte", "crypto", "portfolio", ("crypto",), p_dual_momentum,
           {"lookback": [30, 60, 90], "top": [1, 2]},
           "Geld stroomt naar de sterkste munten; rotatie met euro als veilige haven.",
           "dagkoersen van BTC/ETH/SOL/XRP in euro"),
    Family("funding_oi", "Funding en open interest", "crypto", "unavailable", ("crypto",), None, {},
           "Extreme funding of open interest gaat vaak vooraf aan een omslag.",
           "historische funding rates en open interest van een derivatenbeurs",
           "Bitvavo heeft alleen spot; derivatendata (bijv. van een perpetual-beurs) is niet gekoppeld."),
    Family("event_earnings", "Kwartaalcijfers", "event", "unavailable", ("stocks",), None, {},
           "Koersreactie na verrassende kwartaalcijfers (post-earnings drift).",
           "historische cijferdata met verwachtingen (consensus) en publicatietijd",
           "Vergt een betaalde bron met consensusverwachtingen (Polygon of FMP, nog niet gekozen)."),
    Family("event_macro", "Macro-publicaties en centrale banken", "event", "unavailable", ("stocks", "fx", "metals"),
           None, {}, "Rente- en inflatieverrassingen bewegen valuta, goud en aandelen voorspelbaar binnen uren.",
           "historische releasekalender met verwachting en uitkomst; intraday-koersen",
           "De nieuwspipeline verzamelt nu gebeurtenissen; een historische verwachtingenreeks ontbreekt nog."),
]


def family(key: str) -> Family:
    for f in FAMILIES:
        if f.key == key:
            return f
    raise KeyError(key)


# ── Simulatie met gewichten (één of meer instrumenten) ─────────────────────────────────────
@dataclass
class RoundTrip:
    symbol: str
    entry_ts: str
    exit_ts: str | None
    pnl_eur: float
    costs_eur: float
    bars: int


@dataclass
class WSim:
    returns: list[float]
    equity: list[float]
    weights: list[float]                     # som van de gewichten aan het eind van elke periode
    costs: float
    turnover: float
    orders: int
    trips: list[RoundTrip] = field(default_factory=list)


def simulate_weights(panel: dict[str, list[Candle]], weights: list[dict[str, float]],
                     costs: dict[str, tuple[CostModel, float]], start: int, end: int, capital: float = 1000.0,
                     band: float = 0.05) -> WSim:
    syms = list(panel)
    units = dict.fromkeys(syms, 0.0)
    cash, prev = capital, capital
    rets, eq, wts = [], [], []
    total_costs = turnover = 0.0
    orders = 0
    trips: list[RoundTrip] = []
    ep: dict[str, dict] = {}
    for i in range(start, end):
        want = weights[i - 1] if i >= 1 else {}
        opens = {s: panel[s][i].open for s in syms}
        value_open = cash + sum(units[s] * opens[s] for s in syms)
        # Eerst verkopen (maakt cash vrij), dan kopen.
        plan = []
        for s in syms:
            w = max(0.0, min(1.0, want.get(s, 0.0)))
            cur_w = units[s] * opens[s] / value_open if value_open > 0 else 0.0
            if abs(w - cur_w) <= band and not (w == 0 and units[s] > 0) and not (w > 0 and units[s] == 0):
                continue
            if w == cur_w:
                continue
            plan.append((w - cur_w, s, w))
        for delta, s, w in sorted(plan):
            cm, spread = costs[s]
            px = opens[s]
            target_units = w * value_open / px
            d_units = target_units - units[s]
            if abs(d_units) * px < 1e-9:
                continue
            notional = abs(d_units) * px
            fee = max(cm.min_fee_eur, notional * cm.fee_pct)
            frict = notional * (spread / 2 + cm.slippage_pct)
            if d_units > 0:
                room = cash / (1 + spread / 2 + cm.slippage_pct + cm.fee_pct) - cm.min_fee_eur * (cm.fee_pct == 0)
                if notional > room:
                    notional = max(0.0, room)
                    fee = max(cm.min_fee_eur, notional * cm.fee_pct)
                    notional = max(0.0, min(notional, (cash - fee) / (1 + spread / 2 + cm.slippage_pct)))
                    fee = max(cm.min_fee_eur, notional * cm.fee_pct)
                    frict = notional * (spread / 2 + cm.slippage_pct)
                if notional <= fee:
                    continue
                d_units = notional / px
                cash -= notional + fee + frict
            else:
                cash += notional - fee - frict
            if units[s] == 0 and d_units > 0:
                ep[s] = {"ts": panel[s][i].ts.isoformat(), "i": i, "flow": 0.0, "costs": 0.0}
            e = ep.setdefault(s, {"ts": panel[s][i].ts.isoformat(), "i": i, "flow": 0.0, "costs": 0.0})
            e["flow"] += (-notional if d_units > 0 else notional) - fee - frict
            e["costs"] += fee + frict
            units[s] = max(0.0, units[s] + d_units)
            if units[s] * px < 1e-6:
                units[s] = 0.0
                trips.append(RoundTrip(s, e["ts"], panel[s][i].ts.isoformat(), e["flow"], e["costs"], i - e["i"]))
                ep.pop(s, None)
            total_costs += fee + frict
            turnover += notional
            orders += 1
        value = cash + sum(units[s] * panel[s][i].close for s in syms)
        rets.append(value / prev - 1 if prev > 0 else 0.0)
        eq.append(value)
        wts.append(sum(units[s] * panel[s][i].close for s in syms) / value if value > 0 else 0.0)
        prev = value
    for s, e in ep.items():                  # open posities: tegen slotkoers, als open gemarkeerd
        val = units[s] * panel[s][end - 1].close
        trips.append(RoundTrip(s, e["ts"], None, e["flow"] + val, e["costs"], end - 1 - e["i"]))
    return WSim(rets, eq, wts, total_costs, turnover, orders, trips)


def wmetrics(sim: WSim, ppy: int, capital: float) -> dict:
    r = sim.returns
    n = len(r)
    if n < 2:
        return {"periods": n}
    eq, peak, mdd = 1.0, 1.0, 0.0
    for x in r:
        eq *= 1 + x
        peak = max(peak, eq)
        mdd = max(mdd, 1 - eq / peak)
    years = n / ppy
    ann = eq ** (1 / years) - 1 if eq > 0 else -1.0
    neg = [min(0.0, x) for x in r]
    dd = math.sqrt(sum(x * x for x in neg) / n)
    closed = [t for t in sim.trips if t.exit_ts is not None]
    gw = sum(t.pnl_eur for t in closed if t.pnl_eur > 0)
    gl = -sum(t.pnl_eur for t in closed if t.pnl_eur <= 0)
    expo = stats.mean(sim.weights)
    ev = stats.expected_value([t.pnl_eur for t in closed])
    return {"periods": n, "years": years, "net_return": eq - 1, "annual_return": ann, "max_drawdown": mdd,
            "volatility": stats.stdev(r) * math.sqrt(ppy), "sharpe": stats.sharpe(r, ppy),
            "sortino": stats.mean(r) / dd * math.sqrt(ppy) if dd > 0 else None,
            "calmar": ann / mdd if mdd > 0 else None,
            "trades": len(closed), "orders": sim.orders, "win_rate": ev.get("win_rate"),
            "profit_factor": gw / gl if gl > 0 else None, "expected_value_eur": ev.get("expected_value"),
            "avg_win_eur": ev.get("avg_win"), "avg_loss_eur": ev.get("avg_loss"),
            "largest_loss_eur": ev.get("largest_loss"),
            "exposure": expo, "capital_efficiency": ann / expo if expo > 0 else None,
            "costs_eur": sim.costs, "costs_pct": sim.costs / capital,
            "turnover_per_year": sim.turnover / capital / years if years > 0 else None}


# ── Onderzoeksopzet ─────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Split:
    warm: int
    dev_end: int                    # holdout begint hier
    n: int
    folds: tuple[tuple[int, int], ...]


def make_split(n: int, warm: int, holdout: float = 0.2, folds: int = 4, test_share: float = 0.5) -> Split | None:
    dev_end = n - max(int(n * holdout), 60)
    dev = dev_end - warm
    if dev < 300:
        return None
    test_start = warm + int(dev * (1 - test_share))
    size = (dev_end - test_start) // folds
    if size < 40:
        return None
    fs = tuple((test_start + k * size, test_start + (k + 1) * size if k < folds - 1 else dev_end) for k in range(folds))
    return Split(warm, dev_end, n, fs)


WARMUP = 260
MIN_BARS = 900


def _single_weights(fam: Family, candles: list[Candle], ppy: int, params: dict, sym: str) -> list[dict]:
    return [{sym: w} for w in fam.fn(candles, ppy, **params)]


def walk_forward(weights_for: Callable[[dict], list[dict]], combos: list[dict], panel: dict, costs: dict, sp: Split,
                 ppy: int, capital: float, bench_w: list[dict]) -> dict:
    """Kiest per vak de beste instelling op de trainingsdata en test die op het volgende vak."""
    cache = {json.dumps(p, sort_keys=True): weights_for(p) for p in combos}
    oos, bench, chosen = [], [], []
    trips: list[RoundTrip] = []
    costs_total = 0.0
    weights_seq: list[float] = []
    orders = 0
    for a, b in sp.folds:
        best, best_sh = None, -math.inf
        for p in combos:
            w = cache[json.dumps(p, sort_keys=True)]
            sh = stats.sharpe(simulate_weights(panel, w, costs, sp.warm, a, capital).returns, ppy)
            if sh > best_sh:
                best, best_sh = p, sh
        w = cache[json.dumps(best, sort_keys=True)]
        s = simulate_weights(panel, w, costs, a, b, capital)
        bb = simulate_weights(panel, bench_w, costs, a, b, capital)
        oos += s.returns
        bench += bb.returns
        trips += s.trips
        costs_total += s.costs
        weights_seq += s.weights
        orders += s.orders
        chosen.append({"test_start": a, "test_end": b, "params": best, "train_sharpe": best_sh})
    sim = WSim(oos, [], weights_seq, costs_total, 0.0, orders, trips)
    return {"returns": oos, "bench_returns": bench, "sim": sim, "folds": chosen,
            "metrics": wmetrics(sim, ppy, capital),
            "bench_metrics": wmetrics(WSim(bench, [], [1.0] * len(bench), 0.0, 0.0, 0), ppy, capital)}


def risk_matched(strategy: list[float], bench: list[float]) -> list[float]:
    """Koop-en-houd geschaald naar dezelfde beweeglijkheid als de strategie (rest in cash, 0%)."""
    sb, ss = stats.stdev(bench), stats.stdev(strategy)
    k = min(1.0, ss / sb) if sb > 0 else 0.0
    return [k * r for r in bench]


@dataclass
class Candidate:
    family: str
    symbols: tuple[str, ...]
    interval: str
    params: dict                       # bevroren: gekozen op de hele ontwikkelperiode
    dev: dict
    status: str
    reasons: list[str]
    holdout: dict | None = None


# Poorten voor de ontwikkelperiode (vóór de holdout).
DEV_GATES = {
    "min_trades": 8,
    "min_p_sharpe_better": 0.80,
    "min_neighbour_share": 0.60,
    "min_dsr": 0.50,
}


def evaluate_dataset(fam: Family, panel: dict[str, list[Candle]], anchor: str, costs: dict, ppy: int, interval: str,
                     capital: float, trials_total: int, extra_bench: dict[str, list[dict]] | None = None) -> dict:
    n = len(panel[anchor])
    sp = make_split(n, WARMUP)
    if sp is None:
        return {"family": fam.key, "symbols": list(panel), "interval": interval, "status": "insufficient_history",
                "reasons": [f"{n} perioden; minstens ~{MIN_BARS} nodig voor ontwikkeling + holdout"]}
    syms = list(panel)
    if fam.kind == "single":
        def weights_for(p):
            return _single_weights(fam, panel[anchor], ppy, p, anchor)
    else:
        def weights_for(p):
            return fam.fn(panel, ppy, **{**fam_static(fam, syms), **p})
    combos = fam.combos()
    bench_w = [{anchor: 1.0}] * n
    wf = walk_forward(weights_for, combos, panel, costs, sp, ppy, capital, bench_w)
    m, bm = wf["metrics"], wf["bench_metrics"]
    rm = risk_matched(wf["returns"], wf["bench_returns"])
    unc = stats.excess_uncertainty(wf["returns"], wf["bench_returns"], ppy)
    unc_rm = stats.excess_uncertainty(wf["returns"], rm, ppy)

    # Bevroren instelling: beste Sharpe over de hele ontwikkelperiode (zonder holdout).
    dev_rows = []
    for p in combos:
        s = simulate_weights(panel, weights_for(p), costs, sp.warm, sp.dev_end, capital)
        dev_rows.append((stats.sharpe(s.returns, ppy), p, s))
    dev_rows.sort(key=lambda r: -r[0])
    frozen = dev_rows[0][1]
    bench_dev = stats.sharpe(simulate_weights(panel, bench_w, costs, sp.warm, sp.dev_end, capital).returns, ppy)
    neighbour_share = sum(1 for sh, _, _ in dev_rows if sh > bench_dev) / len(dev_rows)
    dsr = stats.deflated_sharpe(wf["returns"], trials_total, [sh / math.sqrt(ppy) for sh, _, _ in dev_rows])

    # Kosten verdubbeld: blijft de voorsprong?
    cost2 = {s: (CostModel(c.fee_pct * 2, c.slippage_pct * 2, c.min_fee_eur * 2), sp_ * 2) for s, (c, sp_) in costs.items()}
    wf2 = walk_forward(weights_for, [frozen], panel, cost2, sp, ppy, capital, bench_w)

    reasons = []
    if m["sharpe"] <= bm["sharpe"]:
        reasons.append(f"walk-forward Sharpe {m['sharpe']:.2f} niet boven koop-en-houd {bm['sharpe']:.2f}")
    if unc.get("available") and unc["p_sharpe_better"] < DEV_GATES["min_p_sharpe_better"]:
        reasons.append(f"kans op betere Sharpe {unc['p_sharpe_better']:.0%} < {DEV_GATES['min_p_sharpe_better']:.0%}")
    activity = max(m["trades"], m["orders"] // 2)          # gedeeltelijke posities sluiten zelden helemaal af
    if activity < DEV_GATES["min_trades"] and fam.kind == "single":
        reasons.append(f"{m['trades']} afgeronde trades en {m['orders']} orders: te weinig om iets te zeggen")
    if neighbour_share < DEV_GATES["min_neighbour_share"]:
        reasons.append(f"maar {neighbour_share:.0%} van de instellingen beter dan koop-en-houd (gevoelig)")
    if dsr is not None and dsr < DEV_GATES["min_dsr"]:
        reasons.append(f"gedefleerde Sharpe {dsr:.0%} (na {trials_total} pogingen)")
    if wf2["metrics"]["sharpe"] <= wf2["bench_metrics"]["sharpe"]:
        reasons.append("bij dubbele kosten geen voorsprong meer")
    if m["trades"] >= 5 and m.get("expected_value_eur") is not None and m["expected_value_eur"] <= 0:
        reasons.append(f"verwachtingswaarde per trade €{m['expected_value_eur']:.2f} ≤ 0 na kosten")
    risk_better = (m["max_drawdown"] < bm["max_drawdown"] and unc_rm.get("available")
                   and unc_rm["excess_annual"] > 0)
    return {
        "family": fam.key, "family_name": fam.name, "group": fam.group, "symbols": syms, "anchor": anchor,
        "interval": interval, "split": {"warmup_end": panel[anchor][sp.warm].ts.isoformat(),
                                        "test_start": panel[anchor][sp.folds[0][0]].ts.isoformat(),
                                        "holdout_start": panel[anchor][sp.dev_end].ts.isoformat(),
                                        "end": panel[anchor][n - 1].ts.isoformat()},
        "walk_forward": m, "benchmark": bm, "risk_matched_excess": unc_rm, "uncertainty": unc,
        "folds": wf["folds"], "frozen_params": frozen, "neighbour_share": neighbour_share,
        "deflated_sharpe": dsr, "double_costs": {"sharpe": wf2["metrics"]["sharpe"], "bench": wf2["bench_metrics"]["sharpe"]},
        "risk_profile_better": bool(risk_better),
        "status": "candidate" if not reasons else "rejected", "reasons": reasons, "_split": sp,
        "_wf_returns": wf["returns"],
    }


def fam_static(fam: Family, syms: list[str]) -> dict:
    risky = tuple(s for s in syms if s not in DEFENSIVE)
    safe = tuple(s for s in ("XEON.DE", "IEAG.AS") if s in syms)
    if fam.key in ("dual_momentum", "crypto_rotation"):
        return {"risky": risky, "safe": safe}
    if fam.key == "risk_parity":
        return {"assets": tuple(syms)}
    if fam.key == "regime_switch":
        return {"risky": "IWDA.AS", "safe": "IEAG.AS" if "IEAG.AS" in syms else (safe[0] if safe else "")}
    return {}


def align(datasets: list[Dataset]) -> dict[str, list[Candle]]:
    """Alleen tijdstempels die alle instrumenten hebben (op datum voor dagkoersen)."""
    def key(c, interval):
        return c.ts.date() if interval == "1d" else c.ts
    keys = None
    for d in datasets:
        k = {key(c, d.interval) for c in d.candles}
        keys = k if keys is None else keys & k
    out = {}
    for d in datasets:
        out[d.inst.symbol] = [c for c in d.candles if key(c, d.interval) in keys]
    return out


# ── Holdout-register ───────────────────────────────────────────────────────────────────────
class HoldoutLedger:
    """Alleen toevoegen. Elke regel: welke kandidaat, welke dataset, welke holdout-periode, wanneer."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(x) for x in self.path.read_text().splitlines() if x.strip()]

    def uses(self, dataset_key: str, holdout_start: str) -> int:
        return sum(1 for e in self.entries() if e["dataset"] == dataset_key and e["holdout_start"] == holdout_start)

    def record(self, dataset_key: str, holdout_start: str, candidate: str, params: dict, run: str) -> int:
        prior = self.uses(dataset_key, holdout_start)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps({"dataset": dataset_key, "holdout_start": holdout_start, "candidate": candidate,
                                "params": params, "run": run, "at": datetime.now(tz=UTC).isoformat(),
                                "prior_uses": prior}, sort_keys=True) + "\n")
        return prior + 1


def evaluate_holdout(res: dict, fam: Family, panel: dict, costs: dict, ppy: int, capital: float,
                     ledger: HoldoutLedger | None, run: str) -> dict:
    sp: Split = res["_split"]
    syms = res["symbols"]
    anchor = res["anchor"]
    p = res["frozen_params"]
    if fam.kind == "single":
        w = _single_weights(fam, panel[anchor], ppy, p, anchor)
    else:
        w = fam.fn(panel, ppy, **{**fam_static(fam, syms), **p})
    s = simulate_weights(panel, w, costs, sp.dev_end, sp.n, capital)
    b = simulate_weights(panel, [{anchor: 1.0}] * sp.n, costs, sp.dev_end, sp.n, capital)
    m, bm = wmetrics(s, ppy, capital), wmetrics(b, ppy, capital)
    uses = None
    if ledger is not None:
        uses = ledger.record(f"{'+'.join(syms)}@{res['interval']}", res["split"]["holdout_start"],
                             f"{fam.key}", p, run)
    unc = stats.excess_uncertainty(s.returns, b.returns, ppy)
    rm = stats.excess_uncertainty(s.returns, risk_matched(s.returns, b.returns), ppy)
    passed = m["sharpe"] > bm["sharpe"] and (unc.get("p_sharpe_better") or 0) >= 0.5
    return {"metrics": m, "benchmark": bm, "uncertainty": unc, "risk_matched_excess": rm, "holdout_uses": uses,
            "passed": passed,
            "note": ("eerste keer bekeken" if uses == 1 else
                     f"deze holdout is {uses}× gebruikt: niet langer onafhankelijk" if uses else "")}


def research_costs(data: ResearchData, inst: Instrument) -> tuple[CostModel, float]:
    return data.config.costs[inst.asset_class.value], SPREAD[inst.asset_class.value]


def discover(data: ResearchData, interval: str = "1d", symbols: list[str] | None = None, capital: float = 1000.0,
             families: list[str] | None = None, ledger: HoldoutLedger | None = None, holdout: bool = True,
             run: str | None = None) -> dict:
    """Draait alle families op alle geschikte datasets. Kandidaten die de ontwikkelpoorten halen,
    worden bevroren en één keer op de holdout getest."""
    run = run or datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    insts = {i.symbol: i for i in universe(data.config)}
    pick = [insts[s] for s in symbols] if symbols else list(insts.values())
    sets = {i.symbol: data.load(i, interval) for i in pick}
    fams = [f for f in FAMILIES if families is None or f.key in families]

    jobs = []           # (family, panel, anchor, costs, ppy)
    skipped = []
    for fam in fams:
        if fam.kind == "unavailable":
            skipped.append({"family": fam.key, "family_name": fam.name, "group": fam.group,
                            "status": "data_unavailable", "reasons": [fam.unavailable_reason],
                            "data_needs": fam.data_needs, "hypothesis": fam.hypothesis})
            continue
        if fam.kind == "single":
            for sym, ds in sets.items():
                if ds.inst.asset_class.value not in fam.asset_classes or sym in DEFENSIVE:
                    continue
                cm = research_costs(data, ds.inst)
                jobs.append((fam, {sym: ds.candles}, sym, {sym: cm}, ds.ppy, ds.notes))
        else:
            cls = fam.asset_classes[0]
            group = [ds for ds in sets.values() if ds.inst.asset_class.value == cls and ds.candles
                     and (cls != "crypto" or ds.inst.symbol in ("BTC-EUR", "ETH-EUR", "SOL-EUR", "XRP-EUR"))]
            if cls == "stocks":
                group = [ds for ds in group if ds.currency == "EUR"]
            if fam.key == "regime_switch":
                group = [ds for ds in group if ds.inst.symbol in ("IWDA.AS", "IEAG.AS", "XEON.DE")]
            if len(group) < 2 or (cls == "stocks" and "IWDA.AS" not in {d.inst.symbol for d in group}):
                skipped.append({"family": fam.key, "status": "insufficient_history", "reasons": ["te weinig instrumenten"]})
                continue
            panel = align(group)
            anchor = "IWDA.AS" if cls == "stocks" else "BTC-EUR"
            costs = {d.inst.symbol: research_costs(data, d.inst) for d in group}
            jobs.append((fam, panel, anchor, costs, group[0].ppy, ()))

    trials_total = sum(len(j[0].combos()) for j in jobs)
    results = []
    for fam, panel, anchor, costs, ppy, notes in jobs:
        res = evaluate_dataset(fam, panel, anchor, costs, ppy, interval, capital, trials_total)
        res["data_notes"] = list(notes)
        res["hypothesis"] = fam.hypothesis
        if res["status"] == "candidate" and holdout:
            res["holdout"] = evaluate_holdout(res, fam, panel, costs, ppy, capital, ledger, run)
            res["status"] = "holdout_passed" if res["holdout"]["passed"] else "holdout_failed"
            if not res["holdout"]["passed"]:
                res["reasons"].append("holdout: niet beter voor risico dan koop-en-houd")
        res.pop("_split", None)
        res.pop("_wf_returns", None)
        results.append(res)
    summary = {
        "datasets": len({(tuple(r["symbols"]), r["interval"]) for r in results}),
        "combinations": len(results), "trials_total": trials_total,
        "candidates": sum(1 for r in results if r["status"] in ("candidate", "holdout_passed", "holdout_failed")),
        "holdout_passed": sum(1 for r in results if r["status"] == "holdout_passed"),
        "insufficient_history": sum(1 for r in results if r["status"] == "insufficient_history"),
        "better_risk_profile": sum(1 for r in results if r.get("risk_profile_better")),
    }
    return {"run": run, "interval": interval, "capital_eur": capital, "created_at": datetime.now(tz=UTC).isoformat(),
            "gates": DEV_GATES, "summary": summary, "results": results, "unavailable": skipped,
            "method": __doc__.strip().split("\n\n")[0]}


def markdown(rep: dict) -> str:
    def pc(x):
        return "n.v.t." if x is None else f"{x * 100:+.1f}%".replace(".", ",")

    def f2(x):
        return "n.v.t." if x is None else f"{x:.2f}".replace(".", ",")

    s = rep["summary"]
    lines = [f"# Alpha Research Engine: run {rep['run']} ({rep['interval']})", "",
             f"{s['combinations']} combinaties van familie × dataset, samen {s['trials_total']} geteste instellingen. "
             f"Kandidaten na de ontwikkelpoorten: {s['candidates']}. Geslaagd op de afgesloten holdout: {s['holdout_passed']}. "
             f"Te weinig geschiedenis: {s['insufficient_history']}.", "",
             "Walk-forward = alleen de testvakken, met parameters gekozen op eerdere data. Maatlat = koop-en-houd "
             "van het ankerinstrument over dezelfde vakken.", "",
             "| Familie | Data | WF rendement | Maatlat | WF Sharpe | Maatlat | Max. daling | Maatlat | Trades | EV/trade | Status |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    order = {"holdout_passed": 0, "holdout_failed": 1, "candidate": 2, "rejected": 3, "insufficient_history": 4}
    for r in sorted(rep["results"], key=lambda r: (order.get(r["status"], 9), -(r.get("walk_forward", {}).get("sharpe") or -9))):
        if r["status"] == "insufficient_history":
            continue
        m, b = r["walk_forward"], r["benchmark"]
        lines.append(f"| {r['family_name']} | {'+'.join(r['symbols']) if len(r['symbols']) < 4 else r['anchor'] + ' +' + str(len(r['symbols']) - 1)} "
                     f"| {pc(m['net_return'])} | {pc(b['net_return'])} | {f2(m['sharpe'])} | {f2(b['sharpe'])} "
                     f"| {pc(m['max_drawdown'])} | {pc(b['max_drawdown'])} | {m['trades']} "
                     f"| {'€' + f2(m['expected_value_eur']) if m.get('expected_value_eur') is not None else 'n.v.t.'} | {r['status']} |")
    cands = [r for r in rep["results"] if r.get("holdout")]
    if cands:
        lines += ["", "## Holdout (één keer bekeken, bevroren instelling)", "",
                  "| Familie | Data | Instelling | Rendement | Maatlat | Sharpe | Maatlat | Kans beter | Gebruik |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for r in cands:
            h = r["holdout"]
            lines.append(f"| {r['family_name']} | {r['anchor']} | `{r['frozen_params']}` | {pc(h['metrics']['net_return'])} "
                         f"| {pc(h['benchmark']['net_return'])} | {f2(h['metrics']['sharpe'])} | {f2(h['benchmark']['sharpe'])} "
                         f"| {pc(h['uncertainty'].get('p_sharpe_better'))} | {h['holdout_uses'] or '-'}× |")
    better_risk = [r for r in rep["results"] if r.get("risk_profile_better")]
    if better_risk:
        lines += ["", "## Beter risicoprofiel (kleinere daling én beter dan risico-gematcht koop-en-houd)", ""]
        for r in better_risk:
            u = r["risk_matched_excess"]
            lines.append(f"- {r['family_name']} op {r['anchor']}: max. daling {pc(r['walk_forward']['max_drawdown'])} tegen "
                         f"{pc(r['benchmark']['max_drawdown'])}; t.o.v. risico-gematcht {pc(u['excess_annual'])} per jaar "
                         f"(90%: {pc(u['excess_annual_ci90'][0])} tot {pc(u['excess_annual_ci90'][1])}).")
    if rep["unavailable"]:
        lines += ["", "## Niet getest: data ontbreekt", ""]
        for u in rep["unavailable"]:
            lines.append(f"- {u.get('family_name', u['family'])}: {'; '.join(u['reasons'])}")
    short = [r for r in rep["results"] if r["status"] == "insufficient_history"]
    if short:
        lines += ["", f"## Te weinig geschiedenis ({len(short)})", ""]
        seen = set()
        for r in short:
            k = ("+".join(r["symbols"]), r["reasons"][0])
            if k not in seen:
                seen.add(k)
                lines.append(f"- {k[0]}: {k[1]}")
    lines += ["", "## Poorten in de ontwikkelperiode", "",
              "Walk-forward Sharpe boven koop-en-houd; kans op een betere Sharpe (bootstrap) minstens "
              f"{DEV_GATES['min_p_sharpe_better']:.0%}; minstens {DEV_GATES['min_trades']} trades; minstens "
              f"{DEV_GATES['min_neighbour_share']:.0%} van de instellingen beter dan koop-en-houd; gedefleerde Sharpe "
              f"minstens {DEV_GATES['min_dsr']:.0%}; voorsprong blijft bij dubbele kosten; positieve verwachting per trade."]
    return "\n".join(lines) + "\n"

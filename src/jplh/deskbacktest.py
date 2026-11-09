"""Afdelingen-backtest: speelt de hele afdeling na op dagkoersen, inclusief de weekkeuze.

Hiermee testen we verbeteringen aan de afdeling zelf (niet aan één strategie) eerlijk tegen
de huidige versie, op precies dezelfde koersen en met dezelfde kosten:

- ``risk_sizing``  : geld verdelen naar beweeglijkheid (wilde munten krijgen minder) i.p.v. gelijk;
- ``switch_margin``: een nieuwe strategie moet zoveel Sharpe beter zijn dan de huidige om hem te
                     vervangen (0 = altijd wisselen, zoals nu);
- ``regime``       : alleen kopen als de "marktleider" (BTC voor crypto/memes, IWDA voor aandelen)
                     boven zijn 200-dagengemiddelde staat;
- ``trail``        : meebewegende stop: verkopen als de koers ``trail`` x de dagelijkse
                     beweeglijkheid x 10 onder de top sinds aankoop zakt;
- ``vote``         : de beste ``vote`` strategieën stemmen; in de markt bij een meerderheid;
- ``handicap``     : hoeveel Sharpe een strategie moet inleveren t.o.v. vasthouden (nu 0,1).

Zonder in de toekomst te kijken: de keuze op dag d gebruikt alleen koersen t/m dag d, en de
order wordt uitgevoerd op de opening van dag d+1.

Snelle benadering van de weekkeuze: elke strategie wordt één keer over de hele geschiedenis
gedraaid (een strategie hangt alleen af van koersen t/m vandaag), en de Sharpe op het venster
van 500 dagen komt uit lopende sommen. Dat scheelt alleen de eenmalige instapkosten aan het
begin van het venster.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from jplh.backtest import PERIODS_PER_YEAR, metrics, simulate, unit_prices
from jplh.config import HoldingConfig
from jplh.models import Candle, Instrument
from jplh.strategies import BuyHold, Strategy
from jplh.desks import REGIME_BAND

WINDOW = 500
RESELECT_DAYS = 7
VOL_DAYS = 60
LEADER = {"crypto": "BTC-EUR", "meme": "BTC-EUR", "stocks": "IWDA.AS"}


@dataclass(frozen=True)
class Variant:
    name: str
    risk_sizing: bool = False
    switch_margin: float = 0.0
    regime: bool = False
    trail: float = 0.0
    vote: int = 1
    hold_only: bool = False
    handicap: float = 0.1     # Sharpe die een strategie moet inleveren t.o.v. vasthouden
    regime_exit: bool = False # bij slecht marktweer ook verkopen (niet alleen niet kopen)
    rotate: int = 0           # alleen de ``rotate`` sterkste instrumenten (momentum) houden; 0 = uit
    rotate_days: int = 126    # momentum over zoveel dagen (~6 maanden)
    regime_band: float = 0.0  # marge rond het 200-dagengemiddelde: pas wisselen als de leider er zoveel voorbij is


VARIANTS = [
    Variant("oude versie"),
    Variant("vasthouden (maatlat)", hold_only=True),
    Variant("1 grootte op risico", risk_sizing=True),
    Variant("2 minder wisselen", switch_margin=0.3),
    Variant("3 marktweer-filter", regime=True),
    Variant("4 meebewegende stop", trail=3.0),
    Variant("5 stemmen (top 3)", vote=3),
    Variant("6 strenge drempel", handicap=0.5),
    Variant("2+3", switch_margin=0.3, regime=True),
    Variant("2+6", switch_margin=0.3, handicap=0.5),
    Variant("2+3+6", switch_margin=0.3, regime=True, handicap=0.5),
    Variant("1+2+3+6", risk_sizing=True, switch_margin=0.3, regime=True, handicap=0.5),
    Variant("7 vasthouden + marktweer", hold_only=True, regime=True, regime_exit=True),
    Variant("8 rotatie top 2 (6 mnd)", rotate=2),
    Variant("8b rotatie top 2 + marktweer", rotate=2, regime=True, regime_exit=True),
    Variant("8c rotatie top 1 (3 mnd)", rotate=1, rotate_days=63),
    Variant("9 vasthouden + marktweer, marge 3%", hold_only=True, regime=True, regime_exit=True, regime_band=0.03),
    Variant("9b vasthouden + marktweer, marge 5%", hold_only=True, regime=True, regime_exit=True, regime_band=0.05),
    Variant("9c 2+3 met marge 3%", switch_margin=0.3, regime=True, regime_band=0.03),
    Variant("alles", risk_sizing=True, switch_margin=0.3, regime=True, trail=3.0, vote=3, handicap=0.5),
]


@dataclass
class _Series:
    inst: Instrument
    candles: list[Candle]
    index: dict                       # datum -> positie in candles
    targets: dict[str, list[int]]
    csum: dict[str, list[float]]      # lopende som van rendementen per strategie
    csq: dict[str, list[float]]
    vol: list[float]                  # dagelijkse beweeglijkheid (60 dagen)


def _prepare(inst: Instrument, candles: list[Candle], candidates: list[Strategy], cost, ppy) -> _Series:
    candles = unit_prices(candles, inst)
    targets, csum, csq = {}, {}, {}
    for s in candidates:
        run = simulate(s, candles, cost, start=0)
        targets[s.label] = s.targets(candles)
        a, b, acc, acc2 = [0.0], [0.0], 0.0, 0.0
        for r in run.returns:
            acc += r
            acc2 += r * r
            a.append(acc)
            b.append(acc2)
        csum[s.label], csq[s.label] = a, b
    rets = [0.0] + [math.log(y.close / x.close) for x, y in zip(candles, candles[1:])]
    vol = []
    for i in range(len(candles)):
        w = rets[max(1, i - VOL_DAYS + 1):i + 1]
        m = sum(w) / len(w) if w else 0.0
        vol.append(math.sqrt(sum((x - m) ** 2 for x in w) / max(len(w) - 1, 1)) if len(w) > 5 else 0.0)
    return _Series(inst, candles, {c.ts.date(): i for i, c in enumerate(candles)}, targets, csum, csq, vol)


def _sharpe(s: _Series, label: str, i: int, ppy: int) -> float:
    lo = max(0, i + 1 - WINDOW)
    n = i + 1 - lo
    if n < 30:
        return -math.inf
    tot = s.csum[label][i + 1] - s.csum[label][lo]
    sq = s.csq[label][i + 1] - s.csq[label][lo]
    mean = tot / n
    var = (sq - n * mean * mean) / (n - 1)
    return mean / math.sqrt(var) * math.sqrt(ppy) if var > 1e-18 else 0.0


@dataclass
class DeskResult:
    variant: str
    desk: str
    equity: list[float] = field(default_factory=list)
    dates: list = field(default_factory=list)
    trades: int = 0
    fees: float = 0.0
    switches: int = 0


def run_desk(cls: str, series: list[_Series], leader: _Series | None, config: HoldingConfig, variant: Variant,
             start_date, capital: float) -> DeskResult:
    cost = config.costs[cls]
    ppy = PERIODS_PER_YEAR[("1d", cls)]
    labels = list(series[0].targets) if series else []
    dates = sorted({d for s in series for d in s.index if d >= start_date})
    cash, qty = capital, {s.inst.symbol: 0.0 for s in series}
    peak_since = {s.inst.symbol: 0.0 for s in series}
    chosen: dict[str, list[str]] = {}
    pending: dict[str, int] = {}
    res = DeskResult(variant.name, cls)
    res.dates = dates
    last_pick = None
    bull_state: bool | None = None
    rotation: set = set()
    max_pos = max(config.risk.max_position_pct, 1 / max(len(series), 1),
                  1 / variant.rotate if variant.rotate else 0)

    def last_idx(s: _Series, d) -> int | None:
        i = s.index.get(d)
        if i is not None:
            return i
        # laatste bekende dag vóór d
        prev = [k for k in (s.index.get(d.fromordinal(d.toordinal() - j)) for j in range(1, 6)) if k is not None]
        return prev[0] if prev else None

    def known_idx(s: _Series, d) -> int | None:
        """Laatste dag waarvan de slotkoers bij de opening van ``d`` al bekend is (dus vóór d)."""
        j = last_idx(s, d)
        if j is not None and s.candles[j].ts.date() >= d:
            j -= 1
        return j if j is not None and j >= 0 else None

    for d in dates:
        # 1. Orders van gisteren uitvoeren op de opening van vandaag.
        idxs = {s.inst.symbol: s.index.get(d) for s in series}
        equity_open = cash + sum(qty[s.inst.symbol] * s.candles[(last_idx(s, d) or 0)].open for s in series)
        for s in series:
            sym, i = s.inst.symbol, idxs[s.inst.symbol]
            if i is None or sym not in pending:
                continue
            want = pending.pop(sym)
            px = s.candles[i].open
            if want and qty[sym] == 0:
                if variant.risk_sizing:
                    inv = {}
                    for x in series:
                        j = known_idx(x, d)
                        if j is not None and x.vol[j] > 0:
                            inv[x.inst.symbol] = 1 / x.vol[j]
                    w = inv.get(sym, 0.0) / sum(inv.values()) if sym in inv else 1 / len(series)
                elif variant.rotate:
                    w = 1 / variant.rotate
                else:
                    w = 1 / len(series)
                size = min(equity_open * min(w, max_pos), cash)
                fee = max(cost.min_fee_eur, size * cost.fee_pct)
                if size - fee < config.risk.min_order_eur:
                    continue
                qty[sym] = (size - fee) / (px * (1 + cost.slippage_pct))
                cash -= size
                peak_since[sym] = px
                res.trades += 1
                res.fees += fee
            elif not want and qty[sym] > 0:
                gross = qty[sym] * px * (1 - cost.slippage_pct)
                fee = max(cost.min_fee_eur, gross * cost.fee_pct)
                cash += gross - fee
                qty[sym] = 0.0
                res.trades += 1
                res.fees += fee
        # 2. Weekkeuze.
        if last_pick is None or (d - last_pick).days >= RESELECT_DAYS:
            last_pick = d
            if variant.rotate:
                mom = {}
                for s in series:
                    i = idxs[s.inst.symbol] if idxs[s.inst.symbol] is not None else last_idx(s, d)
                    if i is not None and i >= variant.rotate_days:
                        mom[s.inst.symbol] = s.candles[i].close / s.candles[i - variant.rotate_days].close - 1
                top = sorted(mom, key=mom.get, reverse=True)[:variant.rotate]
                rotation = {sym for sym in top if mom[sym] > 0}   # alleen als het echt stijgt
            for s in series:
                i = idxs[s.inst.symbol] if idxs[s.inst.symbol] is not None else last_idx(s, d)
                if i is None:
                    continue
                score = {lab: _sharpe(s, lab, i, ppy) - (0 if lab == "koop_en_houd" else variant.handicap) for lab in labels}
                ranked = sorted(score, key=score.get, reverse=True)
                old = chosen.get(s.inst.symbol)
                new = ["koop_en_houd"] if variant.hold_only else ranked[:variant.vote]
                if old and variant.switch_margin > 0 and score[old[0]] >= score[new[0]] - variant.switch_margin:
                    new = [old[0]] + [x for x in new if x != old[0]][:variant.vote - 1]
                if old and old[0] != new[0]:
                    res.switches += 1
                chosen[s.inst.symbol] = new
        # 3. Signalen op de slotkoers van vandaag, uitvoering morgen.
        bull = True
        if variant.regime and leader is not None:
            li = last_idx(leader, d)
            if li is not None and li >= 200:
                sma = sum(c.close for c in leader.candles[li - 199:li + 1]) / 200
                gap = leader.candles[li].close / sma - 1
                if bull_state is None or abs(gap) > variant.regime_band:
                    bull_state = gap > 0
                bull = bull_state
        for s in series:
            sym, i = s.inst.symbol, idxs[s.inst.symbol]
            if i is None or sym not in chosen:
                continue
            votes = [s.targets[lab][i] for lab in chosen[sym]]
            want = int(sum(votes) * 2 > len(votes))
            if variant.rotate:
                want = int(sym in rotation)
            c = s.candles[i].close
            if qty[sym] > 0:
                peak_since[sym] = max(peak_since[sym], c)
                if variant.trail and s.vol[i] > 0 and c < peak_since[sym] * (1 - variant.trail * s.vol[i] * math.sqrt(10)):
                    want = 0
            if not bull and (qty[sym] == 0 or variant.regime_exit):
                want = 0
            have = qty[sym] > 0
            if want != have:
                pending[sym] = want
        res.equity.append(cash + sum(qty[s.inst.symbol] * s.candles[last_idx(s, d) or 0].close for s in series))
    return res


def live_variant(mode: str) -> Variant:
    """De variant die precies doet wat de afdeling live doet (zie ``desk_mode`` in de config)."""
    if mode == "vasthouden":
        return Variant("gekozen (live)", hold_only=True)
    if mode == "vasthouden_marktweer":
        return Variant("gekozen (live)", hold_only=True, regime=True, regime_exit=True,
                       regime_band=REGIME_BAND.get(mode, 0.0))
    return Variant("gekozen (live)", switch_margin=0.3, regime=True)


def compare(config: HoldingConfig, candles_of: dict[str, list[Candle]], candidates: list[Strategy],
            variants: list[Variant] = VARIANTS, window: int = WINDOW) -> dict[str, dict[str, dict]]:
    """Per afdeling per variant: rendement, Sharpe, max daling, trades, kosten, wissels."""
    out: dict[str, dict[str, dict]] = {}
    for cls, share in config.desks.items():
        insts = [i for i in config.instruments if i.asset_class.value == cls]
        cost = config.costs[cls]
        ppy = PERIODS_PER_YEAR[("1d", cls)]
        series = [_prepare(i, candles_of[i.symbol], candidates, cost, ppy) for i in insts
                  if len(candles_of.get(i.symbol, [])) > window + 60]
        if not series:
            continue
        lead_sym = LEADER.get(cls)
        leader = None
        if lead_sym and len(candles_of.get(lead_sym, [])) > 250:
            li = config.instrument(lead_sym)
            leader = _prepare(li, candles_of[lead_sym], [BuyHold()], config.costs[li.asset_class.value], ppy)
        start = max(s.candles[min(window, len(s.candles) - 1)].ts.date() for s in series)
        capital = config.start_capital_eur * share
        out[cls] = {}
        for v in list(variants) + [live_variant(config.desk_modes.get(cls, "actief"))]:
            r = run_desk(cls, series, leader, config, v, start, capital)
            rets = [b / a - 1 for a, b in zip([capital] + r.equity, r.equity)]
            m = metrics(rets, r.trades, r.fees, 0, ppy)
            out[cls][v.name] = {"return": m.total_return, "sharpe": m.sharpe, "max_dd": m.max_drawdown,
                                "trades": r.trades, "fees": r.fees, "switches": r.switches, "days": len(r.equity)}
            if v.name == "gekozen (live)":
                out[cls][v.name]["curve"] = list(zip(r.dates, r.equity))
    return out


ALLOCATIONS = ("vaste potjes, nooit herverdelen", "vaste verdeling, elk kwartaal terug (live)",
               "naar risico, elk kwartaal")
MOVE_COST = 0.005   # verkopen in de ene afdeling en kopen in de andere kost samen ~0,5% van het verschoven bedrag


def allocation(result: dict[str, dict[str, dict]], shares: dict[str, float], every: int = 91,
               vol_days: int = 90, skip: tuple[str, ...] = (), band: float = 0.10) -> dict[str, dict]:
    """Slimmer verdelen tussen afdelingen? Speelt de live-curves van alle afdelingen samen na
    vanaf de dag dat ze allemaal bestaan, met drie manieren van verdelen."""
    curves = {c: dict(rows["gekozen (live)"]["curve"]) for c, rows in result.items()
              if rows.get("gekozen (live)", {}).get("curve") and c not in skip}
    if len(curves) < 2:
        return {}
    start = max(min(c) for c in curves.values())
    days = sorted({d for c in curves.values() for d in c if d >= start})
    last = {c: None for c in curves}
    rets: dict[str, list[float]] = {c: [] for c in curves}
    for d in days:   # dagrendement per afdeling; geen koers die dag (weekend) = 0
        for c, cur in curves.items():
            v = cur.get(d, last[c])
            rets[c].append(v / last[c] - 1 if last[c] and v else 0.0)
            last[c] = v if v else last[c]
    out = {}
    total_share = sum(shares[c] for c in curves)
    for name in ALLOCATIONS:
        w = {c: shares[c] / total_share for c in curves}
        val = {c: w[c] for c in curves}
        eq, moved = [], 0.0
        for k in range(len(days)):
            for c in curves:
                val[c] *= 1 + rets[c][k]
            tot = sum(val.values())
            if name != ALLOCATIONS[0] and k > 0 and k % every == 0:
                if name == ALLOCATIONS[2] and k >= vol_days:
                    inv = {}
                    for c in curves:
                        r = rets[c][k - vol_days + 1:k + 1]
                        m = sum(r) / len(r)
                        sd = math.sqrt(sum((x - m) ** 2 for x in r) / len(r))
                        inv[c] = 1 / sd if sd > 0 else 0.0
                    w = {c: inv[c] / sum(inv.values()) for c in curves} if sum(inv.values()) else w
                target = {c: tot * w[c] for c in curves}
                if name == ALLOCATIONS[1] and all(abs(val[c] / target[c] - 1) <= band for c in curves):
                    eq.append(tot)
                    continue
                shift = sum(abs(target[c] - val[c]) for c in curves) / 2
                moved += shift
                tot -= shift * MOVE_COST
                val = {c: tot * w[c] for c in curves}
            eq.append(tot)
        dr = [b / a - 1 for a, b in zip([1.0] + eq, eq)]
        m = metrics(dr, 0, 0, 0, 365)
        out[name] = {"return": m.total_return, "sharpe": m.sharpe, "max_dd": m.max_drawdown,
                     "moved": moved, "since": start}
    return out


def compare_report(result: dict[str, dict[str, dict]], now: datetime, demo: bool = False,
                   alloc: dict[str, dict] | None = None, alloc_title: str = "") -> str:
    lines = [f"# Afdelingen-backtest: verbeteringen tegen de huidige versie ({now:%Y-%m-%d})", ""]
    if demo:
        lines += ["**Let op: nep-koersen.** Deze cijfers zeggen niets over echte markten.", ""]
    lines += ["Elke variant speelt de hele afdeling na met weekkeuze, kosten en uitvoering op de volgende opening.",
              "✅ = beter dan wat nu live draait: hogere Sharpe (+0,05) zonder diepere daling. Alleen zo'n variant mag live.", ""]
    names = [v.name for v in VARIANTS if v.name in next(iter(result.values()), {})] + ["gekozen (live)"]
    score = {n: 0 for n in names}
    for cls, rows in result.items():
        base = rows["gekozen (live)"]
        lines += [f"## {cls}", "", "| Variant | Rendement | Sharpe | Max daling | Trades | Kosten € | Wissels |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
        for n in names:
            r = rows[n]
            better = n not in ("vasthouden (maatlat)", "gekozen (live)") and r["sharpe"] > base["sharpe"] + 0.05 and r["max_dd"] <= base["max_dd"] + 0.01
            if better:
                score[n] += 1
            lines.append(f"| {n}{' ✅' if better and n != 'huidig' else ''} | {r['return']:+.1%} | {r['sharpe']:.2f} | "
                         f"{-r['max_dd']:.1%} | {r['trades']} | {r['fees']:.2f} | {r['switches']} |")
        lines.append("")
    lines += ["## Oordeel: beter dan live", "", "| Variant | Afdelingen beter dan live |", "|---|---:|"]
    for n in names[2:-1]:
        lines.append(f"| {n} | {score[n]} van {len(result)} |")
    lines += ["", "## Spelregel: wat live draait moet zich bewijzen", "",
              "| Afdeling | Live: Sharpe | Vorige versie | Vasthouden | Oordeel |", "|---|---:|---:|---:|---|"]
    for cls, rows in result.items():
        live, base, hold = rows["gekozen (live)"], rows["oude versie"], rows["vasthouden (maatlat)"]
        ok = live["sharpe"] >= base["sharpe"] - 0.05 and live["sharpe"] >= hold["sharpe"] - 0.15
        lines.append(f"| {cls} | {live['sharpe']:.2f} | {base['sharpe']:.2f} | {hold['sharpe']:.2f} | "
                     f"{'in orde' if ok else 'NIET in orde: aanpassen'} |")
    if alloc:
        lines += allocation_lines(alloc, alloc_title)
    return "\n".join(lines) + "\n"


def allocation_lines(alloc: dict[str, dict], title: str = "") -> list[str]:
    live = alloc[ALLOCATIONS[1]]
    lines = ["", f"## Verdeling tussen afdelingen{title} (samen, sinds {live['since']})", "",
             f"Herverdelen kost {MOVE_COST:.1%} van het verschoven bedrag. ✅ = beter dan live.", "",
             "| Verdeling | Rendement | Sharpe | Max daling | Verschoven (x pot) |", "|---|---:|---:|---:|---:|"]
    for n, r in alloc.items():
        better = n != ALLOCATIONS[1] and r["sharpe"] > live["sharpe"] + 0.05 and r["max_dd"] <= live["max_dd"] + 0.01
        lines.append(f"| {n}{' ✅' if better else ''} | {r['return']:+.1%} | {r['sharpe']:.2f} | "
                     f"{-r['max_dd']:.1%} | {r['moved']:.2f} |")
    return lines

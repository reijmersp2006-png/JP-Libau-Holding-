"""Strategie-audit: waarom presteert een strategie zoals ze presteert?

De audit verandert geen parameters. Hij ontleedt een bestaande backtest:

- **datakwaliteit**: ongeldige koersbalken, gaten, extreme sprongen, vingerafdruk van de data;
- **causaliteit**: gebruikt het signaal echt alleen data tot het besluitmoment? (herberekend op
  afgekapte reeksen, moet exact gelijk zijn);
- **attributie**: het verschil met koop-en-houd, opgeknipt in log-rendement:
  gemist rendement buiten de markt (per regime en per oorzaak), kosten, en de dagen waarop
  gewisseld werd (instap/uitstap op de opening);
- **gedrag**: snelle heen-en-weer trades, gemiste stijging na uitstappen, herinstap-premie;
- **context**: was de testperiode uitzonderlijk goed voor koop-en-houd?
- **gevoeligheid**: buren van de parameters, gekozen op in-sample data, gemeten out-of-sample;
- **onzekerheid**: blok-bootstrap van het verschil met de maatlat.

Log-rendementen tellen op, dus de onderdelen sommeren exact tot het totale verschil.
"""

from __future__ import annotations

import hashlib
import itertools
import math
from dataclasses import asdict

from jplh.backtest import PERIODS_PER_YEAR, unit_prices
from jplh.config import CostModel
from jplh.models import Candle, Instrument
from jplh.strategies import Strategy, TrendSMA

from nexus import lab, stats


def fingerprint(candles: list[Candle]) -> str:
    h = hashlib.sha256()
    for c in candles:
        h.update(f"{c.ts.isoformat()}|{c.open:.8g}|{c.high:.8g}|{c.low:.8g}|{c.close:.8g}|{c.volume:.8g}\n".encode())
    return h.hexdigest()[:16]


def data_quality(candles: list[Candle], max_gap_days: int = 4, jump: float = 0.10) -> dict:
    invalid = [c.ts.date().isoformat() for c in candles
               if c.open <= 0 or c.close <= 0 or not (c.low <= min(c.open, c.close) <= max(c.open, c.close) <= c.high)]
    zero_vol = [c.ts.date().isoformat() for c in candles if c.volume <= 0]
    flat = [c.ts.date().isoformat() for c in candles if c.open == c.high == c.low == c.close]
    dup = len(candles) - len({c.ts for c in candles})
    unordered = sum(1 for a, b in zip(candles, candles[1:]) if b.ts <= a.ts)
    gaps = [[a.ts.date().isoformat(), b.ts.date().isoformat()] for a, b in zip(candles, candles[1:])
            if (b.ts - a.ts).days > max_gap_days]
    jumps = [[b.ts.date().isoformat(), round(b.close / a.close - 1, 4)] for a, b in zip(candles, candles[1:])
             if a.close > 0 and abs(b.close / a.close - 1) > jump]
    gaps_open = [abs(b.open / a.close - 1) for a, b in zip(candles, candles[1:]) if a.close > 0]
    issues = []
    if invalid:
        issues.append(f"{len(invalid)} ongeldige koersbalken")
    if dup or unordered:
        issues.append("dubbele of ongeordende tijdstempels")
    if jumps:
        issues.append(f"{len(jumps)} sprongen groter dan {jump:.0%} (controleren op splitsing of fout)")
    if len(zero_vol) > len(candles) * 0.02:
        issues.append(f"{len(zero_vol)} balken zonder volume")
    return {"bars": len(candles), "first": candles[0].ts.isoformat() if candles else None,
            "last": candles[-1].ts.isoformat() if candles else None, "fingerprint": fingerprint(candles),
            "invalid_bars": invalid[:20], "zero_volume_bars": len(zero_vol), "flat_bars": len(flat),
            "duplicates": dup, "unordered": unordered, "gaps": gaps, "jumps": jumps,
            "mean_abs_overnight_gap": stats.mean(gaps_open), "ok": not issues, "issues": issues}


def causality_check(strategy: Strategy, candles: list[Candle], samples: int = 40) -> dict:
    """Herberekent het signaal op afgekapte reeksen. Elk verschil betekent dat de strategie in de
    toekomst kijkt."""
    full = strategy.targets(candles)
    n = len(candles)
    lo = min(n - 1, strategy.warmup + 1)
    points = sorted({lo + (n - 1 - lo) * k // max(samples - 1, 1) for k in range(samples)})
    bad = [candles[i].ts.date().isoformat() for i in points if strategy.targets(candles[:i + 1])[-1] != full[i]]
    return {"checked": len(points), "mismatches": bad, "ok": not bad,
            "execution": "besluit op slotkoers i, uitvoering op opening i+1 (simulate gebruikt targets[i-1])"}


def _log(x: float) -> float:
    return math.log1p(x) if x > -1 else -50.0


def attribution(targets: list[int], candles: list[Candle], cost: CostModel, spread_pct: float, start: int, end: int,
                capital: float = 1000.0, causes: list[str] | None = None, regime: list[str] | None = None) -> dict:
    """Verschil met koop-en-houd in log-rendement, opgeknipt in onderdelen die exact optellen.

    ``causes[i]``: waarom de strategie na periode i niet in de markt wilde (optioneel).
    ``regime``: label per periode van ``start`` tot ``end`` (bull/bear)."""
    sim = lab.simulate(targets, candles, cost, spread_pct, start, end, capital)
    bench = lab.simulate([1] * len(candles), candles, cost, spread_pct, start, end, capital, max_volume_share=None)
    regime = regime or lab.regimes(candles, start, end)
    parts: dict[str, float] = {}
    out_by_regime: dict[str, float] = {}
    out_by_cause: dict[str, float] = {}
    out_days = {"bull": 0, "bear": 0, "onbekend": 0}

    def add(key, v):
        parts[key] = parts.get(key, 0.0) + v

    prev_s = capital
    for k in range(end - start):
        i = start + k
        ls, lb = _log(sim.returns[k]), _log(bench.returns[k])
        cs = sim.period_costs[k] / prev_s if prev_s else 0.0
        if sim.traded[k] != 0:
            add("kosten", -cs)
            add("wisseldagen (instap/uitstap op de opening)", ls + cs - lb)
        elif not sim.held[k]:
            add("buiten de markt", -lb)
            g = regime[k]
            out_by_regime[g] = out_by_regime.get(g, 0.0) - lb
            out_days[g] = out_days.get(g, 0) + 1
            if causes is not None and i >= 1:
                cz = causes[i - 1]
                out_by_cause[cz] = out_by_cause.get(cz, 0.0) - lb
        else:
            add("in de markt (zelfde als maatlat)", ls - lb)
        prev_s = sim.equity[k]
    total = sum(_log(r) for r in sim.returns) - sum(_log(r) for r in bench.returns)
    return {
        "strategy_return": math.expm1(sum(_log(r) for r in sim.returns)),
        "benchmark_return": math.expm1(sum(_log(r) for r in bench.returns)),
        "log_excess_total": total, "components_log": parts,
        "check_sum": sum(parts.values()) - total,
        "out_of_market_by_regime_log": out_by_regime, "out_of_market_days": out_days,
        "out_of_market_by_cause_log": out_by_cause, "costs_eur": sim.costs, "trades": len(sim.trades),
        "sim": sim, "bench": bench,
    }


def behaviour(sim: lab.Sim, candles: list[Candle], start: int, quick: int = 3, horizon: int = 20,
              strong: float = 0.03) -> dict:
    closed = [t for t in sim.trades if t.exit_ts is not None]
    idx = {c.ts.isoformat(): i for i, c in enumerate(candles)}
    quick_tr = [t for t in closed if t.bars <= quick]
    missed, reentry = [], []
    for a, b in zip(sim.trades, sim.trades[1:]):
        if a.exit_ts is None:
            continue
        i = idx[a.exit_ts]
        j = min(i + horizon, len(candles) - 1)
        after = candles[j].close / candles[i].open - 1
        if after > strong:
            missed.append({"exit": a.exit_ts[:10], "next_%d_bars" % horizon: after})
        reentry.append({"exit": a.exit_ts[:10], "reentry": b.entry_ts[:10],
                        "bars_out": idx[b.entry_ts] - i, "price_change": b.entry_price / a.exit_price - 1})
    return {
        "closed_trades": len(closed),
        "quick_round_trips": len(quick_tr), "quick_threshold_bars": quick,
        "quick_pnl_eur": sum(t.pnl_eur for t in quick_tr), "quick_costs_eur": sum(t.costs_eur for t in quick_tr),
        "exits_before_strong_rise": missed, "strong_rise_threshold": strong, "horizon_bars": horizon,
        "reentries": reentry,
        "avg_reentry_premium": stats.mean([r["price_change"] for r in reentry]) if reentry else None,
        "avg_bars_out": stats.mean([r["bars_out"] for r in reentry]) if reentry else None,
        "expected_value": stats.expected_value([t.pnl_eur for t in closed]),
    }


def volfilter_causes(strategy: lab.VolatilityFilter, candles: list[Candle]) -> list[str]:
    p = strategy.params
    trend = TrendSMA(p["fast"], p["slow"], 0.01).targets(candles)
    t = strategy.targets(candles)
    return ["in de markt" if t[i] else ("trend omlaag" if not trend[i] else "beweeglijkheid boven mediaan")
            for i in range(len(candles))]


def _window_stats(candles: list[Candle], a: int, b: int, ppy: int) -> dict:
    rets = [candles[i].close / candles[i - 1].close - 1 for i in range(max(a, 1), b)]
    return {"start": candles[a].ts.date().isoformat(), "end": candles[b - 1].ts.date().isoformat(),
            "annual_return": stats.annualized(rets, ppy), "annual_volatility": stats.stdev(rets) * math.sqrt(ppy),
            "sharpe": stats.sharpe(rets, ppy)}


def sensitivity(s: lab.StrategySpec, grid: dict[str, list], candles: list[Candle], cost: CostModel, spread_pct: float,
                warm: int, split: int, n: int, ppy: int, capital: float) -> dict:
    """Burenrooster rond de parameters. Rangorde op in-sample; out-of-sample alleen als controle
    of de in-sample keuze standhield (niet om te kiezen)."""
    rows = []
    keys = list(grid)
    for combo in itertools.product(*grid.values()):
        params = {**s.params, **dict(zip(keys, combo))}
        if "fast" in params and "slow" in params and params["fast"] >= params["slow"]:
            continue
        strat = lab.FACTORIES[s.family](**params)
        t = strat.targets(candles)
        w = max(warm, strat.warmup + 1)
        ins = lab.metrics(lab.simulate(t, candles, cost, spread_pct, w, split, capital), ppy, capital)
        oos = lab.metrics(lab.simulate(t, candles, cost, spread_pct, split, n, capital), ppy, capital)
        rows.append({"params": params, "is_sharpe": ins["sharpe"], "is_return": ins["net_return"],
                     "oos_sharpe": oos["sharpe"], "oos_return": oos["net_return"], "oos_trades": oos["trades"],
                     "original": params == s.params})
    rows.sort(key=lambda r: -r["is_sharpe"])
    best = rows[0] if rows else None
    orig = next((r for r in rows if r["original"]), None)
    return {"grid": grid, "rows": rows, "trials": len(rows), "is_best": best, "original": orig,
            "oos_sharpe_spread": [min(r["oos_sharpe"] for r in rows), max(r["oos_sharpe"] for r in rows)] if rows else None}


SENSITIVITY_GRIDS = {
    "volfilter": {"vol_window": [10, 20, 40], "lookback": [126, 252, 504]},
    "trend": {"fast": [20, 50, 100], "slow": [100, 200, 300]},
    "momentum": {"lookback": [30, 60, 90, 180, 252]},
    "terugkeer": {"low": [20, 25, 30, 35], "high": [50, 55, 65]},
    "uitbraak": {"entry": [20, 55, 100], "exit": [10, 20, 50]},
}


def audit_backtest(s: lab.StrategySpec, inst: Instrument, candles: list[Candle], cost: CostModel,
                   interval: str = "1d", spread_pct: float = 0.001, capital: float = 1000.0,
                   oos_fraction: float = 0.3, oos_start: str | None = None) -> dict:
    """Volledige audit van één strategieversie op één instrument (zelfde aannames als de backtest)."""
    ppy = PERIODS_PER_YEAR[(interval, inst.asset_class.value)]
    raw = candles
    candles = unit_prices(candles, inst)
    strat = s.build()
    result = lab.run_backtest(s, inst, raw, cost, interval, spread_pct, capital, oos_fraction, oos_start=oos_start)
    n = len(candles)
    warm = result["data"]["warmup"]
    split = next(i for i, c in enumerate(candles) if c.ts.isoformat() == result["data"]["oos_start"])
    targets = strat.targets(candles)
    causes = volfilter_causes(strat, candles) if isinstance(strat, lab.VolatilityFilter) else None
    att_oos = attribution(targets, candles, cost, spread_pct, split, n, capital, causes)
    att_full = attribution(targets, candles, cost, spread_pct, warm, n, capital, causes)
    beh = behaviour(att_oos["sim"], candles, split)
    beh_full = behaviour(att_full["sim"], candles, warm)

    # Kosten: hoeveel kosten de trades bij een groter account en zonder kosten?
    zero = CostModel(fee_pct=0.0, slippage_pct=0.0, min_fee_eur=0.0)
    gross = lab.metrics(lab.simulate(targets, candles, zero, 0.0, split, n, capital), ppy, capital)
    big = lab.metrics(lab.simulate(targets, candles, cost, spread_pct, split, n, 10_000.0), ppy, 10_000.0)
    m_oos, b_oos = result["out_of_sample"], result["benchmark"]["out_of_sample"]

    # Context: hoe goed was de out-of-sample periode voor koop-en-houd, vergeleken met de rest?
    context = {"in_sample": _window_stats(candles, warm, split, ppy), "out_of_sample": _window_stats(candles, split, n, ppy),
               "all_history": _window_stats(candles, 0, n, ppy)}
    reg = lab.regimes(candles, split, n)
    context["oos_bull_share"] = reg.count("bull") / len(reg) if reg else None

    unc = stats.excess_uncertainty(att_oos["sim"].returns, att_oos["bench"].returns, ppy)
    grid = SENSITIVITY_GRIDS.get(s.family)
    sens = sensitivity(s, grid, candles, cost, spread_pct, warm, split, n, ppy, capital) if grid else None
    psr = stats.probabilistic_sharpe(att_oos["sim"].returns)
    dsr = stats.deflated_sharpe(att_oos["sim"].returns, sens["trials"] if sens else 1,
                                [r["oos_sharpe"] / math.sqrt(ppy) for r in sens["rows"]] if sens else None)

    def strip(a):
        return {k: v for k, v in a.items() if k not in ("sim", "bench")}

    return {
        "strategy": s.to_dict(), "symbol": inst.symbol, "interval": interval,
        "assumptions": result["assumptions"], "data": result["data"],
        "data_quality": data_quality(raw), "causality": causality_check(strat, candles),
        "original_result": {"out_of_sample": m_oos, "benchmark_oos": b_oos, "full": result["full"],
                            "benchmark_full": result["benchmark"]["full"], "verdict": result["verdict"]},
        "attribution_oos": strip(att_oos), "attribution_full": strip(att_full),
        "behaviour_oos": beh, "behaviour_full": beh_full,
        "costs": {"oos_costs_eur": m_oos["costs_eur"], "oos_gross_return": gross["net_return"],
                  "oos_net_return": m_oos["net_return"], "cost_drag": gross["net_return"] - m_oos["net_return"],
                  "oos_net_return_at_10k": big["net_return"],
                  "per_round_trip_eur_at_capital": 2 * max(cost.min_fee_eur, capital * cost.fee_pct)
                  + capital * (spread_pct + 2 * cost.slippage_pct)},
        "drawdown_tradeoff": {"strategy_mdd": m_oos["max_drawdown"], "benchmark_mdd": b_oos["max_drawdown"],
                              "mdd_reduction": b_oos["max_drawdown"] - m_oos["max_drawdown"],
                              "return_given_up": b_oos["net_return"] - m_oos["net_return"],
                              "strategy_calmar": (m_oos["annual_return"] / m_oos["max_drawdown"]) if m_oos["max_drawdown"] else None,
                              "benchmark_calmar": (b_oos["annual_return"] / b_oos["max_drawdown"]) if b_oos["max_drawdown"] else None},
        "context": context, "uncertainty": unc,
        "probabilistic_sharpe": psr, "deflated_sharpe": dsr,
        "sensitivity": sens,
        "trades_oos": [asdict(t) for t in att_oos["sim"].trades],
    }


# ── Rapport ────────────────────────────────────────────────────────────────────────────────
def _pc(x, d=1):
    return "n.v.t." if x is None else f"{x * 100:+.{d}f}%".replace(".", ",")


def _pu(x, d=1):
    return "n.v.t." if x is None else f"{x * 100:.{d}f}%".replace(".", ",")


def _f(x, d=2):
    return "n.v.t." if x is None else f"{x:.{d}f}".replace(".", ",")


def findings(a: dict) -> list[str]:
    """Bevindingen die direct uit de cijfers volgen (geen interpretatie zonder getal)."""
    out = []
    att, beh, cst = a["attribution_oos"], a["behaviour_oos"], a["costs"]
    comp = att["components_log"]
    total = att["log_excess_total"]
    out_mkt = comp.get("buiten de markt", 0.0)
    m, b = a["original_result"]["out_of_sample"], a["original_result"]["benchmark_oos"]
    out.append(f"Buiten de markt: de strategie zat {_pu(1 - m['exposure'], 0)} van de tijd niet in de markt. "
               f"Dat kostte {_f(-out_mkt * 100, 1)} van de {_f(-total * 100, 1)} log-procentpunt achterstand.")
    for cause, v in sorted(att["out_of_market_by_cause_log"].items(), key=lambda kv: kv[1]):
        out.append(f"  - oorzaak '{cause}': {_f(v * 100, 1)} log-procentpunt")
    for g, v in att["out_of_market_by_regime_log"].items():
        out.append(f"  - in {g}-regime ({att['out_of_market_days'].get(g, 0)} dagen): {_f(v * 100, 1)} log-procentpunt "
                   f"({'gemiste stijging' if v < 0 else 'vermeden daling'})")
    out.append(f"Kosten: {_f(-comp.get('kosten', 0) * 100, 1)} log-procentpunt; €{_f(cst['oos_costs_eur'])} op "
               f"€{_f(a['assumptions']['capital_eur'], 0)} kapitaal, €{_f(cst['per_round_trip_eur_at_capital'])} per "
               f"heen-en-terug. Zonder kosten {_pc(cst['oos_gross_return'])}, met €10.000 kapitaal {_pc(cst['oos_net_return_at_10k'])}.")
    out.append(f"Heen-en-weer: {beh['quick_round_trips']} van {beh['closed_trades']} trades duurden ≤{beh['quick_threshold_bars']} "
               f"dagen, samen €{_f(beh['quick_pnl_eur'])} resultaat na €{_f(beh['quick_costs_eur'])} kosten.")
    if beh["avg_reentry_premium"] is not None:
        out.append(f"Herinstap: gemiddeld {_f(beh['avg_bars_out'], 1)} dagen buiten de markt en {_pc(beh['avg_reentry_premium'], 2)} "
                   f"duurder terug in dan uitgestapt.")
    out.append(f"Uitstappen vóór een stijging van >{_pu(beh['strong_rise_threshold'], 0)} binnen {beh['horizon_bars']} dagen: "
               f"{len(beh['exits_before_strong_rise'])}.")
    dt = a["drawdown_tradeoff"]
    out.append(f"Risico: maximale daling {_pu(dt['strategy_mdd'])} tegen {_pu(dt['benchmark_mdd'])} "
               f"({_f(dt['mdd_reduction'] * 100, 1)} pt minder) voor {_f(dt['return_given_up'] * 100, 1)} pt minder rendement. "
               f"Calmar {_f(dt['strategy_calmar'])} tegen {_f(dt['benchmark_calmar'])}.")
    ctx = a["context"]
    out.append(f"Periode: koop-en-houd haalde out-of-sample {_pc(ctx['out_of_sample']['annual_return'])} per jaar "
               f"(volatiliteit {_pu(ctx['out_of_sample']['annual_volatility'], 0)}), in-sample {_pc(ctx['in_sample']['annual_return'])}, "
               f"over alle data {_pc(ctx['all_history']['annual_return'])}. {_pu(ctx['oos_bull_share'], 0)} van de "
               f"out-of-sample dagen was bull-regime.")
    full_s, full_b = a["original_result"]["full"], a["original_result"]["benchmark_full"]
    out.append(f"Ook over de hele periode achter: {_pc(full_s['net_return'])} tegen {_pc(full_b['net_return'])}, "
               "dus niet alleen pech met de testperiode.")
    u = a["uncertainty"]
    if u.get("available"):
        out.append(f"Onzekerheid: verschil per jaar {_pc(u['excess_annual'])}, 90%-interval {_pc(u['excess_annual_ci90'][0])} "
                   f"tot {_pc(u['excess_annual_ci90'][1])}; kans dat de strategie per jaar beter was: {_pu(u['p_excess_annual_positive'], 1)}.")
    s = a["sensitivity"]
    if s:
        best = s["is_best"]
        out.append(f"Parameters: {s['trials']} buren getest. In-sample beste {best['params']} haalde out-of-sample Sharpe "
                   f"{_f(best['oos_sharpe'])}; de hele rij lag out-of-sample tussen {_f(s['oos_sharpe_spread'][0])} en "
                   f"{_f(s['oos_sharpe_spread'][1])}, tegen {_f(b['sharpe'])} voor koop-en-houd. "
                   f"De originele instelling had in-sample een Sharpe van {_f(s['original']['is_sharpe']) if s['original'] else 'n.v.t.'}.")
    c = a["causality"]
    out.append(f"Look-ahead: {c['checked']} besluitmomenten herberekend op afgekapte data, {len(c['mismatches'])} verschillen.")
    q = a["data_quality"]
    out.append(f"Data: {q['bars']} dagkoersen, {len(q['invalid_bars'])} ongeldig, {len(q['jumps'])} sprongen >10%, "
               f"{len(q['gaps'])} gaten >4 dagen (feestdagen), vingerafdruk {q['fingerprint']}.")
    return out


def markdown(a: dict, conclusions: list[str] | None = None) -> str:
    m, b = a["original_result"]["out_of_sample"], a["original_result"]["benchmark_oos"]
    rows = [("Totaal rendement", _pc(m["net_return"]), _pc(b["net_return"])),
            ("Rendement per jaar", _pc(m["annual_return"]), _pc(b["annual_return"])),
            ("Maximale daling", _pu(m["max_drawdown"]), _pu(b["max_drawdown"])),
            ("Sharpe (95%-interval)", f"{_f(m['sharpe'])} [{_f(m['sharpe_ci95'][0])}; {_f(m['sharpe_ci95'][1])}]",
             f"{_f(b['sharpe'])} [{_f(b['sharpe_ci95'][0])}; {_f(b['sharpe_ci95'][1])}]"),
            ("Sortino", _f(m["sortino"]), _f(b["sortino"])),
            ("Profit factor", _f(m["profit_factor"]), "n.v.t."),
            ("Win rate", _pu(m["win_rate"], 0), "n.v.t."),
            ("Verwachting per trade", f"€{_f(m['expectancy_eur'])}", "n.v.t."),
            ("Tijd in de markt", _pu(m["exposure"], 0), _pu(b["exposure"], 0)),
            ("Rendement per jaar / tijd in markt", _pc(m["exposure_adjusted_return"]), _pc(b["exposure_adjusted_return"])),
            ("Transactiekosten", f"€{_f(m['costs_eur'])}", f"€{_f(b['costs_eur'])}"),
            ("Trades (gesloten)", str(m["trades"]), "1 aankoop")]
    u = a["uncertainty"]
    lines = [f"# Audit: {a['strategy']['name']} v{a['strategy']['version']} op {a['symbol']}", "",
             f"Data {a['data']['first'][:10]} t/m {a['data']['last'][:10]} ({a['data']['bars']} dagen, vingerafdruk "
             f"`{a['data_quality']['fingerprint']}`). Out-of-sample vanaf {a['data']['oos_start'][:10]}. Parameters "
             f"`{a['strategy']['params']}` ongewijzigd (versie 1).", "",
             "## Oorspronkelijke uitkomst (bewaard, niet aangepast)", "",
             "| Out-of-sample | Strategie | Koop-en-houd |", "|---|---|---|"]
    lines += [f"| {r[0]} | {r[1]} | {r[2]} |" for r in rows]
    if u.get("available"):
        lines += ["", f"Verschil met koop-en-houd: {_pc(m['net_return'] - b['net_return'])} totaal; per jaar "
                  f"{_pc(u['excess_annual'])} (90%-interval {_pc(u['excess_annual_ci90'][0])} tot {_pc(u['excess_annual_ci90'][1])}). "
                  f"Probabilistische Sharpe {_pu(a['probabilistic_sharpe'], 0)}, gedefleerd voor "
                  f"{a['sensitivity']['trials'] if a['sensitivity'] else 1} pogingen {_pu(a['deflated_sharpe'], 0)} (drempel 95%)."]
    lines += ["", "## Attributie (log-rendement, out-of-sample)", "", "| Onderdeel | Log-procentpunt |", "|---|---|"]
    for k, v in a["attribution_oos"]["components_log"].items():
        lines.append(f"| {k} | {_f(v * 100, 2)} |")
    lines.append(f"| **Totaal verschil** | **{_f(a['attribution_oos']['log_excess_total'] * 100, 2)}** |")
    lines += ["", "## Bevindingen", ""] + [f"- {x}" if not x.startswith("  ") else f"  {x.strip()}" for x in findings(a)]
    if conclusions:
        lines += ["", "## Conclusie", ""] + [f"{i}. {c}" for i, c in enumerate(conclusions, 1)]
    lines += ["", "## Aannames", "", f"- Uitvoering: {a['assumptions']['execution']}.",
              f"- Kosten: fee {_pu(a['assumptions']['fee_pct'], 2)} (minimaal €{_f(a['assumptions']['min_fee_eur'])}), "
              f"slippage {_pu(a['assumptions']['slippage_pct'], 2)}, spread {_pu(a['assumptions']['spread_pct'], 2)}.",
              f"- Niet gemodelleerd: {', '.join(a['assumptions']['not_modeled'])}."]
    return "\n".join(lines) + "\n"

"""Champion-challenger: een nieuwe strategie vervangt de huidige pas na acht poorten.

1. backtest op de ontwikkelperiode          5. gevoeligheid (buren van de parameters)
2. walk-forward (alleen ongeziene vakken)    6. Monte Carlo (bootstrap van Sharpe en daling)
3. afgesloten holdout, één keer              7. paper trading (minstens ``PAPER_DAYS`` dagen)
4. dubbele kosten                            8. risicotoets + menselijke goedkeuring

Vergeleken met: de huidige kampioen, koop-en-houd, en koop-en-houd geschaald naar hetzelfde
risico. De holdout wordt alleen geopend als poorten 1, 2, 4, 5 en 6 al gehaald zijn; anders blijft
hij onaangeroerd voor later onderzoek. Promotie verandert nooit iets aan live handelen.
"""

from __future__ import annotations

import math

from jplh.models import Candle

from nexus import alpha, lab, stats
from nexus.datasets import ResearchData, universe

PAPER_DAYS = 30
MAX_DRAWDOWN = 0.15            # gelijk aan de Risk Guardian
DEFAULT_CHAMPIONS = {"IWDA.AS": ("volatility_filter", 1)}


def lab_weights(spec_key: str, version: int | None, candles: list[Candle], symbol: str) -> list[dict]:
    t = lab.spec(spec_key, version).build().targets(candles)
    return [{symbol: float(x)} for x in t]


def _gate(status: str, value=None, threshold=None, note: str = "") -> dict:
    return {"status": status, "value": value, "threshold": threshold, "note": note}


def arena(data: ResearchData, symbol: str, interval: str = "1d", capital: float = 1000.0,
          champion: tuple[str, int] | None = None, ledger: alpha.HoldoutLedger | None = None,
          paper_days: dict[str, int] | None = None) -> dict:
    """Kampioen tegen alle uitdagers op één instrument, op exact dezelfde walk-forward-vakken."""
    inst = next(i for i in universe(data.config) if i.symbol == symbol)
    ds = data.load(inst, interval)
    candles = ds.candles
    ppy = ds.ppy
    sp = alpha.make_split(len(candles), alpha.WARMUP)
    if sp is None:
        return {"symbol": symbol, "interval": interval, "status": "insufficient_history", "bars": len(candles)}
    costs = {symbol: alpha.research_costs(data, inst)}
    panel = {symbol: candles}
    n = len(candles)
    bench_w = [{symbol: 1.0}] * n

    champ_key, champ_ver = champion or DEFAULT_CHAMPIONS.get(symbol) or _best_lab(panel, symbol, costs, sp, ppy, capital)
    champ_w = lab_weights(champ_key, champ_ver, candles, symbol)
    champ_wf = _wf_fixed(champ_w, panel, costs, sp, ppy, capital, bench_w)

    challengers = []
    families = [f for f in alpha.FAMILIES if f.kind == "single" and inst.asset_class.value in f.asset_classes]
    trials = sum(len(f.combos()) for f in families)
    for fam in families:
        res = alpha.evaluate_dataset(fam, panel, symbol, costs, ppy, interval, capital, trials)
        frozen_w = alpha._single_weights(fam, candles, ppy, res["frozen_params"], symbol)
        dev = alpha.wmetrics(alpha.simulate_weights(panel, frozen_w, costs, sp.warm, sp.dev_end, capital), ppy, capital)
        wf_ret = _wf_returns(res)
        vs_champ = stats.excess_uncertainty(wf_ret["strategy"], champ_wf["returns"], ppy)
        mc = stats.monte_carlo_drawdown(wf_ret["strategy"])
        m, bm = res["walk_forward"], res["benchmark"]
        gates = {
            "1_backtest": _gate("pass" if dev["sharpe"] > 0 and dev["net_return"] > 0 else "fail",
                                round(dev["sharpe"], 3), "> 0", "ontwikkelperiode, bevroren instelling"),
            "2_walk_forward": _gate("pass" if m["sharpe"] > bm["sharpe"] and m["sharpe"] > champ_wf["metrics"]["sharpe"]
                                    else "fail", round(m["sharpe"], 3),
                                    f"> koop-en-houd {bm['sharpe']:.2f} en kampioen {champ_wf['metrics']['sharpe']:.2f}"),
            "4_costs": _gate("pass" if res["double_costs"]["sharpe"] > res["double_costs"]["bench"] else "fail",
                             round(res["double_costs"]["sharpe"], 3), f"> {res['double_costs']['bench']:.2f} bij 2× kosten"),
            "5_sensitivity": _gate("pass" if res["neighbour_share"] >= alpha.DEV_GATES["min_neighbour_share"] else "fail",
                                   round(res["neighbour_share"], 3), f"≥ {alpha.DEV_GATES['min_neighbour_share']}"),
            "6_monte_carlo": _gate("pass" if (res["uncertainty"].get("p_sharpe_better") or 0) >= alpha.DEV_GATES["min_p_sharpe_better"]
                                   and (vs_champ.get("p_sharpe_better") or 0) >= alpha.DEV_GATES["min_p_sharpe_better"]
                                   and mc.get("p95", 1) <= MAX_DRAWDOWN else "fail",
                                   {"p_vs_buy_hold": res["uncertainty"].get("p_sharpe_better"),
                                    "p_vs_champion": vs_champ.get("p_sharpe_better"), "drawdown_p95": mc.get("p95")},
                                   f"kans ≥ {alpha.DEV_GATES['min_p_sharpe_better']:.0%}, daling p95 ≤ {MAX_DRAWDOWN:.0%}"),
        }
        early = all(g["status"] == "pass" for g in gates.values())
        if early:
            hold = alpha.evaluate_holdout(res, fam, panel, costs, ppy, capital, ledger, run=f"arena-{symbol}")
            if hold["status"] == "evaluated":
                gates["3_holdout"] = _gate("pass" if hold["passed"] else "fail", round(hold["metrics"]["sharpe"], 3),
                                           f"> {hold['benchmark']['sharpe']:.2f}", hold["note"])
            else:
                gates["3_holdout"] = _gate("pending", hold["governance"].get("bars"), hold["governance"].get("needed"),
                                           hold["note"])
        else:
            gates["3_holdout"] = _gate("locked", note="pas open als poorten 1, 2, 4, 5 en 6 gehaald zijn")
        days = (paper_days or {}).get(fam.key, 0)
        gates["7_paper"] = _gate("pass" if days >= PAPER_DAYS else ("pending" if early else "locked"), days,
                                 f"≥ {PAPER_DAYS} dagen")
        risk_ok = m["max_drawdown"] <= MAX_DRAWDOWN and m["exposure"] <= 1.0
        gates["8_risk_review"] = _gate("pending" if risk_ok and early else ("fail" if not risk_ok else "locked"),
                                       round(m["max_drawdown"], 4), f"daling ≤ {MAX_DRAWDOWN:.0%}, geen hefboom; daarna mens",
                                       "menselijke goedkeuring vereist")
        passed = sum(1 for g in gates.values() if g["status"] == "pass")
        challengers.append({
            "family": fam.key, "name": fam.name, "frozen_params": res["frozen_params"],
            "walk_forward": m, "dev_backtest": dev, "vs_champion": vs_champ, "vs_buy_hold": res["uncertainty"],
            "vs_risk_matched": res["risk_matched_excess"], "monte_carlo_drawdown": mc,
            "gates": dict(sorted(gates.items())), "gates_passed": passed,
            "status": "challenger" if early else "rejected", "reasons": res["reasons"],
        })
    challengers.sort(key=lambda c: (-c["gates_passed"], -c["walk_forward"]["sharpe"]))
    return {
        "symbol": symbol, "interval": interval, "capital_eur": capital, "data_notes": list(ds.notes),
        "split": {"warmup_end": candles[sp.warm].ts.isoformat(), "test_start": candles[sp.folds[0][0]].ts.isoformat(),
                  "holdout_start": candles[sp.dev_end].ts.isoformat(), "end": candles[-1].ts.isoformat()},
        "holdout_governance": _governance(symbol, interval, candles, sp, ppy),
        "champion": {"key": champ_key, "version": champ_ver, "walk_forward": champ_wf["metrics"]},
        "buy_hold": champ_wf["bench_metrics"],
        "risk_matched_note": "koop-en-houd geschaald naar de beweeglijkheid van de uitdager, rest in cash (0%)",
        "challengers": challengers, "trials": trials,
        "passed_dev_gates": [c["family"] for c in challengers if c["status"] == "challenger"],
    }


def _wf_fixed(weights: list[dict], panel, costs, sp: alpha.Split, ppy, capital, bench_w) -> dict:
    rets, bench, trips, wsum = [], [], [], []
    cost = 0.0
    orders = 0
    for a, b in sp.folds:
        s = alpha.simulate_weights(panel, weights, costs, a, b, capital)
        bb = alpha.simulate_weights(panel, bench_w, costs, a, b, capital)
        rets += s.returns
        bench += bb.returns
        trips += s.trips
        wsum += s.weights
        cost += s.costs
        orders += s.orders
    sim = alpha.WSim(rets, [], wsum, cost, 0.0, orders, trips)
    return {"returns": rets, "metrics": alpha.wmetrics(sim, ppy, capital),
            "bench_metrics": alpha.wmetrics(alpha.WSim(bench, [], [1.0] * len(bench), 0.0, 0.0, 0), ppy, capital)}


def _wf_returns(res: dict) -> dict:
    return {"strategy": res.get("_wf_returns", [])}


def _best_lab(panel, symbol, costs, sp, ppy, capital) -> tuple[str, int]:
    best, best_sh = ("trend_sma", 1), -math.inf
    candles = panel[symbol]
    for s in lab.SPECS:
        w = lab_weights(s.key, s.version, candles, symbol)
        sh = stats.sharpe(alpha.simulate_weights(panel, w, costs, sp.warm, sp.dev_end, capital).returns, ppy)
        if sh > best_sh:
            best, best_sh = (s.key, s.version), sh
    return best


def _governance(symbol: str, interval: str, candles: list[Candle], sp: alpha.Split, ppy: int) -> dict:
    from nexus import holdout as hg
    key = f"{symbol}@{interval}"
    rule = hg.contamination(key, candles[sp.dev_end].ts.isoformat())
    w = hg.window(candles, sp.dev_end, rule, ppy)
    return {"dataset": key, **{k: v for k, v in w.items() if k not in ("start", "end")}}

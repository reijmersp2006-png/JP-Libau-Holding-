"""Statistiek voor strategie-onderzoek: hoe zeker is een uitkomst?

Een hoger backtest-rendement zegt weinig. De vragen hier:
- hoe breed is de onzekerheid (blok-bootstrap, behoudt de samenhang tussen opeenvolgende dagen);
- hoe groot is de kans dat de echte Sharpe boven een drempel ligt (probabilistische Sharpe);
- hoeveel van een "beste" uitkomst is te verklaren door veel te proberen (gedefleerde Sharpe).

Alles is deterministisch: willekeur gebruikt een vaste seed, zodat een rapport herhaalbaar is.

Bronnen: Bailey & López de Prado (2012, 2014) voor PSR/DSR; Politis & Romano (1994) voor de
stationaire bootstrap; Lo (2002) voor de standaardfout van de Sharpe.
"""

from __future__ import annotations

import math
import random
from statistics import NormalDist

_N = NormalDist()
EULER = 0.5772156649015329


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def stdev(xs: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def sharpe(returns: list[float], ppy: int) -> float:
    sd = stdev(returns)
    return mean(returns) / sd * math.sqrt(ppy) if sd > 0 else 0.0


def moments(xs: list[float]) -> tuple[float, float]:
    """Scheefheid en (niet-excess) kurtosis."""
    n, m, sd = len(xs), mean(xs), stdev(xs)
    if n < 3 or sd == 0:
        return 0.0, 3.0
    skew = sum(((x - m) / sd) ** 3 for x in xs) / n
    kurt = sum(((x - m) / sd) ** 4 for x in xs) / n
    return skew, kurt


def probabilistic_sharpe(returns: list[float], benchmark_sr: float = 0.0) -> float | None:
    """Kans dat de echte Sharpe (per periode) boven ``benchmark_sr`` (per periode) ligt."""
    n = len(returns)
    sd = stdev(returns)
    if n < 10 or sd == 0:
        return None
    sr = mean(returns) / sd
    skew, kurt = moments(returns)
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr * sr
    if denom <= 0:
        return None
    return _N.cdf((sr - benchmark_sr) * math.sqrt(n - 1) / math.sqrt(denom))


def expected_max_sharpe(trials: int, sr_variance: float) -> float:
    """Verwachte hoogste Sharpe (per periode) bij ``trials`` pogingen zonder echte voorsprong."""
    if trials <= 1 or sr_variance <= 0:
        return 0.0
    return math.sqrt(sr_variance) * ((1 - EULER) * _N.inv_cdf(1 - 1 / trials)
                                     + EULER * _N.inv_cdf(1 - 1 / (trials * math.e)))


def deflated_sharpe(returns: list[float], trials: int, trial_sharpes: list[float] | None = None) -> float | None:
    """PSR tegen de Sharpe die je door puur proberen al zou verwachten. Onder 0,95: niet overtuigend."""
    n = len(returns)
    if n < 10:
        return None
    if trial_sharpes and len(trial_sharpes) > 1:
        var = stdev(trial_sharpes) ** 2
    else:
        var = 1.0 / n                          # zonder spreiding: variantie van de Sharpe-schatter
    return probabilistic_sharpe(returns, expected_max_sharpe(max(trials, 1), var))


def block_bootstrap(xs: list[float], stat, samples: int = 1000, block: int = 10, seed: int = 7) -> list[float]:
    """Stationaire bootstrap: trekt blokken met gemiddelde lengte ``block``. Geeft de statistiek per trekking."""
    n = len(xs)
    if n == 0:
        return []
    rng = random.Random(seed)
    p = 1 / max(block, 1)
    out = []
    for _ in range(samples):
        res, i = [], rng.randrange(n)
        while len(res) < n:
            res.append(xs[i])
            i = rng.randrange(n) if rng.random() < p else (i + 1) % n
        out.append(stat(res))
    return out


def quantile(xs: list[float], q: float) -> float:
    s = sorted(xs)
    if not s:
        return float("nan")
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def annualized(returns: list[float], ppy: int) -> float:
    eq = 1.0
    for r in returns:
        eq *= 1 + r
    years = len(returns) / ppy
    return eq ** (1 / years) - 1 if years > 0 and eq > 0 else -1.0


def excess_uncertainty(strategy: list[float], benchmark: list[float], ppy: int, samples: int = 1000,
                       block: int = 10, seed: int = 7) -> dict:
    """Onzekerheid van het verschil met de maatlat, met dagen als paren getrokken."""
    pairs = list(zip(strategy, benchmark))
    if len(pairs) < 20:
        return {"available": False, "reason": "minder dan 20 perioden"}

    def ann_diff(ps):
        return annualized([a for a, _ in ps], ppy) - annualized([b for _, b in ps], ppy)

    def sharpe_diff(ps):
        return sharpe([a for a, _ in ps], ppy) - sharpe([b for _, b in ps], ppy)

    d_ann = block_bootstrap(pairs, ann_diff, samples, block, seed)
    d_sh = block_bootstrap(pairs, sharpe_diff, samples, block, seed + 1)
    return {
        "available": True, "samples": samples, "block": block, "seed": seed,
        "excess_annual": ann_diff(pairs),
        "excess_annual_ci90": [quantile(d_ann, 0.05), quantile(d_ann, 0.95)],
        "p_excess_annual_positive": sum(1 for x in d_ann if x > 0) / len(d_ann),
        "sharpe_diff": sharpe_diff(pairs),
        "sharpe_diff_ci90": [quantile(d_sh, 0.05), quantile(d_sh, 0.95)],
        "p_sharpe_better": sum(1 for x in d_sh if x > 0) / len(d_sh),
    }


def expected_value(trade_pnls: list[float], trade_costs: list[float] | None = None) -> dict:
    """EV = winkans × gem. winst − verlieskans × gem. verlies − kosten. ``trade_pnls`` zijn bruto,
    ``trade_costs`` de kosten per trade. Zonder kosten: pnl's zijn al netto."""
    n = len(trade_pnls)
    if n == 0:
        return {"trades": 0}
    costs = trade_costs or [0.0] * n
    wins = [p for p in trade_pnls if p > 0]
    losses = [-p for p in trade_pnls if p <= 0]
    wr = len(wins) / n
    aw, al = mean(wins), mean(losses)
    c = mean(costs)
    ev = wr * aw - (1 - wr) * al - c
    return {"trades": n, "win_rate": wr, "avg_win": aw, "avg_loss": al, "avg_cost": c, "expected_value": ev,
            "payoff_ratio": aw / al if al > 0 else None,
            "largest_loss": -min(trade_pnls) if trade_pnls else 0.0}


def max_drawdown(returns: list[float]) -> float:
    eq = peak = 1.0
    mdd = 0.0
    for r in returns:
        eq *= 1 + r
        peak = max(peak, eq)
        mdd = max(mdd, 1 - eq / peak)
    return mdd


def monte_carlo_drawdown(returns: list[float], samples: int = 1000, block: int = 10, seed: int = 11) -> dict:
    """Verdeling van de maximale daling als dezelfde dagen in een andere volgorde (blokken) komen."""
    if len(returns) < 20:
        return {"available": False}
    dd = block_bootstrap(returns, max_drawdown, samples, block, seed)
    return {"available": True, "observed": max_drawdown(returns), "median": quantile(dd, 0.5),
            "p95": quantile(dd, 0.95), "p99": quantile(dd, 0.99)}

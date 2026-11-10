"""Stresstest: wat doet de holding van vandaag als het misgaat?

Twee soorten:

1. Echt gebeurd. De huidige verdeling (posities + cash) wordt teruggespeeld op alle koersen die we
   hebben. Daaruit komt de slechtste maand en het slechtste kwartaal dat deze mix echt had gehad.
   Koersen in de eigen munt van het instrument; cash beweegt niet.
2. Scenario's uit de geschiedenis. Vaste schokken per afdeling, ongeveer zoals ze in bekende crashes
   gingen. Die liggen deels vóór onze koersdata, dus het zijn afgeronde aannames en geen metingen.

Daarna kijkt de test naar de vaste grens: zakt een afdeling meer dan de daling-grens, dan gaat ze
op pauze en koopt ze niets meer tot Phil haar hervat.
"""

from __future__ import annotations

from datetime import date, timedelta

from jplh.backtest import unit_prices

# Afgeronde schokken per afdeling, ongeveer zoals in die periode (geen metingen, zie hierboven).
SCENARIOS = [
    {"name": "Coronacrash", "when": "feb–mrt 2020",
     "shock": {"crypto": -0.50, "meme": -0.60, "stocks": -0.33, "metals": -0.12, "fx": -0.03}},
    {"name": "Cryptowinter", "when": "nov 2021 – nov 2022",
     "shock": {"crypto": -0.75, "meme": -0.85, "stocks": -0.20, "metals": -0.05, "fx": 0.02}},
    {"name": "Renteschok", "when": "jan–okt 2022",
     "shock": {"crypto": -0.60, "meme": -0.70, "stocks": -0.25, "metals": -0.10, "fx": 0.05}},
    {"name": "Bankencrisis", "when": "sep 2008 – mrt 2009",
     "shock": {"crypto": -0.60, "meme": -0.80, "stocks": -0.45, "metals": 0.05, "fx": 0.05}},
]


def _series(market, inst, known_at) -> dict[date, float]:
    candles = unit_prices(market.candles(inst.symbol, "1d", known_at=known_at), inst)
    return {c.ts.date(): c.close for c in candles}


def worst_windows(weights: dict[str, float], cash: float, series: dict[str, dict[date, float]],
                  days: int) -> dict | None:
    """Slechtste periode van ``days`` kalenderdagen voor een vaste mix. ``weights`` in euro."""
    syms = [s for s in weights if series.get(s)]
    if not syms:
        return None
    start = max(min(series[s]) for s in syms)          # pas vanaf als alles er is
    end = min(max(series[s]) for s in syms)
    if (end - start).days < days + 30:
        return None
    last = {s: None for s in syms}
    value = {}
    d = start
    while d <= end:                                     # elke kalenderdag, laatste bekende koers
        for s in syms:
            last[s] = series[s].get(d, last[s])
        if all(last[s] for s in syms):
            value[d] = {s: last[s] for s in syms}
        d += timedelta(days=1)
    total = sum(weights[s] for s in syms) + cash
    worst, when = 0.0, None
    for d0, p0 in value.items():
        p1 = value.get(d0 + timedelta(days=days))
        if not p1:
            continue
        after = sum(weights[s] * p1[s] / p0[s] for s in syms) + cash
        r = after / total - 1
        if r < worst:
            worst, when = r, d0
    return {"days": days, "return": worst, "from": when.isoformat() if when else None,
            "to": (when + timedelta(days=days)).isoformat() if when else None, "since": start.isoformat()}


def run(config, desks: dict, market, now) -> dict:
    """De stresstest voor de holding zoals die nu staat."""
    weights: dict[str, float] = {}
    by_desk: dict[str, dict] = {}
    cash = 0.0
    for cls, desk in desks.items():
        h = desk.holding
        prices = h.prices(now)
        pos = {}
        for sym, p in h.portfolio.positions.items():
            try:
                pos[sym] = p.quantity * prices.price_eur(sym)
            except Exception:       # zonder koers telt de positie niet mee
                continue
        weights.update(pos)
        by_desk[cls] = {"invested": sum(pos.values()), "cash": h.portfolio.cash_eur}
        cash += h.portfolio.cash_eur
    total = sum(weights.values()) + cash
    limit = config.risk.max_drawdown_pct
    scenarios = []
    for sc in SCENARIOS:
        lost, paused = 0.0, []
        for cls, d in by_desk.items():
            hit = d["invested"] * sc["shock"].get(cls, 0.0)
            lost += hit
            equity = d["invested"] + d["cash"]
            if equity and -hit / equity >= limit:
                paused.append(cls)
        scenarios.append({"name": sc["name"], "when": sc["when"], "return": lost / total if total else 0.0,
                          "after_eur": total + lost, "paused": paused})
    insts = {i.symbol: i for i in config.instruments}
    series = {s: _series(market, insts[s], now) for s in weights if s in insts}
    real = [w for w in (worst_windows(weights, cash, series, 30), worst_windows(weights, cash, series, 91)) if w]
    return {"computed_at": now.isoformat(), "equity_eur": total, "cash_pct": cash / total if total else 0.0,
            "limit": limit, "scenarios": scenarios, "real": real}

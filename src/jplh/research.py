"""Onderzoekslab: elke afdeling kijkt terug op haar eigen trades en leert ervan.

1. Terugblik. Een week na elke verkoop beoordeelt het lab de hele trade: wat leverde hij op,
   wat had vasthouden opgeleverd, was de verkoop te vroeg of juist op tijd, hoeveel winst
   gaf hij onderweg terug, en welke strategie had in precies die periode het beste gedaan.
2. Leren. Per strategie houdt het lab een live-rapportcijfer bij: hoe deed hij het t.o.v.
   gewoon vasthouden? Een strategie die live na minstens 3 trades slechter is dan vasthouden,
   krijgt strafpunten bij de weekkeuze. Wint hij juist, dan krijgt hij een kleine bonus.
   De straf weegt zwaarder dan de bonus: we willen eerst geen geld weggeven.
3. Weekrapport. Elke week een samenvatting per afdeling: resultaat, wat werkte, wat niet.

Alles gebruikt alleen data die op het moment van beoordelen bekend was.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from jplh.backtest import simulate, unit_prices
from jplh.models import Fill, Side
from jplh.strategies import _nl, _p

REVIEW_AFTER = timedelta(days=7)   # zo lang na de verkoop kijken we hoe het verderging
MIN_TRADES_TO_JUDGE = 3
PENALTY = 0.25                     # Sharpe-strafpunten voor een strategie die live verliest van vasthouden
BONUS = 0.05
WEEK = timedelta(days=7)


@dataclass
class RoundTrip:
    instrument: str
    strategy: str
    entry_ts: datetime
    exit_ts: datetime
    entry_price: float
    exit_price: float
    quantity: float
    fees: float

    @property
    def key(self) -> str:
        return f"{self.instrument}|{self.exit_ts.isoformat()}"

    @property
    def pnl_pct(self) -> float:
        cost = self.entry_price * self.quantity
        return (self.exit_price * self.quantity - self.fees) / cost - 1 if cost else 0.0

    @property
    def pnl_eur(self) -> float:
        return (self.exit_price - self.entry_price) * self.quantity - self.fees


def round_trips(fills: list[Fill]) -> list[RoundTrip]:
    """Koppelt aankopen aan de verkoop die de positie sloot."""
    open_: dict[str, dict] = {}
    out = []
    for f in fills:
        if f.side is Side.BUY:
            o = open_.setdefault(f.instrument, {"qty": 0.0, "cost": 0.0, "fees": 0.0, "ts": f.ts,
                                                "strategy": f.strategy})
            o["qty"] += f.quantity
            o["cost"] += f.quantity * f.price_eur
            o["fees"] += f.fee_eur
        elif f.instrument in open_:
            o = open_.pop(f.instrument)
            out.append(RoundTrip(f.instrument, o["strategy"], o["ts"], f.ts, o["cost"] / o["qty"], f.price_eur,
                                 o["qty"], o["fees"] + f.fee_eur))
    return out


def _close_at(candles, ts: datetime) -> tuple[int, float] | None:
    idx = None
    for i, c in enumerate(candles):
        if c.ts <= ts:
            idx = i
    return (idx, candles[idx].close) if idx is not None else None


def review(trip: RoundTrip, daily, inst, cost, candidates, now: datetime) -> dict | None:
    """Beoordeelt één afgesloten trade. ``daily`` = dagkoersen bekend op ``now``."""
    target = trip.exit_ts + REVIEW_AFTER
    if target > now or not daily or daily[-1].ts + timedelta(days=1) < target - timedelta(days=3):
        return None   # nog niet genoeg tijd of data na de verkoop
    daily = unit_prices(daily, inst)
    a, b, c = _close_at(daily, trip.entry_ts), _close_at(daily, trip.exit_ts), _close_at(daily, trip.exit_ts + REVIEW_AFTER)
    if not (a and b and c) or c[0] <= b[0]:
        return None
    during = [k.close for k in daily[a[0]:b[0] + 1]] or [trip.entry_price]
    top = max(during) / trip.entry_price - 1
    bottom = min(during) / trip.entry_price - 1
    after = c[1] / trip.exit_price - 1
    hold = c[1] / trip.entry_price - 1
    pnl = trip.pnl_pct

    # Wat hadden alle strategieën in precies deze periode (aankoop tot een week na verkoop) gedaan?
    scores, traded = {}, {}
    for s in candidates:
        run = simulate(s, daily, cost, start=a[0] + 1, end=c[0] + 1)
        total = 1.0
        for r in run.returns:
            total *= 1 + r
        scores[s.label] = total - 1
        traded[s.label] = run.trades > 0
    best_label = max(scores, key=scores.get) if scores else trip.strategy
    own = scores.get(trip.strategy)

    if pnl > 0:
        verdict = "winst"
    elif pnl > -0.01:
        verdict = "quitte"
    else:
        verdict = "verlies"
    lessons = []
    if after > 0.03:
        lessons.append(f"te vroeg verkocht: daarna nog {_p(after)}")
    elif after < -0.03:
        lessons.append(f"goed verkocht: daarna zakte de koers nog {_p(after)}")
    else:
        lessons.append("verkoopmoment was prima")
    if top > 0.05 and top - pnl > 0.05:
        lessons.append(f"gaf onderweg winst terug: stond op {_p(top)}, eindigde op {_p(pnl)}")
    if bottom < -0.10:
        lessons.append(f"stond onderweg diep in de min ({_p(bottom)}), dat is veel risico voor deze trade")
    if trip.fees > 0 and abs(trip.pnl_eur) < trip.fees * 2:
        lessons.append(f"de kosten (€{_nl(f'{trip.fees:.2f}')}) waren groot t.o.v. het resultaat")
    if pnl < hold - 0.02:
        lessons.append(f"vasthouden was beter geweest ({_p(hold)})")
    if best_label != trip.strategy and own is not None and scores[best_label] - own > 0.02:
        if traded.get(best_label):
            lessons.append(f"de betere keuze lag bij {best_label} ({_p(scores[best_label])} in dezelfde periode)")
        else:
            lessons.append("de betere keuze was deze keer: niet instappen")
    return {
        "instrument": trip.instrument, "strategy": trip.strategy, "key": trip.key,
        "entry_ts": trip.entry_ts.isoformat(), "exit_ts": trip.exit_ts.isoformat(),
        "days": (trip.exit_ts - trip.entry_ts).days, "pnl_pct": pnl, "pnl_eur": trip.pnl_eur, "fees_eur": trip.fees,
        "hold_pct": hold, "after_exit_pct": after, "top_pct": top, "bottom_pct": bottom,
        "edge_vs_hold": pnl - hold, "best_alternative": best_label, "best_alternative_pct": scores.get(best_label),
        "verdict": verdict, "lessons": lessons,
        "reason": f"terugblik {trip.instrument}: {verdict} {_p(pnl)}. " + "; ".join(lessons),
    }


def track_record(reflections: list[dict]) -> dict[str, dict]:
    """Live-rapportcijfer per strategie, uit alle terugblikken."""
    out: dict[str, dict] = {}
    for r in reflections:
        t = out.setdefault(r["strategy"], {"trades": 0, "wins": 0, "pnl_sum": 0.0, "edge_sum": 0.0})
        t["trades"] += 1
        t["wins"] += r["pnl_pct"] > 0
        t["pnl_sum"] += r["pnl_pct"]
        t["edge_sum"] += r["edge_vs_hold"]
    for t in out.values():
        t["avg_pnl"] = t["pnl_sum"] / t["trades"]
        t["avg_edge"] = t["edge_sum"] / t["trades"]
        t["hit_rate"] = t["wins"] / t["trades"]
    return out


def adjustments(record: dict[str, dict]) -> dict[str, float]:
    """Sharpe-aanpassing per strategie voor de weekkeuze: straf bij verlies t.o.v. vasthouden."""
    adj = {}
    for label, t in record.items():
        if t["trades"] < MIN_TRADES_TO_JUDGE or label == "koop_en_houd":
            continue
        if t["avg_edge"] < 0:
            adj[label] = -PENALTY
        elif t["avg_edge"] > 0.01 and t["hit_rate"] >= 0.5:
            adj[label] = BONUS
    return adj


def weekly_report(desk, now: datetime, reflections: list[dict], record: dict[str, dict]) -> dict:
    """Samenvatting van de afgelopen week voor één afdeling."""
    curve = desk.holding.store.equity_curve()
    week_ago = [e for t, e in curve if t <= now - WEEK]
    start = week_ago[-1] if week_ago else desk.config.start_capital_eur
    end = curve[-1][1] if curve else desk.config.start_capital_eur
    since = now - WEEK
    fills = [f for f in desk.holding.store.fills() if f.ts > since]
    recent = [r for r in reflections if datetime.fromisoformat(r["exit_ts"]) > since - REVIEW_AFTER]
    best = max(recent, key=lambda r: r["pnl_pct"], default=None)
    worst = min(recent, key=lambda r: r["pnl_pct"], default=None)
    adj = adjustments(record)
    lines = [f"Week {now:%d-%m}: potje {_nl(f'{end - start:+.2f}')} euro ({_p(end / start - 1)}), {len(fills)} trades"]
    if best:
        lines.append(f"beste: {best['instrument']} {_p(best['pnl_pct'])}")
    if worst and worst is not best:
        lines.append(f"slechtste: {worst['instrument']} {_p(worst['pnl_pct'])}")
    for label, a in adj.items():
        lines.append(f"{label} krijgt {'strafpunten' if a < 0 else 'een bonus'} in de weekkeuze")
    if not recent:
        lines.append("nog geen afgeronde trades om van te leren")
    return {"desk": desk.cls, "week_return": end / start - 1 if start else 0.0, "trades": len(fills),
            "reviewed": len(recent), "best": best and best["key"], "worst": worst and worst["key"],
            "adjustments": adj, "reason": "weekrapport: " + "; ".join(lines)}

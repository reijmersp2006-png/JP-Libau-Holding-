"""Handelsafdelingen. Elke afdeling draait op zichzelf: eigen potje nepgeld, eigen
boekhouding, eigen logboek en eigen keuze van strategieën.

Een ronde (elk uur):
1. Koersen zijn al opgehaald (uur voor de prijs, dag voor de signalen).
2. Eén keer per week kiest de afdeling per instrument de strategie die op de laatste
   500 dagen het best werkte voor risico (Sharpe), na kosten. Koop-en-houd doet mee:
   als niets beter is, houdt de afdeling gewoon vast. Dit is de leerlus.
3. Per instrument: wil de strategie erin en hebben we niets, dan een koopsignaal; wil ze
   eruit en hebben we wel iets, dan een verkoopsignaal. Elk signaal krijgt de concrete reden
   mee (met de cijfers). De risico-afdeling beslist.
4. Het Onderzoekslab blikt terug op afgesloten trades en past de weekkeuze aan: strategieën
   die live slechter doen dan vasthouden krijgen strafpunten (zie ``research.py``).
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jplh.backtest import PERIODS_PER_YEAR, metrics, simulate, unit_prices
from jplh.config import HoldingConfig
from jplh.holding import Holding
from jplh.models import AssetClass, Decision, Instrument, Side, Signal
from jplh.research import REVIEW_AFTER, WEEK, adjustments, review, round_trips, track_record, weekly_report
from jplh.store import Store
from jplh.strategies import FAMILIES, BuyHold, Strategy, _nl

DESK_ORDER = ("crypto", "meme", "stocks", "metals", "fx")
SELECTION_WINDOW = 500      # dagen waarop de strategie gekozen wordt
RESELECT_EVERY = timedelta(days=7)
MIN_DAILY_BARS = 220        # genoeg voor de langste strategie (200 dagen) plus marge

ALL_CANDIDATES: list[Strategy] = [BuyHold()] + [s for fam in FAMILIES.values() for s in fam]
_BY_LABEL = {s.label: s for s in ALL_CANDIDATES}


def desk_config(config: HoldingConfig, cls: str) -> HoldingConfig:
    """Risico-instellingen voor één afdeling. Het potje van de afdeling IS al haar deel van
    de holding, dus binnen het potje mag de afdeling alleen haar eigen soort kopen."""
    own = [i for i in config.instruments if i.asset_class.value == cls]
    risk = dataclasses.replace(
        config.risk,
        max_class_pct={c: (1.0 if c == cls else 0.0) for c in DESK_ORDER},
        # Met maar 2 instrumenten (goud, zilver) is 25% per stuk te krap om iets te doen.
        max_position_pct=max(config.risk.max_position_pct, 1 / max(len(own), 1)),
    )
    return dataclasses.replace(config, risk=risk,
                               start_capital_eur=config.start_capital_eur * config.desks.get(cls, 0.0))


def choose_strategy(candles, inst: Instrument, config: HoldingConfig, window: int = SELECTION_WINDOW,
                    adjust: dict[str, float] | None = None) -> tuple[str, float]:
    """De beste strategie voor risico op de laatste ``window`` dagen, na kosten.
    ``adjust``: live-straf of -bonus per strategie uit de terugblikken van het lab."""
    adjust = adjust or {}
    candles = unit_prices(candles, inst)
    cost = config.costs[inst.asset_class.value]
    ppy = PERIODS_PER_YEAR[("1d", inst.asset_class.value)]
    start = max(0, len(candles) - window)
    best, best_sharpe = "koop_en_houd", -math.inf
    for strat in ALL_CANDIDATES:
        run = simulate(strat, candles, cost, start=start)
        m = metrics(run.returns, run.trades, run.fees, run.in_market, ppy)
        # Een strategie moet duidelijk beter zijn dan vasthouden om het te verdringen.
        score = m.sharpe if strat.name == "koop_en_houd" else m.sharpe - 0.1
        score += adjust.get(strat.label, 0.0)
        if score > best_sharpe:
            best, best_sharpe = strat.label, score
    return best, best_sharpe


@dataclass
class DeskRound:
    desk: str
    decisions: list[Decision]
    notes: list[str]


class Desk:
    def __init__(self, cls: str, config: HoldingConfig, market: Store, book: Store,
                 base_dir: Path | None, log_dir: Path | None) -> None:
        self.cls = cls
        self.config = desk_config(config, cls)
        self.market = market
        self.instruments = [i for i in config.instruments if i.asset_class.value == cls]
        self.holding = Holding(self.config, book, base_dir, log_dir, market=market)

    @property
    def meta(self) -> dict:
        return self.holding.meta

    def selection(self) -> dict[str, str]:
        return self.meta.get("selection", {})

    def maybe_reselect(self, now: datetime) -> list[str]:
        last = self.meta.get("selected_at")
        if last and now - datetime.fromisoformat(last) < RESELECT_EVERY and self.selection():
            return []
        notes, chosen, scores = [], {}, {}
        adj = adjustments(track_record(self.reflections()))
        for label, a in adj.items():
            notes.append(f"lab: {label} {'strafpunten' if a < 0 else 'bonus'} ({a:+.2f}) door live-resultaten")
        for inst in self.instruments:
            daily = self.market.candles(inst.symbol, "1d", known_at=now)
            if len(daily) < MIN_DAILY_BARS:
                continue
            label, score = choose_strategy(daily, inst, self.config, adjust=adj)
            chosen[inst.symbol] = label
            scores[inst.symbol] = round(score, 2)
            old = self.selection().get(inst.symbol)
            if old != label:
                notes.append(f"{inst.symbol}: {old or 'niets'} -> {label} (Sharpe {score:.2f})")
        self.meta["selection"] = chosen
        self.meta["selection_scores"] = scores
        self.meta["adjustments"] = adj
        self.meta["selected_at"] = now.isoformat()
        self.holding.journal.write(now, "selection", {"desk": self.cls, "selection": chosen, "changes": notes,
                                                       "reason": "weekkeuze strategieën: " + ("; ".join(notes) or "geen wijzigingen")})
        self.holding._save()
        return notes

    def reflections(self) -> list[dict]:
        return [p for _, _, p in reversed(self.holding.store.events(kind="reflection", limit=100_000))]

    def learn(self, now: datetime) -> list[str]:
        """Terugblik op elke trade die minstens een week geleden gesloten is."""
        done = set(self.meta.get("reviewed", []))
        notes = []
        for trip in round_trips(self.holding.store.fills()):
            if trip.key in done or trip.exit_ts + REVIEW_AFTER > now:
                continue
            inst = next((i for i in self.instruments if i.symbol == trip.instrument), None)
            if inst is None:
                continue
            daily = self.market.candles(inst.symbol, "1d", known_at=now)
            r = review(trip, daily, inst, self.config.costs[self.cls], ALL_CANDIDATES, now)
            if r is None:
                continue
            self.holding.journal.write(now, "reflection", {"desk": self.cls, **r})
            done.add(trip.key)
            notes.append(r["reason"])
        if notes:
            self.meta["reviewed"] = sorted(done)
            self.holding._save()
        return notes

    def maybe_report(self, now: datetime) -> str | None:
        last = self.meta.get("report_at")
        started = self.meta.get("started_at")
        if not started or now - datetime.fromisoformat(started) < WEEK:
            return None
        if last and now - datetime.fromisoformat(last) < WEEK:
            return None
        refl = self.reflections()
        rep = weekly_report(self, now, refl, track_record(refl))
        self.holding.journal.write(now, "weekreport", rep)
        self.meta["report_at"] = now.isoformat()
        self.holding._save()
        return rep["reason"]

    def run(self, now: datetime | None = None) -> DeskRound:
        now = now or datetime.now(tz=UTC)
        notes = self.learn(now)
        notes += self.maybe_reselect(now)
        if "benchmark_start" not in self.meta:
            prices = self.holding.prices(now)
            start = {}
            for inst in self.instruments:
                try:
                    start[inst.symbol] = prices.price_eur(inst.symbol)
                except KeyError:
                    pass
            self.meta["benchmark_start"] = start
            self.meta["started_at"] = now.isoformat()
        decisions = []
        per_instrument = self.config.start_capital_eur / max(len(self.instruments), 1)
        for inst in self.instruments:
            label = self.selection().get(inst.symbol)
            if label is None:
                continue
            strat = _BY_LABEL[label]
            daily = self.market.candles(inst.symbol, "1d", known_at=now)
            if not daily:
                continue
            unit = unit_prices(daily, inst)
            want = strat.targets(unit)[-1]
            have = inst.symbol in self.holding.portfolio.positions
            if want and not have:
                equity = self.holding.portfolio.equity_eur(self.holding.prices(now))
                size = equity / max(len(self.instruments), 1) if equity > 0 else per_instrument
                sig = Signal(inst.symbol, Side.BUY, label, self._why(strat, unit, inst.symbol), size)
            elif not want and have:
                why = self._why(strat, unit, inst.symbol)
                opened_by = self._opened_by(inst.symbol)
                if opened_by and opened_by != label:
                    why = (f"de weekkeuze verving {opened_by} door {label}, en die wil hier nu niet in zitten: "
                           + why)
                sig = Signal(inst.symbol, Side.SELL, label, why)
            else:
                continue
            decisions.append(self.holding.submit(sig, now))
        self.holding.mark(now, self.holding.prices(now))
        rep = self.maybe_report(now)
        if rep:
            notes.append(rep)
        return DeskRound(self.cls, decisions, notes)

    def _opened_by(self, symbol: str) -> str | None:
        for f in reversed(self.holding.store.fills()):
            if f.instrument == symbol and f.side is Side.BUY:
                return f.strategy
        return None

    def _why(self, strat: Strategy, unit, symbol: str) -> str:
        why = strat.explain(unit)
        score = self.meta.get("selection_scores", {}).get(symbol)
        if score is not None:
            why += f". Gekozen in de weekkeuze als beste voor risico op 500 dagen (score {_nl(format(score, '.2f'))})"
        return why


def open_desks(config: HoldingConfig, home: Path, market: Store, use_kill_file: bool = True) -> dict[str, Desk]:
    out = {}
    for cls in DESK_ORDER:
        if config.desks.get(cls, 0) <= 0:
            continue
        book = Store(home / "data" / "desks" / f"{cls}.sqlite3")
        out[cls] = Desk(cls, config, market, book, home if use_kill_file else None, home / "logs" / cls)
    return out


def benchmark_equity(desk: Desk, now: datetime | None = None) -> float | None:
    """Wat het potje waard zou zijn als je op dag 1 alles gelijk verdeeld had gekocht."""
    start = desk.meta.get("benchmark_start") or {}
    if not start:
        return None
    prices = desk.holding.prices(now)
    cap = desk.config.start_capital_eur
    total = 0.0
    for sym, p0 in start.items():
        try:
            total += cap / len(start) * prices.price_eur(sym) / p0
        except KeyError:
            total += cap / len(start)
    return total


__all__ = ["ALL_CANDIDATES", "DESK_ORDER", "Desk", "DeskRound", "AssetClass", "benchmark_equity",
           "choose_strategy", "desk_config", "open_desks"]

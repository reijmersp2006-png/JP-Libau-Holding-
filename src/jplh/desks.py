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
from jplh.strategies import FAMILIES, BuyHold, Strategy, _nl, _p

DESK_ORDER = ("crypto", "meme", "stocks", "metals", "fx")
DESK_NAMES = {"crypto": "Crypto Lab", "meme": "Meme Arcade", "stocks": "Beurstoren", "metals": "De Kluis",
              "fx": "Wisselhaven"}
SELECTION_WINDOW = 500      # dagen waarop de strategie gekozen wordt
RESELECT_EVERY = timedelta(days=7)
MIN_DAILY_BARS = 220        # genoeg voor de langste strategie (200 dagen) plus marge
SWITCH_MARGIN = 0.3         # zoveel Sharpe beter moet een nieuwe strategie zijn om de huidige te vervangen
REBALANCE_EVERY = timedelta(days=91)
REBALANCE_BAND = 0.10       # pas herverdelen als een deel meer dan 10% naast zijn doel zit
LEADER = {"crypto": "BTC-EUR", "meme": "BTC-EUR", "stocks": "IWDA.AS"}
# Marge rond het 200-dagengemiddelde per werkwijze: pas omslaan als de leider er zoveel voorbij is.
# Getest in de afdelingen-backtest: crypto 5% gaf Sharpe 1,01 i.p.v. 0,91 en kosten €19 i.p.v. €71.
REGIME_BAND = {"vasthouden_marktweer": 0.05}

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
    scores = score_strategies(candles, inst, config, window, adjust)
    best = max(scores, key=scores.get)
    return best, scores[best]


def score_strategies(candles, inst: Instrument, config: HoldingConfig, window: int = SELECTION_WINDOW,
                     adjust: dict[str, float] | None = None) -> dict[str, float]:
    """Score (Sharpe na kosten, met handicap en lab-aanpassing) voor elke kandidaat."""
    adjust = adjust or {}
    candles = unit_prices(candles, inst)
    cost = config.costs[inst.asset_class.value]
    ppy = PERIODS_PER_YEAR[("1d", inst.asset_class.value)]
    start = max(0, len(candles) - window)
    out = {}
    for strat in ALL_CANDIDATES:
        run = simulate(strat, candles, cost, start=start)
        m = metrics(run.returns, run.trades, run.fees, run.in_market, ppy)
        # Een strategie moet duidelijk beter zijn dan vasthouden om het te verdringen.
        score = m.sharpe if strat.name == "koop_en_houd" else m.sharpe - 0.1
        out[strat.label] = score + adjust.get(strat.label, 0.0)
    return out


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
    def mode(self) -> str:
        return self.config.desk_modes.get(self.cls, "actief")

    def regime(self, now: datetime) -> tuple[bool | None, str]:
        """Marktweer: staat de marktleider boven zijn 200-dagengemiddelde? None = geen leider/data."""
        sym = LEADER.get(self.cls)
        if not sym:
            return None, ""
        daily = self.market.candles(sym, "1d", known_at=now, limit=200)
        if len(daily) < 200:
            return None, ""
        sma = sum(c.close for c in daily) / len(daily)
        gap = daily[-1].close / sma - 1
        band = REGIME_BAND.get(self.mode, 0.0)
        prev = self.meta.get("regime_bull")
        bull = gap > 0 if prev is None or abs(gap) > band else bool(prev)
        self.meta["regime_bull"] = bull
        where = "boven" if gap > 0 else "onder"
        text = f"{sym} staat {_nl(f'{abs(gap):.1%}')} {where} zijn 200-dagengemiddelde"
        if band and abs(gap) <= band and (gap > 0) != bull:
            text += f", binnen de marge van {_nl(f'{band:.0%}')}: we houden de vorige stand aan om heen-en-weer te voorkomen"
        return bull, f"marktweer {'goed' if bull else 'slecht'}: {text}"

    @property
    def meta(self) -> dict:
        return self.holding.meta

    def exposure(self) -> float:
        """Hoeveel van het potje volgens de Risicodirecteur in de markt hoort (1,0 = alles)."""
        from jplh.riskdirector import WING
        if not self.config.risk_director or self.cls not in WING:
            return 1.0
        st = self.market.get_state("risk") or {}
        e = st.get("exposure")
        return min(1.0, max(0.0, float(e))) if isinstance(e, (int, float)) else 1.0

    def follow_director(self, now: datetime, e: float) -> list[Decision]:
        """Verschuift de Risicodirecteur zijn stand, dan schuiven de posities mee: bij minder
        risico alleen verkopen, bij meer risico alleen bijkopen. Elke positie gaat naar
        stand x (potje / aantal instrumenten), net als een nieuwe aankoop."""
        prev = float(self.meta.get("risk_exposure", 1.0))
        if abs(e - prev) < 1e-9:
            return []
        held = self.holding.portfolio.positions
        out: list[Decision] = []
        if held:
            prices = self.holding.prices(now)
            values = {}
            for sym, pos in held.items():
                try:
                    values[sym] = pos.quantity * prices.price_eur(sym)
                except KeyError:
                    values = {}
                    break
            equity = self.holding.portfolio.equity_eur(prices) if values else 0.0
            target = e * equity / max(len(self.instruments), 1)
            for sym, v in sorted(values.items(), key=lambda kv: -kv[1]):   # eerst verkopen, dan kopen
                drift = v / target - 1 if target > 0 else 1.0
                if abs(drift) < REBALANCE_BAND or (drift < 0) == (e < prev):
                    continue
                side = Side.SELL if drift > 0 else Side.BUY
                why = (f"Risicodirecteur: crypto en memes bewegen {'wilder' if e < prev else 'rustiger'}, de stand gaat van "
                       f"{_nl(f'{prev:.0%}')} naar {_nl(f'{e:.0%}')} in de markt. {sym} gaat naar "
                       f"{_nl(format(target, ',.2f'))} euro")
                label = self.selection().get(sym, "koop_en_houd")
                out.append(self.holding.submit(Signal(sym, side, label, why, abs(v - target)), now))
        if all(d.approved for d in out):    # geweigerd (bijv. oude koers)? dan volgende ronde opnieuw
            self.meta["risk_exposure"] = e
        self.holding._save()
        return out

    def selection(self) -> dict[str, str]:
        return self.meta.get("selection", {})

    def maybe_reselect(self, now: datetime) -> list[str]:
        last = self.meta.get("selected_at")
        same_mode = self.meta.get("mode") == self.mode
        if last and same_mode and now - datetime.fromisoformat(last) < RESELECT_EVERY and self.selection():
            return []
        self.meta["mode"] = self.mode
        notes, chosen, scores = [], {}, {}
        if self.mode != "actief":
            for inst in self.instruments:
                if self.market.candles(inst.symbol, "1d", known_at=now, limit=1):
                    chosen[inst.symbol] = "koop_en_houd"
            if self.selection() != chosen:
                notes.append(f"kern: deze afdeling houdt vast ({self.mode.replace('_', ' + ')})")
            adj = {}
        else:
            adj = adjustments(track_record(self.reflections()))
            for label, a in adj.items():
                notes.append(f"lab: {label} {'strafpunten' if a < 0 else 'bonus'} ({a:+.2f}) door live-resultaten")
            for inst in self.instruments:
                daily = self.market.candles(inst.symbol, "1d", known_at=now)
                if len(daily) < MIN_DAILY_BARS:
                    continue
                all_scores = score_strategies(daily, inst, self.config, adjust=adj)
                label = max(all_scores, key=all_scores.get)
                old = self.selection().get(inst.symbol)
                # Minder heen-en-weer: de huidige strategie blijft, tenzij de nieuwe duidelijk beter is.
                if old in all_scores and old != label and all_scores[old] >= all_scores[label] - SWITCH_MARGIN:
                    label = old
                chosen[inst.symbol] = label
                scores[inst.symbol] = round(all_scores[label], 2)
                if old != label:
                    notes.append(f"{inst.symbol}: {old or 'niets'} -> {label} (Sharpe {all_scores[label]:.2f})")
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
        bull, weather = self.regime(now) if self.mode != "vasthouden" else (None, "")
        e = self.exposure()
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
            blocked = None
            if bull is False and (self.mode == "vasthouden_marktweer" or (self.mode == "actief" and not have)):
                if want:
                    blocked = weather
                want = 0
            if want and not have:
                equity = self.holding.portfolio.equity_eur(self.holding.prices(now))
                size = (equity / max(len(self.instruments), 1) if equity > 0 else per_instrument) * e
                why = self._why(strat, unit, inst.symbol) + (f". {weather}" if weather else "")
                if e < 1.0:
                    why += f". Risicodirecteur: {_nl(f'{e:.0%}')} van het normale bedrag"
                sig = Signal(inst.symbol, Side.BUY, label, why, size)
            elif not want and have:
                why = (f"noodrem: {blocked}. Eruit tot het marktweer weer goed is" if blocked
                       else self._why(strat, unit, inst.symbol))
                opened_by = self._opened_by(inst.symbol)
                if opened_by and opened_by != label and not blocked:
                    why = (f"de weekkeuze verving {opened_by} door {label}, en die wil hier nu niet in zitten: "
                           + why)
                sig = Signal(inst.symbol, Side.SELL, label, why)
            else:
                continue
            decisions.append(self.holding.submit(sig, now))
        decisions += self.follow_director(now, e)
        decisions += self.maybe_rebalance(now)
        self.holding.mark(now, self.holding.prices(now))
        rep = self.maybe_report(now)
        if rep:
            notes.append(rep)
        return DeskRound(self.cls, decisions, notes)

    def maybe_rebalance(self, now: datetime) -> list[Decision]:
        """Kern-afdelingen: elk kwartaal terug naar gelijke delen, als iets ver is afgedreven."""
        if self.mode == "actief":
            return []
        last = self.meta.get("rebalanced_at") or self.meta.get("started_at")
        if not last or now - datetime.fromisoformat(last) < REBALANCE_EVERY:
            return []
        self.meta["rebalanced_at"] = now.isoformat()
        held = self.holding.portfolio.positions
        if len(held) < 2:
            return []
        prices = self.holding.prices(now)
        values = {}
        for sym, pos in held.items():
            try:
                values[sym] = pos.quantity * prices.price_eur(sym)
            except KeyError:
                return []
        target = sum(values.values()) / len(values)
        out = []
        for sym, v in sorted(values.items(), key=lambda kv: -kv[1]):   # eerst verkopen, dan kopen
            drift = v / target - 1
            if abs(drift) < REBALANCE_BAND:
                continue
            side = Side.SELL if drift > 0 else Side.BUY
            why = (f"kwartaal-herverdeling: {sym} is {_p(drift)} t.o.v. zijn deel, terug naar gelijke delen "
                   f"({_nl(format(target, ',.2f'))} euro elk)")
            out.append(self.holding.submit(Signal(sym, side, "koop_en_houd", why, abs(v - target)), now))
        self.holding._save()
        return out

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


def rebalance_desks(desks: dict[str, Desk], market: Store, now: datetime) -> list[str]:
    """Elk kwartaal het geld tussen de afdelingen terug naar de vaste verdeling uit de config
    (``[desks]``), als een afdeling meer dan 10% naast haar deel zit. Getest in de
    afdelingen-backtest: zelfde of hoger rendement, kleinere daling (zie 'Verdeling')."""
    if len(desks) < 2:
        return []
    state = market.get_state("desk_rebalance", {})
    starts = [d.meta.get("started_at") for d in desks.values() if d.meta.get("started_at")]
    last = state.get("at") or (min(starts) if starts else None)
    if not last or now - datetime.fromisoformat(last) < REBALANCE_EVERY:
        return []
    market.set_state("desk_rebalance", {"at": now.isoformat()})
    shares = {c: d.config.start_capital_eur for c, d in desks.items()}
    prices = {c: d.holding.prices(now) for c, d in desks.items()}
    value = {c: d.holding.portfolio.equity_eur(prices[c]) for c, d in desks.items()}
    total = sum(value.values())
    target = {c: total * shares[c] / sum(shares.values()) for c in desks}
    over = {c: value[c] - target[c] for c in desks if value[c] > target[c] * (1 + REBALANCE_BAND)}
    under = {c: target[c] - value[c] for c in desks if value[c] < target[c] * (1 - REBALANCE_BAND)}
    if not over or not under:
        return []
    notes = []
    freed = 0.0
    for c, excess in over.items():   # 1. te grote afdelingen maken cash vrij
        d = desks[c]
        need = excess - d.holding.portfolio.cash_eur
        held = {}
        for sym, pos in d.holding.portfolio.positions.items():
            try:
                held[sym] = pos.quantity * prices[c].price_eur(sym)
            except KeyError:
                pass
        if need > 0 and held:
            for sym, v in held.items():
                part = min(v, need * v / sum(held.values()))
                why = (f"herverdeling tussen afdelingen: {DESK_NAMES.get(c, c)} is "
                       f"{_p(value[c] / target[c] - 1)} t.o.v. haar deel van de holding")
                d.holding.submit(Signal(sym, Side.SELL, "koop_en_houd", why, part), now)
        give = min(excess, d.holding.portfolio.cash_eur)
        _transfer(d, -give, now)
        freed += give
        notes.append(f"{DESK_NAMES.get(c, c)} geeft {_nl(format(give, ',.2f'))} euro af")
    want = sum(under.values())
    for c, short in under.items():   # 2. te kleine afdelingen krijgen het naar verhouding
        d = desks[c]
        got = freed * short / want
        _transfer(d, got, now)
        notes.append(f"{DESK_NAMES.get(c, c)} krijgt {_nl(format(got, ',.2f'))} euro")
        if d.mode != "actief" and d.meta.get("regime_bull") is not False:
            held = {}
            for sym, pos in d.holding.portfolio.positions.items():
                try:
                    held[sym] = pos.quantity * prices[c].price_eur(sym)
                except KeyError:
                    pass
            for sym, v in held.items():
                why = "herverdeling tussen afdelingen: extra geld naar verhouding bijgekocht"
                d.holding.submit(Signal(sym, Side.BUY, "koop_en_houd", why, got * v / sum(held.values())), now)
    for c in set(over) | set(under):
        d = desks[c]
        d.holding.journal.write(now, "selection", {"reason": "kwartaal-herverdeling tussen afdelingen: " + "; ".join(notes)})
        d.holding._save()
    return notes


def _transfer(desk: Desk, amount: float, now: datetime) -> None:
    """Cash tussen potjes schuiven. Top en dagstart schuiven mee, zodat een overboeking
    geen nep-verlies (en geen pauze) oplevert."""
    h = desk.holding
    h.portfolio.cash_eur += amount
    h.meta["peak_equity"] = max(h.meta.get("peak_equity", 0.0) + amount, 0.0)
    h.meta["day_start_equity"] = h.meta.get("day_start_equity", 0.0) + amount
    desk.meta["transfers_eur"] = desk.meta.get("transfers_eur", 0.0) + amount
    h.journal.write(now, "transfer", {"amount_eur": amount})


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

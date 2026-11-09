"""Eén paper-ronde voor de hele holding, plus een demo-wereld om het dashboard te bekijken."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jplh.arena import maybe_run_arena
from jplh.collect import collect_candles, collect_fx_reference, collect_radar, collect_shadow, collect_watch
from jplh.config import HoldingConfig
from jplh.data import Bitvavo, Demo, Yahoo
from jplh.desks import open_desks, rebalance_desks
from jplh.models import Candle
from jplh.notify import notify
from jplh.scouts import scan
from jplh.site import build_state, write_site
from jplh.store import Store


def paper_round(config: HoldingConfig, home: Path, site_dir: Path | None = None, collect: bool = True,
                now: datetime | None = None, log=print) -> int:
    """Koersen ophalen, elke afdeling laten handelen, dashboard bijwerken. Geeft het aantal
    mislukte databronnen terug (0 = alles gelukt)."""
    now = now or datetime.now(tz=UTC)
    market = Store(home / "data" / "holding.sqlite3")
    failed = 0
    problems: list[str] = []
    if collect:
        sources = {"bitvavo": Bitvavo(), "yahoo": Yahoo()}
        results = collect_candles(config, market, sources, "1h", 48, now)
        # Eén keer per dag diep terug (voor de 'wat als'-machine), anders alleen het recente stuk.
        deep = market.get_state("deep_1d") != now.date().isoformat()
        results += collect_candles(config, market, sources, "1d", 1500 if deep else 600, now)
        if deep:
            market.set_state("deep_1d", now.date().isoformat())
        results += collect_fx_reference(config, market, now=now)
        results += collect_radar(market, now=now)
        for r in results:
            if not r.ok:
                failed += 1
                problems.append(f"{r.symbol} ({r.error})")
                log(f"FAIL  {r.symbol}: {r.error}")
        log(f"Koersen: {len(results) - failed} van {len(results)} gelukt")
        watch = collect_watch(config, market, sources, now)
        for r in watch:
            if not r.ok:
                log(f"verkenner mist {r.symbol}: {r.error}")
        log(f"Verkenners: {sum(r.ok for r in watch)} van {len(watch)} extra markten binnen")
        shadow = collect_shadow(config, market, sources, now, 1500 if deep else 600)
        for r in shadow:
            if not r.ok:
                log(f"schaduw mist {r.symbol}: {r.error}")
        if shadow:
            log(f"Schaduw-afdelingen: {sum(r.ok for r in shadow)} van {len(shadow)} koersen binnen")
    desks = open_desks(config, home, market)
    for cls, desk in desks.items():
        rnd = desk.run(now)
        for note in rnd.notes:
            log(f"{cls:<7} keuze  {note}")
        for d in rnd.decisions:
            log(f"{cls:<7} {'OK ' if d.approved else 'NEE'}  {d.signal.instrument}: {d.reason}")
        eq = desk.holding.portfolio.equity_eur(desk.holding.prices(now))
        log(f"{cls:<7} potje €{eq:,.2f}")
    for note in rebalance_desks(desks, market, now):
        log(f"holding  herverdeling  {note}")
    for a in scan(market, watch_list(config), now):
        log(f"verkenner {a.level:<6} {a.text}")
    maybe_run_arena(config, market, [d.holding.store for d in desks.values()], now, log)
    if site_dir is not None:
        state = build_state(config, desks, market, home, now, problems=problems)
        write_site(state, site_dir)
        notify(state, market, now, log=log)
        log(f"Dashboard bijgewerkt in {site_dir}")
    return failed


def watch_list(config: HoldingConfig) -> list[tuple[str, str]]:
    return [(i.symbol, i.symbol) for i in config.instruments] + [(w.symbol, w.name) for w in config.watch]


def build_demo(config: HoldingConfig, home: Path, hours: int = 96, now: datetime | None = None,
               history_days: int = 60) -> Path:
    """Maakt een nep-wereld: ~2 jaar nep-dagkoersen, ``history_days`` dagen met één ronde per
    dag (zodat het lab al trades kan terugblikken) en daarna ``hours`` rondes per uur.
    Alles staat in ``home``, los van je echte data."""
    now = (now or datetime.now(tz=UTC)).replace(minute=5, second=0, microsecond=0)
    if home.exists():
        shutil.rmtree(home)
    (home / "data").mkdir(parents=True)
    market = Store(home / "data" / "holding.sqlite3")
    kinds = {i.symbol: i.asset_class.value for i in config.instruments}
    kinds.update({w.symbol: "stocks" for w in config.watch})
    hourly = Demo(kinds, seed=11, end=now)
    for inst in list(config.instruments) + list(config.watch):
        h = hourly.candles(inst.symbol, "1h", hours + 48 + history_days * 24)
        market.save_observed(inst.symbol, "1h", h, "demo", timedelta(hours=1))
        # Dagkoersen die netjes aansluiten op de uurkoersen.
        last_close = h[0].open
        d = Demo(kinds, seed=5, end=h[0].ts.replace(hour=0)).candles(inst.symbol, "1d", 700)
        k = last_close / d[-1].close
        d = [Candle(c.ts, c.open * k, c.high * k, c.low * k, c.close * k, c.volume) for c in d]
        # Daarna dagkoersen gebouwd uit de uurkoersen, zodat signalen in de demo meebewegen.
        days: dict = {}
        for c in h:
            days.setdefault(c.ts.replace(hour=0), []).append(c)
        for day, cs in sorted(days.items()):
            if day > d[-1].ts and len(cs) == 24:
                d.append(Candle(day, cs[0].open, max(c.high for c in cs), min(c.low for c in cs), cs[-1].close,
                                sum(c.volume for c in cs)))
        market.save_observed(inst.symbol, "1d", d, "demo", timedelta(days=1))
    # Schaduw-afdelingen: alleen dagkoersen (rustig voor geldmarkt/obligaties).
    calm = {"schatkist": "fx", "obligaties": "fx", "vastgoed": "stocks", "grondstoffen": "metals"}
    kinds.update({x.symbol: calm.get(x.desk, "stocks") for x in config.shadow})
    for x in config.shadow:
        d = Demo(kinds, seed=7, end=now.replace(hour=0)).candles(x.symbol, "1d", 760)
        market.save_observed(x.symbol, "1d", d, "demo", timedelta(days=1))
    desks = open_desks(config, home, market, use_kill_file=False)
    steps = [now - timedelta(hours=hours + 24 * d) for d in range(history_days, 0, -1)]
    steps += [now - timedelta(hours=i) for i in range(hours, -1, -1)]
    for t in steps:
        for desk in desks.values():
            desk.run(t)
        rebalance_desks(desks, market, t)
        scan(market, watch_list(config), t)
    maybe_run_arena(config, market, [d.holding.store for d in desks.values()], now, log=lambda *_: None)
    site = home / "site"
    write_site(build_state(config, desks, market, home, now, demo=True), site)
    return site

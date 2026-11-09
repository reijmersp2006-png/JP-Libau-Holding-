"""Eén paper-ronde voor de hele holding, plus een demo-wereld om het dashboard te bekijken."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jplh.collect import collect_candles, collect_fx_reference, collect_radar
from jplh.config import HoldingConfig
from jplh.data import Bitvavo, Demo, Yahoo
from jplh.desks import open_desks
from jplh.site import build_state, write_site
from jplh.store import Store


def paper_round(config: HoldingConfig, home: Path, site_dir: Path | None = None, collect: bool = True,
                now: datetime | None = None, log=print) -> int:
    """Koersen ophalen, elke afdeling laten handelen, dashboard bijwerken. Geeft het aantal
    mislukte databronnen terug (0 = alles gelukt)."""
    now = now or datetime.now(tz=UTC)
    market = Store(home / "data" / "holding.sqlite3")
    failed = 0
    if collect:
        sources = {"bitvavo": Bitvavo(), "yahoo": Yahoo()}
        results = collect_candles(config, market, sources, "1h", 48, now)
        results += collect_candles(config, market, sources, "1d", 600, now)
        results += collect_fx_reference(config, market, now=now)
        results += collect_radar(market, now=now)
        for r in results:
            if not r.ok:
                failed += 1
                log(f"FAIL  {r.symbol}: {r.error}")
        log(f"Koersen: {len(results) - failed} van {len(results)} gelukt")
    desks = open_desks(config, home, market)
    for cls, desk in desks.items():
        rnd = desk.run(now)
        for note in rnd.notes:
            log(f"{cls:<7} keuze  {note}")
        for d in rnd.decisions:
            log(f"{cls:<7} {'OK ' if d.approved else 'NEE'}  {d.signal.instrument}: {d.reason}")
        eq = desk.holding.portfolio.equity_eur(desk.holding.prices(now))
        log(f"{cls:<7} potje €{eq:,.2f}")
    if site_dir is not None:
        write_site(build_state(config, desks, market, home, now), site_dir)
        log(f"Dashboard bijgewerkt in {site_dir}")
    return failed


def build_demo(config: HoldingConfig, home: Path, hours: int = 96, now: datetime | None = None) -> Path:
    """Maakt een nep-wereld: ~2 jaar nep-dagkoersen en een paar dagen paper-rondes per uur.
    Alles staat in ``home``, los van je echte data."""
    now = (now or datetime.now(tz=UTC)).replace(minute=5, second=0, microsecond=0)
    if home.exists():
        shutil.rmtree(home)
    (home / "data").mkdir(parents=True)
    market = Store(home / "data" / "holding.sqlite3")
    kinds = {i.symbol: i.asset_class.value for i in config.instruments}
    hourly = Demo(kinds, seed=11, end=now)
    for inst in config.instruments:
        h = hourly.candles(inst.symbol, "1h", hours + 48)
        market.save_observed(inst.symbol, "1h", h, "demo", timedelta(hours=1))
        # Dagkoersen die netjes aansluiten op de uurkoersen.
        last_close = h[0].open
        d = Demo(kinds, seed=5, end=h[0].ts.replace(hour=0)).candles(inst.symbol, "1d", 700)
        k = last_close / d[-1].close
        from jplh.models import Candle
        d = [Candle(c.ts, c.open * k, c.high * k, c.low * k, c.close * k, c.volume) for c in d]
        market.save_observed(inst.symbol, "1d", d, "demo", timedelta(days=1))
    desks = open_desks(config, home, market, use_kill_file=False)
    for i in range(hours, -1, -1):
        t = now - timedelta(hours=i)
        for desk in desks.values():
            desk.run(t)
    site = home / "site"
    write_site(build_state(config, desks, market, home, now, demo=True), site)
    return site

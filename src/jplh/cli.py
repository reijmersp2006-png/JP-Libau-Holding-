"""Opdrachtregel: ``jplh <opdracht>``. Draai ``jplh --help`` voor de lijst."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from jplh import __version__
from jplh.collect import collect_candles, collect_fx_reference, collect_radar
from jplh.config import ConfigError, load_config
from jplh.data import Bitvavo, DataError, Demo, DexScreener, ECB, Yahoo
from jplh.holding import Holding
from jplh.models import Side, Signal
from jplh.store import Store


def _paths(home: Path) -> tuple[Path, Path, Path]:
    return home / "config" / "holding.toml", home / "data" / "holding.sqlite3", home / "logs"


def _open(args):
    cfg_path, db_path, log_dir = _paths(args.home)
    config = load_config(cfg_path)
    store = Store(db_path)
    return config, store, log_dir


def cmd_doctor(args) -> int:
    """Kan elke databron bereikt worden? FAIL betekent: die afdeling krijgt geen koersen."""
    try:
        config = load_config(_paths(args.home)[0])
        print(f"OK    config: {len(config.instruments)} instrumenten, mode={config.mode}")
    except ConfigError as exc:
        print(f"FAIL  config: {exc}")
        return 1
    checks = [("bitvavo (crypto, memecoins)", Bitvavo()), ("yahoo (aandelen, goud/zilver, valuta)", Yahoo()),
              ("ecb (officiële wisselkoersen)", ECB()), ("dexscreener (memecoin-radar)", DexScreener())]
    failed = 0
    for label, src in checks:
        try:
            print(f"OK    {label}: {src.ping()}")
        except (DataError, KeyError, ValueError) as exc:
            failed += 1
            print(f"FAIL  {label}: {exc}")
    return 1 if failed else 0


def cmd_collect(args) -> int:
    config, store, _ = _open(args)
    now = datetime.now(tz=UTC)
    if args.demo:
        demo = Demo({i.symbol: i.asset_class.value for i in config.instruments}, end=now)
        sources = {"bitvavo": demo, "yahoo": demo}
    else:
        sources = {"bitvavo": Bitvavo(), "yahoo": Yahoo()}
    results = collect_candles(config, store, sources, interval=args.interval, limit=args.limit, now=now)
    if not args.demo and args.interval == "1h":
        results += collect_fx_reference(config, store, now=now)
        if not args.no_radar:
            results += collect_radar(store, now=now)
    bad = 0
    for r in results:
        if r.ok:
            print(f"OK    {r.symbol}: {r.new} nieuw")
        else:
            bad += 1
            print(f"FAIL  {r.symbol}: {r.error}")
    print(f"{len(results) - bad} van {len(results)} gelukt")
    return 1 if bad == len(results) else 0


def cmd_backtest(args) -> int:
    """Walk-forward-backtest van alle strategieën per afdeling, met rapport in reports/."""
    from jplh.backtest import run_lab
    from jplh.report import backtest_report

    config = load_config(_paths(args.home)[0])
    instruments = [i for i in config.instruments if not args.symbol or i.symbol in args.symbol]
    now = datetime.now(tz=UTC)
    if args.demo:
        demo = Demo({i.symbol: i.asset_class.value for i in config.instruments}, end=now)
        candles_of = {i.symbol: demo.candles(i.symbol, args.interval, args.bars) for i in instruments}
    else:
        store = Store(_paths(args.home)[1])
        candles_of = {i.symbol: store.candles(i.symbol, args.interval) for i in instruments}
        short = [s for s, c in candles_of.items() if len(c) < args.train + args.test]
        if short:
            print(f"Te weinig koersen voor: {', '.join(short)}. Draai eerst "
                  f"'jplh collect --interval {args.interval} --limit 1500'.")
    results = run_lab(instruments, candles_of, config.costs, args.interval, args.train, args.test)
    if not results:
        print("Geen enkel instrument heeft genoeg koersen voor een backtest.")
        return 1
    report = backtest_report(results, instruments, args.interval, args.train, args.test, now, args.demo)
    out = args.home / "reports" / f"backtest-{now:%Y-%m-%d}{'-demo' if args.demo else ''}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"Rapport opgeslagen in {out}")
    return 0


def cmd_run(args) -> int:
    """Eén paper-ronde: koersen ophalen, elke afdeling laten handelen, dashboard bijwerken."""
    from jplh.paper import paper_round

    config = load_config(_paths(args.home)[0])
    failed = paper_round(config, args.home, args.home / "site", collect=not args.no_collect)
    return 0 if failed < 10 else 1


def cmd_dashboard(args) -> int:
    """Bouwt het HQ-dashboard en opent het in je browser."""
    import functools
    import http.server
    import webbrowser

    from jplh.desks import open_desks
    from jplh.paper import build_demo
    from jplh.site import build_state, write_site

    config = load_config(_paths(args.home)[0])
    if args.demo:
        site = build_demo(config, args.home / "data" / "demo").parent
    else:
        market = Store(_paths(args.home)[1])
        desks = open_desks(config, args.home, market)
        site = write_site(build_state(config, desks, market, args.home), args.home / "site").parent
    print(f"Dashboard staat in {site}")
    if args.no_serve:
        return 0
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    with http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler) as srv:
        url = f"http://127.0.0.1:{args.port}/"
        print(f"Open {url} (stoppen met Ctrl+C)")
        webbrowser.open(url)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


def cmd_status(args) -> int:
    config, store, log_dir = _open(args)
    h = Holding(config, store, args.home, log_dir)
    prices = h.prices()
    equity = h.portfolio.equity_eur(prices)
    print(f"{config.name}  (paper)")
    print(f"Vermogen  €{equity:,.2f}   cash €{h.portfolio.cash_eur:,.2f}   top €{h.meta['peak_equity']:,.2f}")
    if h.meta.get("paused_reason"):
        print(f"PAUZE     {h.meta['paused_reason']}")
    if (args.home / "KILL").exists():
        print("NOODSTOP  aan (jplh unkill om op te heffen)")
    for cls, val in sorted(h.portfolio.class_exposure_eur(prices).items()):
        print(f"  {cls:<7} €{val:,.2f}")
    for sym, pos in h.portfolio.positions.items():
        print(f"  {sym:<9} {pos.quantity:.6g} @ €{pos.avg_price_eur:.6g}  nu €{h.portfolio.value_of(sym, prices):,.2f}")
    counts = store.candle_counts()
    print(f"Koersen in database: {sum(counts.values())} candles voor {len(counts)} instrumenten")
    for ts, kind, payload in store.events(limit=5):
        print(f"  {ts:%Y-%m-%d %H:%M} {kind}: {payload.get('reason', payload)}")
    return 0


def cmd_kill(args) -> int:
    (args.home / "KILL").write_text(f"noodstop {datetime.now(tz=UTC).isoformat()}\n")
    print("NOODSTOP aan: er wordt geen enkele order meer uitgevoerd.")
    return 0


def cmd_unkill(args) -> int:
    (args.home / "KILL").unlink(missing_ok=True)
    print("Noodstop eraf.")
    return 0


def cmd_resume(args) -> int:
    config, store, log_dir = _open(args)
    Holding(config, store, args.home, log_dir).resume()
    print("Pauze opgeheven. De top is opnieuw gezet op het huidige vermogen.")
    return 0


def cmd_selftest(args) -> int:
    """Laat met nep-koersen één signaal per afdeling de hele keten doorlopen. Raakt je echte database niet."""
    home = args.home / "data" / "selftest"
    home.mkdir(parents=True, exist_ok=True)
    db = home / "selftest.sqlite3"
    db.unlink(missing_ok=True)
    config = load_config(_paths(args.home)[0])
    store = Store(db)
    now = datetime.now(tz=UTC)
    demo = Demo({i.symbol: i.asset_class.value for i in config.instruments}, end=now)
    collect_candles(config, store, {"bitvavo": demo, "yahoo": demo}, now=now)
    h = Holding(config, store, base_dir=None, log_dir=home / "logs")
    picks = {}
    for inst in config.instruments:
        picks.setdefault(inst.asset_class.value, inst.symbol)
    for cls, sym in picks.items():
        d = h.submit(Signal(sym, Side.BUY, "selftest", f"test {cls}"), now)
        print(f"{'OK  ' if d.approved else 'NEE '}  {cls:<7} {sym:<9} {d.reason}")
    sym = picks["crypto"]
    d = h.submit(Signal(sym, Side.SELL, "selftest", "test verkoop"), now)
    print(f"{'OK  ' if d.approved else 'NEE '}  verkoop {sym:<9} {d.reason}")
    equity = h.portfolio.equity_eur(h.prices())
    print(f"Vermogen na test €{equity:,.2f} (kosten €{h.portfolio.fees_eur:.2f})")
    store.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jplh", description="JP-libau Holding: trading- en onderzoeksbot (paper)")
    p.add_argument("--version", action="version", version=f"jplh {__version__}")
    p.add_argument("--home", type=Path, default=Path("."), help="map met config/, data/ en logs/")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="controleer of alle databronnen bereikbaar zijn").set_defaults(fn=cmd_doctor)
    c = sub.add_parser("collect", help="haal de nieuwste koersen op voor alle afdelingen")
    c.add_argument("--demo", action="store_true", help="nep-koersen, werkt zonder internet")
    c.add_argument("--limit", type=int, default=200, help="aantal candles per instrument")
    c.add_argument("--interval", choices=["1h", "1d"], default="1h", help="uur- of dagkoersen")
    c.add_argument("--no-radar", action="store_true", help="sla de memecoin-radar over")
    c.set_defaults(fn=cmd_collect)
    b = sub.add_parser("backtest", help="walk-forward-backtest van alle strategieën per afdeling")
    b.add_argument("--interval", choices=["1h", "1d"], default="1d")
    b.add_argument("--train", type=int, default=500, help="perioden om instellingen op te kiezen")
    b.add_argument("--test", type=int, default=125, help="perioden om daarna op te testen")
    b.add_argument("--symbol", action="append", help="alleen dit instrument (mag vaker)")
    b.add_argument("--demo", action="store_true", help="nep-koersen, werkt zonder internet")
    b.add_argument("--bars", type=int, default=1200, help="aantal nep-koersen bij --demo")
    b.set_defaults(fn=cmd_backtest)
    r = sub.add_parser("run", help="één paper-ronde voor alle afdelingen + dashboard bijwerken")
    r.add_argument("--no-collect", action="store_true", help="geen nieuwe koersen ophalen")
    r.set_defaults(fn=cmd_run)
    d = sub.add_parser("dashboard", help="HQ-dashboard bouwen en openen in je browser")
    d.add_argument("--demo", action="store_true", help="met een nep-wereld, werkt zonder internet")
    d.add_argument("--port", type=int, default=8000)
    d.add_argument("--no-serve", action="store_true", help="alleen bouwen, niet openen")
    d.set_defaults(fn=cmd_dashboard)
    sub.add_parser("status", help="vermogen, posities en laatste gebeurtenissen").set_defaults(fn=cmd_status)
    sub.add_parser("kill", help="noodstop: geen enkele order meer").set_defaults(fn=cmd_kill)
    sub.add_parser("unkill", help="noodstop opheffen").set_defaults(fn=cmd_unkill)
    sub.add_parser("resume", help="pauze na een drawdown opheffen").set_defaults(fn=cmd_resume)
    sub.add_parser("selftest", help="hele keten testen met nep-koersen").set_defaults(fn=cmd_selftest)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except ConfigError as exc:
        print(f"Config-fout: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

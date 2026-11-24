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
    if config.shadow:   # schaduw-afdelingen: alleen ter info, blokkeert nooit
        sources = {"bitvavo": Bitvavo(), "yahoo": Yahoo()}
        for x in config.shadow:
            try:
                cs = sources[x.source].candles(x.symbol, "1d", 5)
                print(f"OK    schaduw {x.symbol} ({x.name}): {len(cs)} dagkoersen, laatste {cs[-1].close:.2f}")
            except (DataError, KeyError, ValueError, IndexError) as exc:
                print(f"LET OP schaduw {x.symbol}: {exc}")
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
    if args.desks:
        from jplh.deskbacktest import allocation, allocation_lines, compare, compare_report
        from jplh.desks import ALL_CANDIDATES
        res = compare(config, candles_of, ALL_CANDIDATES)
        report = compare_report(res, now, args.demo, allocation(res, config.desks))
        longer = allocation(res, config.desks, skip=("meme",))
        if longer:
            report += "\n".join(allocation_lines(longer, " zonder memecoins")) + "\n"
        from jplh.riskdirector import risk_lines
        report += "\n".join(risk_lines(res, config.desks)) + "\n"
        out = args.home / "reports" / f"afdelingen-{now:%Y-%m-%d}{'-demo' if args.demo else ''}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(report)
        print(f"Rapport opgeslagen in {out}")
        return 0
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
    from jplh.site import build_overmind, build_state, write_site

    config = load_config(_paths(args.home)[0])
    if args.demo:
        site = build_demo(config, args.home / "data" / "demo").parent
    else:
        market = Store(_paths(args.home)[1])
        desks = open_desks(config, args.home, market)
        state = build_state(config, desks, market, args.home)
        site = write_site(state, args.home / "site",
                          build_overmind(state, config, desks, market, args.home)).parent
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


def cmd_jarvis(args) -> int:
    import os

    from jplh.commands import listen
    from jplh.notify import Telegram
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        print("Geen TELEGRAM_TOKEN: Jarvis luistert niet.")
        return 0
    config = load_config(_paths(args.home)[0])
    try:
        listen(config, args.home, Telegram(token))
    except RuntimeError as exc:
        print(f"Jarvis: {exc}")
        return 1
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


def cmd_publish_check(args) -> int:
    """Poortwachter voor GitHub Pages: alleen de allowlist, geen geheimen, geen lokale paden."""
    from jplh.security import check_site, known_secrets
    site = args.site or args.home / "site"
    found = check_site(site, known_secrets(args.home))
    for f in found:
        print(f"NIET PUBLICEREN  {f}")
    print(f"Publieke export: {'GEBLOKKEERD' if found else 'veilig'} ({site.name}, {len(found)} bevinding(en))")
    return 1 if found else 0


def cmd_secret_scan(args) -> int:
    """Zoekt patronen van echte geheimen (tokens, sleutels) in bestanden. Toont nooit de waarde."""
    from jplh.security import known_secrets, scan_paths
    found = scan_paths([Path(p) for p in args.paths], known_secrets(None))
    for f in found:
        print(f"GEHEIM?  {f}")
    print(f"Geheimenscan: {len(args.paths)} bestand(en), {len(found)} bevinding(en)")
    return 1 if found else 0


def cmd_state_check(args) -> int:
    """Vingerafdruk van de stand (hashes, integriteit, vermogen, pauzes). Alleen-lezen."""
    import json

    from jplh.statecheck import compare, fingerprint
    fp = fingerprint(args.home)
    if args.out:
        args.out.write_text(json.dumps(fp, indent=1, sort_keys=True))
    if args.against:
        other = json.loads(args.against.read_text())
        diff = compare(other, fp)
        for d in diff:
            print(f"VERSCHIL  {d}")
        print(f"Vergelijking: {'IDENTIEK' if not diff else 'NIET GELIJK'}")
        return 1 if diff else 0
    print(json.dumps({k: v for k, v in fp.items() if k != "integrity"}, indent=1, sort_keys=True))
    return 0 if fp["integrity_ok"] and fp["has_data"] else 1


def cmd_config_check(args) -> int:
    """Welke beveiligingsinstellingen staan aan? Toont alleen ja/nee, nooit een waarde."""
    import os

    from jplh.notify import chat_status
    st = Store(_paths(args.home)[1]) if _paths(args.home)[1].exists() else None
    memory = st.get_state("telegram", {}) if st else {}
    rows = {
        "TELEGRAM_TOKEN aanwezig": bool(os.environ.get("TELEGRAM_TOKEN")),
        "TELEGRAM_CHAT_ID aanwezig": bool(os.environ.get("TELEGRAM_CHAT_ID")),
        "chat-id": chat_status(memory),
        "chat-id nog in de stand": "chat" in memory,
        "STATE_REPO ingesteld": bool(os.environ.get("STATE_REPO")),
        "STATE_TOKEN aanwezig": bool(os.environ.get("STATE_TOKEN")),
    }
    for k, v in rows.items():
        print(f"{k:<28} {('ja' if v else 'nee') if isinstance(v, bool) else v}")
    return 0


def cmd_telegram_check(args) -> int:
    """9.3: is de bottoken geldig en staat er geen webhook? Toont nooit de token."""
    import os

    from jplh.health import HEALTHY, check_telegram
    c = check_telegram(os.environ.get("TELEGRAM_TOKEN"))
    print(f"Telegram: {c.status}  {c.detail}")
    for k, v in c.facts.items():
        print(f"  {k:<22} {v}")
    return 0 if c.status == HEALTHY else 1


def cmd_access_check(args) -> int:
    """9.3: waarom wel of geen toegang tot de privé-repo? Lezen en schrijven (dry-run), niets wordt geschreven."""
    import os

    from jplh.health import check_repo_access
    r = check_repo_access(args.repo, os.environ.get("STATE_TOKEN"))
    for k, v in r.items():
        print(f"{k:<12} {v}")
    return 0 if r["oorzaak"] in ("OK", "LEEG_OK") else 1


def cmd_health(args) -> int:
    """9.3: gezondheid van alle onderdelen (HEALTHY/DEGRADED/OFFLINE/CRITICAL). Alleen lezen."""
    import json
    import os

    from jplh import health as H
    now = datetime.now(tz=UTC)
    gh = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    hdr = {"Authorization": f"Bearer {gh}", "Accept": "application/vnd.github+json"} if gh else {}
    tg = H.check_telegram(os.environ.get("TELEGRAM_TOKEN"))
    comps = [tg]
    if repo and gh:
        code, _ = H.http(f"https://api.github.com/repos/{repo}", hdr)
        comps.append(H.check_github_auth(code))
        dcode, deps = H.http(f"https://api.github.com/repos/{repo}/deployments?environment=github-pages&per_page=1", hdr)
        state = age = None
        if dcode == 200 and isinstance(deps, list) and deps:
            scode, sts = H.http(deps[0]["statuses_url"] + "?per_page=1", hdr)
            if scode == 200 and isinstance(sts, list) and sts:
                state = sts[0].get("state")
                created = datetime.fromisoformat(sts[0]["created_at"].replace("Z", "+00:00"))
                age = (now - created).total_seconds() / 60
        comps.append(H.check_pages(state, age))
    state_repo = os.environ.get("STATE_REPO")
    access = H.check_repo_access(state_repo, os.environ.get("STATE_TOKEN")) if state_repo else None
    comps.append(H.check_state_storage(state_repo, access))
    comps.append(H.check_scheduler(args.last_round, now))
    comps.append(H.check_database(args.home))
    comps.append(H.emergency_channels(tg, Path(".github/workflows/noodstop.yml").is_file()))
    comps.append(H.check_ai_gateway())
    print(H.report(comps, now))
    if args.out:
        args.out.write_text(json.dumps({"at": now.isoformat(), "overall": H.overall(comps),
                                        "components": [{"name": c.name, "status": c.status, "detail": c.detail,
                                                        "counts": c.counts} for c in comps]}, indent=1))
    return 1 if args.strict and H.overall(comps) == H.CRITICAL else 0


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
    b.add_argument("--desks", action="store_true", help="hele afdelingen naspelen: verbeteringen tegen de huidige versie")
    b.set_defaults(fn=cmd_backtest)
    r = sub.add_parser("run", help="één paper-ronde voor alle afdelingen + dashboard bijwerken")
    r.add_argument("--no-collect", action="store_true", help="geen nieuwe koersen ophalen")
    r.set_defaults(fn=cmd_run)
    d = sub.add_parser("dashboard", help="HQ-dashboard bouwen en openen in je browser")
    d.add_argument("--demo", action="store_true", help="met een nep-wereld, werkt zonder internet")
    d.add_argument("--port", type=int, default=8000)
    d.add_argument("--no-serve", action="store_true", help="alleen bouwen, niet openen")
    d.set_defaults(fn=cmd_dashboard)
    sub.add_parser("jarvis", help="Telegram-commando's van Phil beantwoorden").set_defaults(fn=cmd_jarvis)
    sub.add_parser("status", help="vermogen, posities en laatste gebeurtenissen").set_defaults(fn=cmd_status)
    sub.add_parser("kill", help="noodstop: geen enkele order meer").set_defaults(fn=cmd_kill)
    sub.add_parser("unkill", help="noodstop opheffen").set_defaults(fn=cmd_unkill)
    sub.add_parser("resume", help="pauze na een drawdown opheffen").set_defaults(fn=cmd_resume)
    sub.add_parser("selftest", help="hele keten testen met nep-koersen").set_defaults(fn=cmd_selftest)
    pc = sub.add_parser("publish-check", help="controleer of het dashboard veilig publiek kan")
    pc.add_argument("--site", type=Path, default=None, help="map met de site (standaard <home>/site)")
    pc.set_defaults(fn=cmd_publish_check)
    sc = sub.add_parser("state-check", help="vingerafdruk van de stand: hashes, integriteit, vermogen")
    sc.add_argument("--out", type=Path, help="vingerafdruk als JSON bewaren")
    sc.add_argument("--against", type=Path, help="vergelijk met een eerder bewaarde vingerafdruk")
    sc.set_defaults(fn=cmd_state_check)
    sub.add_parser("config-check", help="welke beveiligingsinstellingen staan aan (alleen ja/nee)").set_defaults(
        fn=cmd_config_check)
    ss = sub.add_parser("secret-scan", help="zoek naar tokens en sleutels in bestanden")
    ss.add_argument("paths", nargs="*", help="bestanden om te scannen")
    ss.set_defaults(fn=cmd_secret_scan)
    sub.add_parser("telegram-check", help="is de bottoken geldig, staat er een webhook (nooit de token)").set_defaults(
        fn=cmd_telegram_check)
    ac = sub.add_parser("access-check", help="toegang tot de privé-repo: oorzaak per toestand")
    ac.add_argument("--repo", required=True, help="eigenaar/naam")
    ac.set_defaults(fn=cmd_access_check)
    he = sub.add_parser("health", help="gezondheid per onderdeel: HEALTHY/DEGRADED/OFFLINE/CRITICAL")
    he.add_argument("--last-round", type=float, help="tijdstip (epoch) van de laatste paper-ronde")
    he.add_argument("--out", type=Path, help="uitkomst als JSON bewaren")
    he.add_argument("--strict", action="store_true", help="exitcode 1 bij CRITICAL")
    he.set_defaults(fn=cmd_health)
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

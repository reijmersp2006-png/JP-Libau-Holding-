"""Onderzoek vanaf de opdrachtregel: ``nexus-research <opdracht>``.

    baseline   bewaar de uitkomsten van alle lab-strategieën (versie 1) als onveranderlijk ijkpunt
    audit      ontleed één strategie op één instrument (Markdown + JSON)
    fetch      haal geschiedenis op voor een tijdschaal (naar de onderzoeksdatabase)
    discover   draai de Alpha Research Engine (zie ``nexus.alpha``)

Omgeving: ``NEXUS_HOLDING_HOME`` (koersen van de holding), ``NEXUS_RESEARCH_DB`` (eigen opslag).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from jplh.config import load_config

from nexus import audit, datasets, lab

OUT = Path(os.environ.get("NEXUS_RESEARCH_OUT", Path(__file__).resolve().parents[2] / "research"))


def _data(args) -> datasets.ResearchData:
    cfg = load_config(os.environ.get("NEXUS_HOLDING_CONFIG") or None)
    home = os.environ.get("NEXUS_HOLDING_HOME")
    rdb = os.environ.get("NEXUS_RESEARCH_DB")
    return datasets.ResearchData(cfg, Path(home) / "data" / "holding.sqlite3" if home else None,
                                 Path(rdb) if rdb else None)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    print(f"geschreven: {path}")


def cmd_baseline(args) -> int:
    data = _data(args)
    target = OUT / "baselines" / f"{args.label}.json"
    if target.exists() and not args.force:
        print(f"{target} bestaat al; een ijkpunt wordt niet overschreven", file=sys.stderr)
        return 1
    rows = []
    for inst in data.config.instruments:
        raw = data.raw(inst.symbol, "1d")
        cost = data.config.costs[inst.asset_class.value]
        for sp in lab.SPECS:
            try:
                r = lab.run_backtest(sp, inst, raw, cost)
            except ValueError as e:
                rows.append({"symbol": inst.symbol, "strategy": sp.key, "version": sp.version, "skipped": str(e)})
                continue
            rows.append({"symbol": inst.symbol, "strategy": sp.key, "version": sp.version,
                         "fingerprint": audit.fingerprint(raw), "data": r["data"], "assumptions": r["assumptions"],
                         "out_of_sample": r["out_of_sample"], "benchmark_oos": r["benchmark"]["out_of_sample"],
                         "full": r["full"], "benchmark_full": r["benchmark"]["full"],
                         "passes": r["passes"], "verdict": r["verdict"]})
    doc = {"label": args.label, "created_at": datetime.now(tz=UTC).isoformat(),
           "method": "nexus.lab.run_backtest v1 (oos = laatste 30% na opwarmtijd per strategie)",
           "rows": rows}
    _write(target, json.dumps(doc, indent=1, default=str))
    passed = [r for r in rows if r.get("passes")]
    print(f"{len(rows)} combinaties, {len(passed)} geslaagd")
    return 0


def cmd_audit(args) -> int:
    data = _data(args)
    inst = next(i for i in datasets.universe(data.config) if i.symbol == args.symbol)
    sp = lab.spec(args.strategy, args.version)
    a = audit.audit_backtest(sp, inst, data.raw(inst.symbol, "1d"), data.config.costs[inst.asset_class.value],
                             oos_start=args.oos_start)
    stem = f"{inst.symbol}-{sp.key}-v{sp.version}" + (f"-oos{args.oos_start}" if args.oos_start else "")
    _write(OUT / "audits" / f"{stem}.json", json.dumps(a, indent=1, default=str))
    _write(OUT / "audits" / f"{stem}.md", audit.markdown(a))
    return 0


def cmd_fetch(args) -> int:
    data = _data(args)
    insts = {i.symbol: i for i in datasets.universe(data.config)}
    bad = 0
    for sym in args.symbols:
        inst = insts[sym]
        try:
            candles = datasets.fetch_history(inst, args.interval, args.bars)
        except Exception as e:  # noqa: BLE001 - bronfout melden, niets vervangen
            print(f"{sym} {args.interval}: NIET BESCHIKBAAR ({e})")
            bad += 1
            continue
        n = data.save(sym, args.interval, candles, inst.source)
        print(f"{sym} {args.interval}: {len(candles)} candles ({n} nieuw)")
    return 1 if bad else 0


def cmd_discover(args) -> int:
    from nexus import alpha
    data = _data(args)
    report = alpha.discover(data, interval=args.interval, symbols=args.symbols or None)
    stem = f"discovery-{args.interval}-{datetime.now(tz=UTC):%Y%m%d}"
    _write(OUT / "discovery" / f"{stem}.json", json.dumps(report, indent=1, default=str))
    _write(OUT / "discovery" / f"{stem}.md", alpha.markdown(report))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="nexus-research")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("baseline")
    b.add_argument("--label", default=f"lab-v1-{datetime.now(tz=UTC):%Y-%m-%d}")
    b.add_argument("--force", action="store_true")
    a = sub.add_parser("audit")
    a.add_argument("symbol")
    a.add_argument("strategy")
    a.add_argument("--version", type=int, default=None)
    a.add_argument("--oos-start", default=None)
    f = sub.add_parser("fetch")
    f.add_argument("--interval", choices=list(datasets.STEP), required=True)
    f.add_argument("--bars", type=int, default=5000)
    f.add_argument("symbols", nargs="+")
    d = sub.add_parser("discover")
    d.add_argument("--interval", choices=list(datasets.STEP), default="1d")
    d.add_argument("symbols", nargs="*")
    args = p.parse_args(argv)
    return {"baseline": cmd_baseline, "audit": cmd_audit, "fetch": cmd_fetch, "discover": cmd_discover}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())

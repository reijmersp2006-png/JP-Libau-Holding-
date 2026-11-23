"""``nexus-ops``: de read-only koppeling tussen JP-Libau Holding en NEXUS vanaf de opdrachtregel.

    nexus-ops snapshot --home ../paper-data            # jplh.snapshot/v1 (alleen-lezen) naar stdout
    nexus-ops research --home ../paper-data --scope crypto --export out/records.json
    nexus-ops show ops-20261123...                     # één record terughalen

Schrijft alleen naar de NEXUS-database (``NEXUS_DATABASE_URL``) en naar een expliciet ``--export``-pad,
nooit naar de holding-map. Plaatst geen orders en roept geen AI-model aan.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from nexus import operations
from nexus.db import Database


def _src(a) -> dict:
    return {"path": Path(a.snapshot) if a.snapshot else None, "home": Path(a.home) if a.home else None}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="nexus-ops", description="JP-Libau Holding → NEXUS, alleen lezen")
    ap.add_argument("--db", default=os.environ.get("NEXUS_DATABASE_URL", "sqlite:///./nexus.db"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("snapshot", "research"):
        p = sub.add_parser(name)
        p.add_argument("--home", help="holding-map (bijv. een kopie van de paper-data-branch)")
        p.add_argument("--snapshot", help="pad naar een snapshot.json van het dashboard")
        if name == "research":
            p.add_argument("--scope", default="holding", choices=operations.SCOPES)
            p.add_argument("--question", default="")
            p.add_argument("--export", help="schrijf nexus.records/v1 naar dit pad (voor Jarvis /onderzoek)")
    s = sub.add_parser("show")
    s.add_argument("trace")
    a = ap.parse_args(argv)

    if a.cmd == "show":
        db = Database(a.db)
        try:
            print(json.dumps(operations.get(db, a.trace), ensure_ascii=False, indent=2, default=str))
        except KeyError:
            print(f"onbekend record {a.trace}", file=sys.stderr)
            return 1
        return 0
    try:
        snap = operations.load(**_src(a))
    except operations.SnapshotError as e:
        print(f"BLOCKED: {e}", file=sys.stderr)
        return 2
    if a.cmd == "snapshot":
        print(json.dumps(snap, ensure_ascii=False, indent=2, default=str))
        return 0
    db = Database(a.db)
    rec = operations.run(db, snap, scope=a.scope, question=a.question, requested_by="cli",
                         max_age_hours=operations.max_age_hours())
    print(json.dumps({k: rec[k] for k in ("trace_id", "subject", "status", "generator", "data_label", "data_asof",
                                          "ai_status", "recommendation", "summary", "snapshot_sha256")},
                     ensure_ascii=False, indent=2))
    for f in rec["findings"]:
        print(f"  [{f['severity']}] {f['text']}  ← {', '.join(f['evidence']) or 'geen feit-id'}")
    if a.export:
        out = Path(a.export)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(operations.export(db), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"export: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

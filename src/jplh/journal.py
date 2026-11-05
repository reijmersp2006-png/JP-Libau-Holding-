"""Logboek: elke beslissing met reden en alle risico-checks, in de database en als JSONL per dag."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from jplh.models import Decision, Fill
from jplh.store import Store


class Journal:
    def __init__(self, store: Store, log_dir: Path | None = Path("logs")) -> None:
        self.store = store
        self.log_dir = log_dir

    def write(self, ts: datetime, kind: str, payload: dict) -> None:
        self.store.add_event(ts, kind, payload)
        if self.log_dir is not None:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            line = json.dumps({"ts": ts.isoformat(), "kind": kind, **payload}, ensure_ascii=False, default=str)
            with (self.log_dir / f"journal-{ts:%Y-%m-%d}.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def decision(self, ts: datetime, d: Decision) -> None:
        self.write(ts, "decision", {
            "instrument": d.signal.instrument, "side": d.signal.side.value, "strategy": d.signal.strategy,
            "signal_reason": d.signal.reason, "approved": d.approved, "reason": d.reason,
            "size_eur": round(d.size_eur, 2), "checks": [asdict(c) for c in d.checks],
        })

    def fill(self, f: Fill) -> None:
        self.store.add_fill(f)
        self.write(f.ts, "fill", {"instrument": f.instrument, "side": f.side.value, "quantity": f.quantity,
                                  "price_eur": f.price_eur, "fee_eur": round(f.fee_eur, 4),
                                  "strategy": f.strategy})

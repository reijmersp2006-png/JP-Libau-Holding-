"""Bescherming van de holdout: manifest, registratie vooraf, besmetting en een prospectieve periode.

Regels:
- Voor elke holdout-blik wordt eerst een registratie geschreven met het manifest (hash van de koersen)
  en de bevroren instelling. Dezelfde kandidaat met dezelfde instelling mag een holdout maar één keer zien.
- Een holdout die al invloed had op de keuze van een strategie is *besmet*
  (``research/holdout/contamination.json``). Dan telt alleen data ná ``prospective_start``: echte nieuwe
  dagen die nog niemand gezien had toen de strategie bevroren werd.
- Te weinig prospectieve data → ``awaiting_prospective``: geen oordeel, geen promotie.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from jplh.models import Candle

CONTAMINATION_FILE = Path(__file__).resolve().parents[2] / "research" / "holdout" / "contamination.json"
MIN_PROSPECTIVE_DAYS = 63          # ongeveer drie maanden handelsdagen


def manifest(candles: list[Candle], start: int, end: int) -> dict:
    """Onveranderlijke vingerafdruk van een stuk dataset (tijd + OHLCV)."""
    h = hashlib.sha256()
    for c in candles[start:end]:
        h.update(f"{c.ts.isoformat()}|{c.open:.10g}|{c.high:.10g}|{c.low:.10g}|{c.close:.10g}|{c.volume:.10g}\n".encode())
    return {"sha256": h.hexdigest(), "bars": max(0, end - start),
            "first": candles[start].ts.isoformat() if end > start else None,
            "last": candles[end - 1].ts.isoformat() if end > start else None}


def contamination(dataset_key: str, holdout_start: str, path: Path | None = None) -> dict | None:
    """Besmettingsregel die op deze dataset en holdout van toepassing is, of None."""
    p = path or CONTAMINATION_FILE
    if not p.exists():
        return None
    for e in json.loads(p.read_text()).get("entries", []):
        if fnmatch.fnmatch(dataset_key, e["datasets"]) and holdout_start[:10] <= e["seen_until"]:
            return e
    return None


def min_prospective_bars(ppy: int) -> int:
    return max(MIN_PROSPECTIVE_DAYS, int(round(ppy * MIN_PROSPECTIVE_DAYS / 252)))


def window(candles: list[Candle], dev_end: int, rule: dict | None, ppy: int) -> dict:
    """Welke bars mogen als onafhankelijke toets gelden."""
    n = len(candles)
    if rule is None:
        return {"status": "clean", "start": dev_end, "end": n, "bars": n - dev_end}
    ps = datetime.fromisoformat(rule["prospective_start"]).replace(tzinfo=UTC)
    start = next((i for i, c in enumerate(candles) if c.ts >= ps), n)
    need = min_prospective_bars(ppy)
    have = n - start
    return {"status": "contaminated", "start": start, "end": n, "bars": have, "needed": need,
            "ready": have >= need, "prospective_start": rule["prospective_start"], "reason": rule["reason"]}


def already_evaluated(entries: list[dict], dataset_key: str, window_start: str, candidate: str, params: dict) -> dict | None:
    key = json.dumps(params, sort_keys=True)
    for e in entries:
        if (e.get("dataset") == dataset_key and e.get("holdout_start") == window_start and e.get("candidate") == candidate
                and json.dumps(e.get("params"), sort_keys=True) == key):
            return e
    return None

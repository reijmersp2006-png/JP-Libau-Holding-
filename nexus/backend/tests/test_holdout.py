"""Holdout-bescherming: manifest, besmetting, prospectieve periode, één blik per kandidaat."""

import json
from datetime import UTC, datetime, timedelta

from jplh.config import CostModel
from jplh.models import Candle

from nexus import alpha
from nexus import holdout as hg
from test_lab import series

ZERO = (CostModel(0, 0, 0), 0.0)


def _rules(tmp_path, seen_until, prospective_start):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"entries": [{"datasets": "*@1d", "seen_until": seen_until, "reason": "test",
                                          "prospective_start": prospective_start}]}))
    return p


def test_manifest_changes_when_data_changes():
    c = series(100)
    a = hg.manifest(c, 50, 100)
    c2 = c[:70] + [Candle(c[70].ts, c[70].open, c[70].high, c[70].low, c[70].close * 1.001, c[70].volume)] + c[71:]
    assert a["bars"] == 50 and a["sha256"] != hg.manifest(c2, 50, 100)["sha256"]
    assert a == hg.manifest(c, 50, 100)


def test_repository_marks_daily_holdouts_before_audit_as_contaminated():
    assert hg.contamination("IWDA.AS@1d", "2025-09-09T00:00:00+00:00") is not None
    assert hg.contamination("BTC-EUR@1h", "2025-09-09T00:00:00+00:00") is None       # nooit bekeken
    assert hg.contamination("IWDA.AS@1d", "2026-12-01T00:00:00+00:00") is None       # na de besmetting


def test_prospective_window_counts_only_new_bars(tmp_path):
    c = series(900)
    start = c[850].ts.date().isoformat()
    rule = hg.contamination("X@1d", "2023-01-01", _rules(tmp_path, "2030-01-01", start))
    w = hg.window(c, 700, rule, 252)
    assert w["status"] == "contaminated" and w["bars"] == 50 and not w["ready"]
    assert hg.window(c, 700, None, 252) == {"status": "clean", "start": 700, "end": 900, "bars": 200}


def _candidate():
    fam = alpha.family("vol_target")
    c = series(900)
    panel = {"IWDA.AS": c}
    costs = {"IWDA.AS": ZERO}
    res = alpha.evaluate_dataset(fam, panel, "IWDA.AS", costs, 252, "1d", 1000.0, len(fam.combos()))
    return fam, panel, costs, res


def test_contaminated_holdout_is_not_looked_at(tmp_path, monkeypatch):
    monkeypatch.setattr(hg, "CONTAMINATION_FILE", _rules(tmp_path, "2030-01-01", "2030-01-02"))
    fam, panel, costs, res = _candidate()
    led = alpha.HoldoutLedger(tmp_path / "l.jsonl")
    h = alpha.evaluate_holdout(res, fam, panel, costs, 252, 1000.0, led, "r1")
    assert h["status"] == "awaiting_prospective" and h["passed"] is False and h["metrics"] is None
    assert led.entries() == []


def test_clean_holdout_is_registered_once_per_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(hg, "CONTAMINATION_FILE", tmp_path / "geen.json")
    fam, panel, costs, res = _candidate()
    led = alpha.HoldoutLedger(tmp_path / "l.jsonl")
    h = alpha.evaluate_holdout(res, fam, panel, costs, 252, 1000.0, led, "r1")
    assert h["status"] == "evaluated" and h["holdout_uses"] == 1
    e = led.entries()[0]
    assert e["manifest"]["sha256"] == h["manifest"]["sha256"] and e["candidate"] == "vol_target"
    again = alpha.evaluate_holdout(res, fam, panel, costs, 252, 1000.0, led, "r2")
    assert again["status"] == "already_evaluated" and len(led.entries()) == 1


def test_enough_prospective_data_opens_only_the_new_window(tmp_path, monkeypatch):
    c = series(900)
    ps = (c[800].ts + timedelta(hours=1)).date().isoformat()
    monkeypatch.setattr(hg, "CONTAMINATION_FILE", _rules(tmp_path, "2030-01-01", ps))
    fam, panel, costs, res = _candidate()
    led = alpha.HoldoutLedger(tmp_path / "l.jsonl")
    h = alpha.evaluate_holdout(res, fam, panel, costs, 252, 1000.0, led, "r1")
    assert h["status"] == "evaluated" and h["manifest"]["first"] >= datetime.fromisoformat(ps).replace(tzinfo=UTC).isoformat()
    assert h["manifest"]["bars"] < 900 - res["_split"].dev_end

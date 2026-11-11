import random
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from jplh.academy import luck, maybe_study, score_live, signal_note, write_forecasts
from jplh.config import load_config
from jplh.desks import ALL_CANDIDATES
from jplh.models import Candle
from jplh.store import Store

T0 = datetime(2026, 1, 1, 22, tzinfo=UTC)


def _market(days: int, step: float = 1.0):
    """Eén aandeel dat elke dag ``step`` procent stijgt."""
    market = Store(":memory:")
    p, candles = 100.0, []
    for i in range(days):
        candles.append(Candle(T0 + timedelta(days=i), p, p, p, p))
        p *= 1 + step / 100
    market.save_observed("ASML.AS", "1d", candles, "test", timedelta(days=1))   # pas bekend na de dag zelf
    return market


def _desks(config):
    inst = config.instrument("ASML.AS")
    return {"stocks": SimpleNamespace(instruments=[inst], selection=lambda: {"ASML.AS": "koop_en_houd"})}


def test_forecasts_are_written_once_and_only_scored_after_the_horizon():
    config = load_config(None)
    market = _market(400)
    desks = _desks(config)
    now = T0 + timedelta(days=300, hours=2)
    known = market.candles("ASML.AS", "1d", known_at=now)
    assert len(known) == 300
    assert write_forecasts(desks, market, ALL_CANDIDATES, now) == 1
    assert write_forecasts(desks, market, ALL_CANDIDATES, now + timedelta(hours=1)) == 0     # zelfde dag: niet opnieuw
    early = score_live(market, config, now + timedelta(days=3))
    assert early["horizons"]["7"]["all_live"] is None                                       # nog geen week: geen oordeel
    later = score_live(market, config, now + timedelta(days=8))
    s = later["horizons"]["7"]["all_live"]
    assert s["n"] == 1 and s["hit"] == 1.0 and s["verdict"] == "nog toeval"                  # één meting is geen bewijs


def test_luck_is_small_for_a_real_edge_and_large_for_noise():
    rng = random.Random(3)
    live = [rng.gauss(0, 0.01) for _ in range(300)]
    better = [x + 0.003 for x in live]                      # elke dag een stukje beter
    noisy = [x + rng.gauss(0, 0.01) for x in live]          # alleen anders, niet beter
    assert luck(better, live) < 0.05
    assert luck(noisy, live) > 0.10
    assert luck(better[:10], live[:10]) is None             # te weinig dagen om te toetsen


def test_study_runs_once_a_day_and_explains_signals_with_the_base_rate():
    config = load_config(None)
    market = _market(400)
    desks = _desks(config)
    now = T0 + timedelta(days=399, hours=2)
    a = maybe_study(desks, market, config, ALL_CANDIDATES, now, log=lambda *_: None)
    assert a and maybe_study(desks, market, config, ALL_CANDIDATES, now + timedelta(hours=1), log=lambda *_: None) == a
    label = next(s.label for s in ALL_CANDIDATES if s.label.startswith("trend"))
    note = signal_note(a, "ASML.AS", label, 1)
    assert "Academie" in note and "gewoon" in note
    assert signal_note(a, "ASML.AS", "koop_en_houd", 1) == ""   # vasthouden vergelijken met zichzelf zegt niets
    lessons = market.events(kind="lesson")
    assert lessons and "Academie" in lessons[0][2]["text"]

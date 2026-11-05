from datetime import timedelta

from conftest import NOW, flat

from jplh.models import Candle


def test_first_observation_wins(store):
    store.save_candles("BTC-EUR", "1h", flat(100.0), "a", NOW)
    changed = [Candle(c.ts, 1, 1, 1, 999.0) for c in flat(100.0)]
    assert store.save_candles("BTC-EUR", "1h", changed, "b", NOW + timedelta(hours=1)) == 0
    assert store.latest_close("BTC-EUR")[1] == 100.0


def test_known_at_hides_future_fetches(store):
    store.save_candles("BTC-EUR", "1h", flat(100.0, end=NOW), "a", NOW)
    later = NOW + timedelta(hours=3)
    store.save_candles("BTC-EUR", "1h", flat(110.0, n=2, end=later), "a", later)
    assert len(store.candles("BTC-EUR", known_at=NOW)) == 5
    assert len(store.candles("BTC-EUR")) == 7


def test_state_roundtrip(store):
    store.set_state("x", {"a": 1})
    assert store.get_state("x") == {"a": 1}
    assert store.get_state("missing", 5) == 5

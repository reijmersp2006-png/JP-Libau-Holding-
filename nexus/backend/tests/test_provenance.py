from datetime import UTC, datetime, timedelta

from nexus.provenance import DataLabel, labeled, market_label

NOW = datetime(2026, 11, 12, 20, tzinfo=UTC)
MAX = timedelta(hours=3)


def test_labels():
    assert market_label(None, NOW, MAX) is DataLabel.UNAVAILABLE
    assert market_label(NOW - timedelta(hours=1), NOW, MAX) is DataLabel.DELAYED
    assert market_label(NOW - timedelta(hours=5), NOW, MAX) is DataLabel.HISTORICAL
    assert market_label(NOW - timedelta(hours=1), NOW, MAX, demo=True) is DataLabel.SIMULATED
    # Candles zijn nooit LIVE; alleen een echte stream binnen een minuut.
    assert market_label(NOW - timedelta(seconds=10), NOW, MAX) is DataLabel.DELAYED
    assert market_label(NOW - timedelta(seconds=10), NOW, MAX, streaming=True) is DataLabel.LIVE


def test_unavailable_never_carries_a_number():
    assert labeled(123.0, DataLabel.UNAVAILABLE)["value"] is None
    assert labeled(123.0, DataLabel.DELAYED)["value"] == 123.0

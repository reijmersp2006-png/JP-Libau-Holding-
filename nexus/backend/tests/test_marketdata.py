from datetime import UTC, datetime, timedelta

from jplh.config import load_config
from jplh.models import Candle

from nexus.marketdata import MarketData, assess, session

NOW = datetime(2026, 11, 12, 15, 0, tzinfo=UTC)   # donderdag


def bars(n=10, step=timedelta(hours=1), end=NOW, gap_at=None, bad_at=None):
    out = []
    for i in range(n):
        if i == gap_at:
            continue
        ts = end - (n - i) * step
        o, h, l, c = 100.0, 101.0, 99.0, 100.5
        if i == bad_at:
            h = 90.0                                  # hoog onder open/slot: onmogelijk
        out.append(Candle(ts, o, h, l, c, 5.0))
    return out


def test_sessions():
    assert session("BTC-EUR", "crypto", NOW) == "24/7"
    assert session("ASML.AS", "stocks", NOW) == "open"                       # 16:00 Amsterdam
    assert session("ASML.AS", "stocks", NOW.replace(hour=20)) == "closed"
    assert session("AAPL", "stocks", NOW) == "open"                          # 10:00 New York
    assert session("AAPL", "stocks", NOW.replace(hour=22)) == "closed"
    sat = NOW + timedelta(days=2)
    assert session("EURUSD=X", "fx", sat) == "closed" and session("EURUSD=X", "fx", NOW) == "open"
    assert session("GC=F", "metals", sat) == "closed"


def test_quality_checks():
    max_age = timedelta(hours=3)
    assert assess(bars(), "1h", NOW, max_age, True) == ("ok", [])
    assert assess([], "1h", NOW, max_age, True)[0] == "missing"
    assert assess(bars(gap_at=4), "1h", NOW, max_age, True)[0] == "gaps"
    assert assess(bars(bad_at=3), "1h", NOW, max_age, True)[0] == "invalid"
    assert assess(bars(end=NOW - timedelta(hours=10)), "1h", NOW, max_age, True)[0] == "stale"


class Broken:
    def candles(self, *a):
        raise ConnectionError("bron plat")


class Good:
    def candles(self, symbol, interval, limit):
        return bars()


def test_failing_provider_gives_unavailable_and_no_numbers():
    s = MarketData(load_config(), {"bitvavo": Broken()}).series("BTC-EUR", now=NOW)
    assert s.label == "UNAVAILABLE" and s.bars == [] and s.last_close is None and "bron plat" in s.error


def test_unconnected_provider_is_not_substituted():
    s = MarketData(load_config(), {"bitvavo": Good()}).series("AAPL", now=NOW)   # yahoo niet gekoppeld
    assert s.label == "UNAVAILABLE" and s.bars == [] and "niet gekoppeld" in s.error


def test_good_series_has_full_metadata():
    s = MarketData(load_config(), {"bitvavo": Good()}).series("BTC-EUR", now=NOW)
    assert (s.source, s.currency, s.session, s.quality) == ("bitvavo", "EUR", "24/7", "ok")
    assert s.label == "DELAYED" and s.last_close == 100.5 and len(s.bars) == 10

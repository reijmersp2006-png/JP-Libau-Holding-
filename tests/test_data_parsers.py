from datetime import UTC, date, datetime

import pytest

from jplh.data.bitvavo import parse_candles
from jplh.data.dexscreener import parse_pairs
from jplh.data.ecb import parse_csv
from jplh.data.http import DataError
from jplh.data.yahoo import parse_chart


def test_bitvavo_sorted_old_to_new():
    payload = [[1762344000000, "2", "3", "1", "2.5", "10"], [1762340400000, "1", "2", "0.5", "2", "5"]]
    c = parse_candles(payload)
    assert [x.close for x in c] == [2.0, 2.5]
    assert c[0].ts.tzinfo is UTC


def test_yahoo_skips_empty_rows():
    payload = {"chart": {"error": None, "result": [{
        "timestamp": [1762340400, 1762344000, 1762347600],
        "indicators": {"quote": [{"open": [1.0, None, 3.0], "high": [1.5, None, 3.5],
                                  "low": [0.5, None, 2.5], "close": [1.2, None, 3.1],
                                  "volume": [100, None, None]}]}}]}}
    c = parse_chart(payload)
    assert [x.close for x in c] == [1.2, 3.1]
    assert c[1].volume == 0.0


def test_yahoo_error_raises():
    with pytest.raises(DataError):
        parse_chart({"chart": {"error": {"code": "Not Found"}, "result": None}})


def test_ecb_csv():
    text = "KEY,FREQ,TIME_PERIOD,OBS_VALUE\nEXR.D.USD,D,2026-11-03,1.0812\nEXR.D.USD,D,2026-11-04,1.0790\n"
    assert parse_csv(text) == [(date(2026, 11, 3), 1.0812), (date(2026, 11, 4), 1.079)]


def test_dexscreener_red_flags():
    now = datetime(2026, 11, 5, tzinfo=UTC)
    payload = {"pairs": [{
        "chainId": "solana", "pairAddress": "abc", "baseToken": {"symbol": "NEWMEME"},
        "priceUsd": "0.0001", "liquidity": {"usd": 10_000}, "volume": {"h24": 500_000},
        "priceChange": {"h24": 350}, "pairCreatedAt": int(datetime(2026, 11, 3, tzinfo=UTC).timestamp() * 1000),
    }]}
    snap = parse_pairs(payload)[0]
    flags = snap.red_flags(now)
    assert len(flags) == 4
    assert snap.age_days(now) == pytest.approx(2.0)


def test_dexscreener_missing_fields_are_zero():
    snap = parse_pairs({"pairs": [{"baseToken": {}}]})[0]
    assert snap.liquidity_usd == 0.0 and snap.created_at is None

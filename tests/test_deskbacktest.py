from datetime import UTC, datetime

from jplh.config import load_config
from jplh.data.demo import Demo
from jplh.desks import ALL_CANDIDATES
from jplh.deskbacktest import VARIANTS, Variant, _prepare, compare, compare_report, run_desk
from jplh.models import Candle

END = datetime(2026, 11, 1, tzinfo=UTC)


def _world(n=800):
    config = load_config(None)
    demo = Demo({i.symbol: i.asset_class.value for i in config.instruments}, end=END)
    return config, {i.symbol: demo.candles(i.symbol, "1d", n) for i in config.instruments}


def test_compare_runs_every_variant_for_every_desk():
    config, candles = _world()
    res = compare(config, candles, ALL_CANDIDATES)
    assert set(res) == set(config.desks)
    for rows in res.values():
        assert {v.name for v in VARIANTS} == set(rows)
        assert rows["vasthouden (maatlat)"]["switches"] == 0
    assert "Oordeel" in compare_report(res, END, demo=True)


def test_desk_replay_does_not_look_ahead():
    config, candles = _world()
    syms = [i for i in config.instruments if i.asset_class.value == "crypto"]
    cost = config.costs["crypto"]
    v = Variant("alles", risk_sizing=True, switch_margin=0.3, trail=3.0, vote=3)

    def equity(data):
        series = [_prepare(i, data[i.symbol], ALL_CANDIDATES, cost, 365) for i in syms]
        start = series[0].candles[500].ts.date()
        return run_desk("crypto", series, None, config, v, start, 300.0).equity

    base = equity(candles)
    cut = 700
    changed = dict(candles)
    for i in syms:
        cs = candles[i.symbol]
        changed[i.symbol] = cs[:cut] + [Candle(c.ts, c.open * 3, c.high * 3, c.low * 3, c.close * 3, c.volume)
                                         for c in cs[cut:]]
    other = equity(changed)
    k = cut - 500   # dagen vóór de wijziging
    assert base[:k - 1] == other[:k - 1]

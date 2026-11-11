import math
import random
from datetime import UTC, date, datetime, timedelta

from jplh.coach import RULES, Series, beta, event_study, maybe_coach, study, today_warnings
from jplh.config import load_config
from jplh.models import Candle
from jplh.store import Store

T0 = datetime(2023, 1, 1, 22, tzinfo=UTC)


def _save(market, sym, closes):
    cs = [Candle(T0 + timedelta(days=i), p, p, p, p) for i, p in enumerate(closes)]
    market.save_observed(sym, "1d", cs, "test", timedelta(days=1))


def _walk(n, seed, vol=0.02, start=100.0):
    rng, p, out = random.Random(seed), start, []
    for _ in range(n):
        p *= math.exp(rng.gauss(0, vol))
        out.append(p)
    return out


def test_beta_sees_who_moves_harder():
    btc = _walk(400, 1)
    alt = [btc[0]]
    for a, b in zip(btc, btc[1:]):
        alt.append(alt[-1] * (1 + 2 * (b / a - 1)))      # elke dag twee keer zo hard
    m = Store(":memory:")
    _save(m, "BTC-EUR", btc)
    _save(m, "ETH-EUR", alt)
    now = T0 + timedelta(days=500)
    r = beta(Series(m, "ETH-EUR", now).daily(), Series(m, "BTC-EUR", now).daily())
    assert abs(r["beta"] - 2) < 0.05 and r["lo"] > 1


def test_event_study_is_honest_about_noise_and_clusters():
    m = Store(":memory:")
    _save(m, "IWDA.AS", _walk(800, 4, vol=0.01))
    now = T0 + timedelta(days=900)
    s = Series(m, "IWDA.AS", now)
    # willekeurige "momenten" voorspellen niets: de coach mag hier nooit "klopt" zeggen
    rng = random.Random(9)
    ev = event_study(rng.sample(s.dates[:-40], 40), s, 7, +1)
    assert ev["verdict"] in ("niet aangetoond", "klopt niet")
    # tien dagen achter elkaar is één moment, geen tien
    burst = event_study(s.dates[100:110], s, 7, +1)
    assert burst["n"] <= 2 and burst["verdict"] == "te weinig data"


def test_every_rule_runs_on_thin_data_and_never_trades():
    m = Store(":memory:")
    config = load_config(None)
    for i, inst in enumerate(config.instruments):
        _save(m, inst.symbol, _walk(300, i + 1))
    now = T0 + timedelta(days=301)
    got = study(m, config, now)
    assert len(got["rules"]) == len(RULES)
    assert all(r["verdict"] in ("klopt", "klopt niet", "deels", "niet aangetoond", "te weinig data") for r in got["rules"])
    assert any(r["partner"] for r in got["rules"])                     # er zijn samenwerkingsregels


def test_a_confirmed_cross_desk_rule_warns_the_other_desk_once():
    m = Store(":memory:")
    config = load_config(None)
    btc = [100.0] * 50 + [90.0]                                       # gisteren -10%
    _save(m, "BTC-EUR", btc)
    now = T0 + timedelta(days=len(btc) + 1)
    coach = {"rules": [{"id": "btc_crash_memes", "verdict": "klopt", "text": "Memes zakken de dag erna verder."}]}
    w = today_warnings(m, now, coach)
    assert w and w[0]["to"] == "meme" and "Meme Arcade" in w[0]["text"]
    coach["rules"][0]["verdict"] = "niet aangetoond"                  # niet bevestigd: geen waarschuwing
    assert today_warnings(m, now, coach) == []
    first = maybe_coach(m, config, now, None, log=lambda *_: None)
    assert first and maybe_coach(m, config, now + timedelta(hours=1), None, log=lambda *_: None) == first
    assert any(k == "lesson" and p["topic"] == "teamoverleg" for _, k, p in m.events(limit=50)) or first["team_at"] is None

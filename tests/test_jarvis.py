from datetime import UTC, datetime, timedelta

from jplh.jarvis import briefing, health
from jplh.notify import messages, notify
from jplh.store import Store

NOW = datetime(2026, 11, 9, 8, 30, tzinfo=UTC)   # 09:30 in Nederland


def _state(**kw):
    s = {
        "generated_at": NOW.isoformat(), "demo": False, "kill": False,
        "limits": {"max_drawdown_pct": 0.15, "daily_loss_limit_pct": 0.03},
        "total": {"equity_eur": 1010.0, "pnl_pct": 0.01, "day_pnl_pct": 0.002, "benchmark_eur": 1000.0},
        "market_weather": [{"name": "Crypto (bitcoin)", "ok": True, "text": ""}],
        "desks": [
            {"id": "crypto", "name": "Crypto Lab", "pnl_pct": 0.05, "drawdown": 0.0, "paused_reason": None,
             "instruments": [{"symbol": "BTC-EUR", "fresh": True}]},
            {"id": "fx", "name": "Wisselhaven", "pnl_pct": -0.01, "drawdown": 0.0, "paused_reason": None,
             "instruments": [{"symbol": "EURUSD=X", "fresh": False}]},
        ],
        "feed": [{"ts": (NOW - timedelta(minutes=30)).isoformat(), "desk": "crypto", "kind": "trade",
                  "text": "BTC-EUR: koopt", "why": "Trend omhoog"}],
        "lab": {"alerts": []},
    }
    s.update(kw)
    return s


def test_healthy_when_closed_markets_are_stale_but_crypto_is_fresh():
    assert health(_state())["status"] == "ok"


def test_alarm_on_pause_or_stale_crypto():
    st = _state()
    st["desks"][0]["instruments"][0]["fresh"] = False
    assert health(st)["status"] == "alarm"
    st = _state()
    st["desks"][1]["paused_reason"] = "drawdown 16%"
    h = health(st)
    assert h["status"] == "alarm" and "Wisselhaven" in h["issues"][0]["text"]
    assert health(_state(), ["AAPL (HTTP 500)"])["status"] == "let op"


def test_briefing_leads_with_the_money_and_explains_trades():
    b = briefing(_state(), NOW, health(_state()))
    assert b["hello"] == "Goedemorgen"
    assert "€1.010,00" in b["lines"][0] and "beter dan gewoon vasthouden" in b["lines"][0]
    assert any("BTC-EUR: koopt" in x and "trend omhoog" in x for x in b["lines"])
    assert b["speech"].startswith("Goedemorgen Phil.")


class FakeTelegram:
    def __init__(self):
        self.sent = []

    def find_chat(self):
        return "42"

    def send(self, chat, text):
        self.sent.append((chat, text))


def test_notify_sends_briefing_trades_and_only_new_things(tmp_path):
    st = _state()
    st["jarvis"] = {"health": health(st), "briefing": briefing(st, NOW, health(st))}
    market = Store(tmp_path / "m.sqlite3")
    tg = FakeTelegram()
    n = notify(st, market, NOW, log=lambda *_: None, client=tg)
    texts = [t for _, t in tg.sent]
    assert n == 3 and "verbonden" in texts[0] and "Dagbriefing" in texts[1] and "BTC-EUR" in texts[2]
    assert market.get_state("telegram")["chat"] == "42"
    tg.sent.clear()
    assert notify(st, market, NOW + timedelta(hours=1), log=lambda *_: None, client=tg) == 0   # niets nieuws


def test_weather_flip_and_alarm_are_reported():
    memory = {"seen_ts": NOW.isoformat(), "weather": {"Crypto (bitcoin)": True}, "briefing_day": "2026-11-09"}
    st = _state(market_weather=[{"name": "Crypto (bitcoin)", "ok": False, "text": ""}])
    st["desks"][0]["paused_reason"] = "drawdown 16%"
    st["jarvis"] = {"health": health(st)}
    msgs = messages(st, memory, NOW)
    assert any("omgeslagen naar slecht" in m for m in msgs)
    assert any(m.startswith("🚨") for m in msgs)


def test_week_report_on_sunday_evening_once():
    sunday = datetime(2026, 11, 15, 18, 30, tzinfo=UTC)          # 19:30 in Nederland
    st = _state()
    st["total"]["pnl_pct"] = 0.01
    st["total"]["equity_curve"] = [[(sunday - timedelta(days=8)).isoformat(), 1000.0], [sunday.isoformat(), 1010.0]]
    st["desks"][0].update(equity_eur=525.0, equity_curve=[[(sunday - timedelta(days=8)).isoformat(), 500.0]])
    st["desks"][1].update(equity_eur=495.0, equity_curve=[[(sunday - timedelta(days=8)).isoformat(), 500.0]])
    st["feed"] = [{"ts": (sunday - timedelta(days=2)).isoformat(), "desk": "crypto", "kind": "reflection",
                   "text": "terugblik BTC-EUR: goed"}]
    st["jarvis"] = {"health": {"status": "ok", "issues": []}}
    memory = {"seen_ts": sunday.isoformat(), "briefing_day": "2026-11-15"}
    msgs = messages(st, memory, sunday)
    report = next(m for m in msgs if "Weekrapport" in m)
    assert "+1,0%" in report and "Winnaar van de week: Crypto Lab" in report and "terugblik BTC-EUR" in report
    assert not any("Weekrapport" in m for m in messages(st, memory, sunday + timedelta(hours=1)))
    assert not any("Weekrapport" in m for m in messages(_state(), {"briefing_day": "2026-11-09"}, NOW))


def test_telegram_only_gets_alerts_about_what_we_own_or_the_whole_market():
    st = _state()
    st["desks"][0]["positions"] = [{"symbol": "BTC-EUR"}]
    ts = NOW.isoformat()
    st["lab"]["alerts"] = [
        {"ts": ts, "symbol": "BTC-EUR", "kind": "val", "level": "groot", "text": "BTC-EUR: val"},
        {"ts": ts, "symbol": "PEPE-EUR", "kind": "volume", "level": "groot", "text": "PEPE-EUR: drukte"},
        {"ts": ts, "symbol": "markt:uur", "kind": "markt", "level": "groot", "text": "Hele markt in beweging"},
    ]
    text = "\n".join(messages(st, {"seen_ts": (NOW - timedelta(hours=1)).isoformat()}, NOW))
    assert "BTC-EUR: val" in text and "Hele markt" in text and "PEPE" not in text

from datetime import UTC, datetime
from pathlib import Path

from jplh.commands import answer, listen
from jplh.config import load_config
from jplh.paper import build_demo
from jplh.store import Store

NOW = datetime(2026, 11, 9, 16, 5, tzinfo=UTC)


def _home(tmp_path) -> Path:
    home = tmp_path / "h"
    build_demo(load_config(None), home, hours=6, history_days=3, now=NOW)
    return home


class Fake:
    def __init__(self, updates):
        self.updates, self.sent = updates, []

    def call(self, method, params=None):
        assert method == "getUpdates"
        off = (params or {}).get("offset", 0)
        return {"ok": True, "result": [u for u in self.updates if u["update_id"] >= off]}

    def send(self, chat, text):
        self.sent.append((chat, text))


def _msg(uid, chat, text):
    return {"update_id": uid, "message": {"chat": {"id": chat, "type": "private"}, "text": text}}


def test_noodstop_and_hervat_toggle_the_kill_file(tmp_path):
    home = _home(tmp_path)
    cfg, market = load_config(None), Store(home / "data" / "holding.sqlite3")
    assert "AAN" in answer("/noodstop", cfg, home, market, NOW) and (home / "KILL").exists()
    assert "uit" in answer("/hervat", cfg, home, market, NOW) and not (home / "KILL").exists()


def test_stand_and_waarom_answer_from_the_books(tmp_path):
    home = _home(tmp_path)
    cfg, market = load_config(None), Store(home / "data" / "holding.sqlite3")
    stand = answer("/stand", cfg, home, market, NOW)
    assert "Schatkist" in stand and "Crypto Lab" in stand
    assert "Waarom:" in answer("/waarom BTC", cfg, home, market, NOW)
    assert "ken ik niet" in answer("/raket", cfg, home, market, NOW)


def test_only_phils_chat_is_obeyed_and_updates_are_used_once(tmp_path):
    home = _home(tmp_path)
    Store(home / "data" / "holding.sqlite3").set_state("telegram", {"chat": "42"})
    fake = Fake([_msg(1, 999, "/noodstop"), _msg(2, 42, "/help")])
    assert listen(load_config(None), home, fake, log=lambda *_: None, now=NOW) == 1
    assert not (home / "KILL").exists()                     # vreemde chat mag niets
    assert fake.sent == [("42", fake.sent[0][1])] and "/noodstop" in fake.sent[0][1]
    assert listen(load_config(None), home, fake, log=lambda *_: None, now=NOW) == 0   # al gedaan


class Px:
    """Nepkoersbron: geeft steeds de koers die je erin zet."""
    name = "fake"

    def __init__(self, price):
        self.price = price

    def candles(self, symbol, interval="1h", limit=200):
        from jplh.models import Candle
        return [Candle(NOW, self.price, self.price, self.price, self.price, 1.0)]


def test_alarm_is_set_listed_fired_once_and_removed(tmp_path):
    home = _home(tmp_path)
    cfg, market = load_config(None), Store(home / "data" / "holding.sqlite3")
    market.set_state("telegram", {"chat": "42"})
    px = Px(70_000.0)
    src = {"bitvavo": px, "yahoo": px}
    memo = {}
    reply = answer("/alarm BTC 80.000", cfg, home, market, NOW, memo, src)
    assert "BTC-EUR" in reply and "boven" in reply and memo["alarms"][0]["level"] == 80_000
    assert "BTC-EUR boven" in answer("/alarmen", cfg, home, market, NOW, memo, src)
    assert "ken ik niet" in answer("/alarm RAKET 5", cfg, home, market, NOW, memo, src)

    (home / "jarvis.json").write_text(__import__("json").dumps(memo))
    fake = Fake([])
    listen(cfg, home, fake, log=lambda *_: None, now=NOW, sources=src)
    assert fake.sent == []                                   # nog niet geraakt
    px.price = 80_500.0
    listen(cfg, home, fake, log=lambda *_: None, now=NOW, sources=src)
    assert len(fake.sent) == 1 and "Alarm" in fake.sent[0][1]
    listen(cfg, home, fake, log=lambda *_: None, now=NOW, sources=src)
    assert len(fake.sent) == 1                               # maar één keer melden


def test_alarm_remove_and_small_coin_prices(tmp_path):
    home = _home(tmp_path)
    cfg, market = load_config(None), Store(home / "data" / "holding.sqlite3")
    src = {"bitvavo": Px(0.0000105), "yahoo": Px(1.0)}
    memo = {}
    reply = answer("/alarm PEPE 0,000009", cfg, home, market, NOW, memo, src)
    assert "onder" in reply and abs(memo["alarms"][0]["level"] - 0.000009) < 1e-12
    assert "0,0000090" in reply
    assert "1 alarm" in answer("/alarm weg PEPE", cfg, home, market, NOW, memo, src)
    assert memo["alarms"] == []

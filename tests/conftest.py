from datetime import UTC, datetime, timedelta

import pytest

from jplh.config import load_config
from jplh.holding import Holding
from jplh.models import Candle
from jplh.store import Store

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def flat(price: float, n: int = 5, end: datetime = NOW) -> list[Candle]:
    return [Candle(end - timedelta(hours=n - i), price, price, price, price, 1.0) for i in range(n)]


@pytest.fixture
def config():
    return load_config(None)


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def seed_prices(store: Store, config, prices: dict[str, float], end: datetime = NOW) -> None:
    defaults = {i.symbol: 100.0 for i in config.instruments}
    defaults.update({"EURUSD=X": 1.10, "EURGBP=X": 0.85, "EURJPY=X": 160.0, "EURCHF=X": 0.95})
    defaults.update(prices)
    for sym, p in defaults.items():
        store.save_candles(sym, "1h", flat(p, end=end), "test", end)


@pytest.fixture
def holding(config, store, tmp_path):
    seed_prices(store, config, {})
    return Holding(config, store, base_dir=tmp_path, log_dir=tmp_path / "logs")

import warnings

import pytest

warnings.filterwarnings("ignore", category=DeprecationWarning)

from fastapi.testclient import TestClient  # noqa: E402

from nexus.app import create_app  # noqa: E402
from nexus.settings import Settings  # noqa: E402


@pytest.fixture(scope="session")
def demo_home(tmp_path_factory):
    """Eén kleine demo-wereld van de holding (nep-koersen, expliciet demo) voor alle tests."""
    from jplh.config import load_config
    from jplh.paper import build_demo
    home = tmp_path_factory.mktemp("demo") / "home"
    build_demo(load_config(), home, hours=24, history_days=8)
    return home


@pytest.fixture
def demo_settings(demo_home):
    return Settings(demo=True, demo_home=demo_home, database_url="sqlite:///:memory:", admin_token="geheim-token-123",
                    cache_seconds=0, worker=False)


@pytest.fixture
def client(demo_settings):
    return TestClient(create_app(demo_settings))


@pytest.fixture(autouse=True)
def _clean_kill(demo_home):
    yield
    (demo_home / "KILL").unlink(missing_ok=True)


def proposal(**over) -> dict:
    p = {
        "idempotency_key": "test-0001-abcdef", "source": "test", "symbol": "IWDA.AS", "asset_class": "stocks",
        "direction": "buy", "strategy_id": "trend_v1", "entry_conditions": "slot boven 50-daags gemiddelde",
        "entry_price": 100.0, "size_eur": 20.0, "stop_loss": 95.0, "take_profit": "trailing stop 2x ATR",
        "holding_period": "2-6 weken", "est_fee_pct": 0.001, "est_slippage_pct": 0.001, "spread_pct": 0.001,
        "available_liquidity_eur": 50_000_000, "evidence": ["trend omhoog"], "counterarguments": ["hoge waardering"],
        "reasons_to_avoid": ["rentebesluit volgende week"], "max_modeled_loss_eur": 1.5,
        "scenario_risks": ["gap omlaag bij opening"], "input_data_label": "DELAYED",
    }
    p.update(over)
    return p

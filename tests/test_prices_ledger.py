import pytest

from conftest import NOW

from jplh.ledger import Portfolio
from jplh.models import Fill, Side
from jplh.prices import PriceBook, PriceError


def test_usd_stock_converted_to_eur(config):
    b = PriceBook({i.symbol: i for i in config.instruments})
    b.update("AAPL", NOW, 220.0)
    b.update("EURUSD=X", NOW, 1.10)
    assert b.price_eur("AAPL") == pytest.approx(200.0)
    # Een valuta-positie is de vreemde munt zelf: 1 USD = 1/1.10 euro.
    assert b.price_eur("EURUSD=X") == pytest.approx(1 / 1.10)


def test_missing_fx_raises(config):
    b = PriceBook({i.symbol: i for i in config.instruments})
    b.update("AAPL", NOW, 220.0)
    with pytest.raises(PriceError):
        b.price_eur("AAPL")


def test_buy_sell_pnl_and_fees():
    p = Portfolio(1000.0)
    p.apply(Fill("BTC-EUR", Side.BUY, 2.0, 100.0, 1.0, NOW))
    assert p.cash_eur == pytest.approx(799.0)
    p.apply(Fill("BTC-EUR", Side.SELL, 2.0, 110.0, 1.0, NOW))
    assert "BTC-EUR" not in p.positions
    assert p.cash_eur == pytest.approx(1018.0)
    assert p.realized_pnl_eur == pytest.approx(19.0)
    assert p.fees_eur == pytest.approx(2.0)


def test_cannot_overspend_or_oversell():
    p = Portfolio(100.0)
    with pytest.raises(ValueError):
        p.apply(Fill("BTC-EUR", Side.BUY, 2.0, 100.0, 0.0, NOW))
    with pytest.raises(ValueError):
        p.apply(Fill("BTC-EUR", Side.SELL, 1.0, 100.0, 0.0, NOW))


def test_roundtrip_dict():
    p = Portfolio(500.0)
    p.apply(Fill("ETH-EUR", Side.BUY, 1.0, 100.0, 0.5, NOW))
    assert Portfolio.from_dict(p.to_dict()) == p

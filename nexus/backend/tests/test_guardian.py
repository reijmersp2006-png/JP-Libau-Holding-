import pytest
from pydantic import ValidationError

from conftest import proposal
from nexus.controls import Mode
from nexus.guardian import PortfolioView, RiskGuardian, RiskLimits, limits_from_env
from nexus.proposals import TradeProposalIn

VIEW = PortfolioView(equity_eur=1000.0, position_value={"BTC-EUR": 80.0}, class_exposure={"crypto": 80.0},
                     day_pnl_pct=0.0, drawdown=0.02)


def ev(view=VIEW, mode=Mode.PAPER, kill=False, **over):
    return RiskGuardian().evaluate(TradeProposalIn(**proposal(**over)), view, mode, kill)


def failed(v):
    return {c.rule for c in v.checks if not c.passed}


def test_good_proposal_passes_and_reports_every_check():
    v = ev()
    assert v.approved, v.reason
    assert {"noodstop", "risico_per_trade", "concentratie", "liquiditeit"} <= {c.rule for c in v.checks}


def test_kill_switch_vetoes_even_sells():
    assert "noodstop" in failed(ev(kill=True))
    assert not ev(kill=True, symbol="BTC-EUR", asset_class="crypto", direction="sell", size_eur=10).approved


def test_no_portfolio_means_no_trade():
    v = ev(view=None)
    assert not v.approved and "portefeuille_bekend" in failed(v)


@pytest.mark.parametrize("over,rule", [
    ({"size_eur": 200.0, "max_modeled_loss_eur": 10.0}, "concentratie"),
    ({"stop_loss": 40.0}, "risico_per_trade"),                       # 60% tot de stop op €20 = €12 > 1%
    ({"spread_pct": 0.02}, "spread"),
    ({"est_slippage_pct": 0.05}, "slippage"),
    ({"available_liquidity_eur": None}, "liquiditeit"),
    ({"available_liquidity_eur": 2_000_000, "size_eur": 2500.0}, "order_vs_liquiditeit"),
    ({"input_data_label": "HISTORICAL"}, "data_beschikbaar"),
    ({"input_data_label": "UNAVAILABLE"}, "data_beschikbaar"),
])
def test_vetoes(over, rule):
    v = ev(**over)
    assert not v.approved and rule in failed(v)


def test_meme_needs_security_checks_and_allocation_room():
    v = ev(symbol="PEPE-EUR", asset_class="meme", size_eur=20.0)
    assert "meme_veiligheid" in failed(v)
    v = ev(symbol="PEPE-EUR", asset_class="meme", size_eur=60.0, security_checks_passed=True,
           max_modeled_loss_eur=3.0)
    assert "memecoin_limiet" in failed(v)


def test_drawdown_and_daily_loss_suspend_buys():
    bad = PortfolioView(1000.0, {}, {}, day_pnl_pct=-0.05, drawdown=0.2)
    assert {"max_drawdown", "dagverlies"} <= failed(ev(view=bad))


def test_sell_without_position_is_refused_no_shorting():
    v = ev(direction="sell")
    assert not v.approved and "positie_aanwezig" in failed(v)


def test_proposal_schema_demands_exit_and_counterarguments():
    with pytest.raises(ValidationError):
        TradeProposalIn(**proposal(stop_loss=None))
    TradeProposalIn(**proposal(stop_loss=None, alternative_exit="verkopen na 10 dagen"))
    with pytest.raises(ValidationError):
        TradeProposalIn(**proposal(counterarguments=[]))
    with pytest.raises(ValidationError):   # LLM-zekerheid mag zich niet "gekalibreerd" noemen
        TradeProposalIn(**proposal(confidence={"value": 0.8, "calibrated": True, "method": "llm"}))


def test_limits_can_only_be_tightened():
    assert limits_from_env({"NEXUS_RISK_MAX_MEME_PCT": "0.02"}).max_meme_pct == 0.02
    with pytest.raises(ValueError):
        limits_from_env({"NEXUS_RISK_MAX_MEME_PCT": "0.5"})
    with pytest.raises(ValueError):
        RiskLimits().tightened(min_liquidity_eur=10.0)
    assert RiskLimits().tightened(min_liquidity_eur=5e6).min_liquidity_eur == 5e6

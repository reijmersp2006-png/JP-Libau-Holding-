import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from nexus.db import Account, Database, Organization, SubscriptionPlan


def test_migration_creates_every_entity(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'n.db'}")
    tables = set(inspect(db.engine).get_table_names())
    for t in ("users", "organizations", "accounts", "broker_connections", "assets", "market_data", "strategies",
              "strategy_versions", "backtests", "trade_proposals", "orders", "executions", "positions",
              "portfolio_valuations", "risk_policies", "ai_research_reports", "agent_decisions", "audit_log",
              "subscription_plans", "billing_records"):
        assert t in tables, t
    Database(f"sqlite:///{tmp_path / 'n.db'}")        # tweede keer: migratie is idempotent


def test_plans_seeded_but_inactive_until_legal_review():
    db = Database("sqlite:///:memory:")
    with db.session() as s:
        plans = {p.key: p for p in s.query(SubscriptionPlan)}
    assert {k: p.price_eur_cents for k, p in plans.items()} == {"starter": 1900, "pro": 5900, "elite": 14900}
    assert not any(p.active for p in plans.values())


def test_tenant_isolation_of_audit_log():
    db = Database("sqlite:///:memory:")
    with db.session.begin() as s:
        s.add(Organization(id=2, name="klant"))
    db.audit("x", "geheim", {"a": 1}, org_id=2)
    db.audit("x", "eigen", {})
    assert [e["action"] for e in db.audit_entries()] == ["eigen"]
    assert [e["action"] for e in db.audit_entries(org_id=2)] == ["geheim"]


def test_live_account_requires_broker_connection():
    db = Database("sqlite:///:memory:")
    with pytest.raises(IntegrityError):
        with db.session.begin() as s:
            s.add(Account(org_id=1, name="live", kind="live", starting_cash=0, cash=0, peak_equity=0))

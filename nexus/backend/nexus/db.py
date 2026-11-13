"""Opslag van NEXUS (los van de boekhouding van de holding-bots).

Alle klant-gebonden tabellen hebben ``org_id``: zo blijft data van verschillende organisaties
gescheiden zodra NEXUS meerdere gebruikers krijgt. In de persoonlijke MVP bestaat één
organisatie (JP-libau Holding, id 1). Bedragen staan als NUMERIC in de database en worden als
float teruggegeven; alle berekeningen zijn deterministisch (geen willekeur, geen klok in de som).

Schemawijzigingen gaan via Alembic (``migrations/``). Tests en een lege SQLite-database in het
geheugen gebruiken ``create_all``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

DEFAULT_ORG = 1


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def iso(ts: datetime | None) -> str | None:
    """SQLite bewaart geen tijdzone; alles wat we opslaan is UTC."""
    if ts is None:
        return None
    return (ts if ts.tzinfo else ts.replace(tzinfo=UTC)).isoformat()


def Money():
    return Numeric(24, 10, asdecimal=False)


TS = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


# ── Organisaties, gebruikers, abonnementen ─────────────────────────────────────────────────
class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    plan_key: Mapped[str | None] = mapped_column(ForeignKey("subscription_plans.key"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mfa_secret_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)  # verwijzing naar secret store
    role: Mapped[str] = mapped_column(String(16), default="owner")
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    __table_args__ = (CheckConstraint("role IN ('owner','admin','analyst','viewer')", name="ck_users_role"),)


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"
    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    price_eur_cents: Mapped[int] = mapped_column(Integer)
    limits: Mapped[dict] = mapped_column(JSON, default=dict)        # AI-verzoeken, watchlists, strategieën
    trial_days: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=False)    # pas aan na juridische toets
    __table_args__ = (CheckConstraint("price_eur_cents >= 0", name="ck_plan_price"),)


class BillingRecord(Base):
    __tablename__ = "billing_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    plan_key: Mapped[str] = mapped_column(ForeignKey("subscription_plans.key"))
    period_start: Mapped[datetime] = mapped_column(TS)
    period_end: Mapped[datetime] = mapped_column(TS)
    amount_eur_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))                 # draft, open, paid, failed, refunded
    provider: Mapped[str] = mapped_column(String(32), default="stripe")
    provider_ref: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)


# ── Accounts en brokers ────────────────────────────────────────────────────────────────────
class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16))                   # paper | live
    base_currency: Mapped[str] = mapped_column(String(3), default="EUR")
    starting_cash: Mapped[float] = mapped_column(Money())
    cash: Mapped[float] = mapped_column(Money())
    realized_pnl: Mapped[float] = mapped_column(Money(), default=0.0)
    fees: Mapped[float] = mapped_column(Money(), default=0.0)
    peak_equity: Mapped[float] = mapped_column(Money())
    broker_connection_id: Mapped[int | None] = mapped_column(ForeignKey("broker_connections.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    __table_args__ = (CheckConstraint("kind IN ('paper','live')", name="ck_account_kind"),
                      CheckConstraint("kind = 'paper' OR broker_connection_id IS NOT NULL", name="ck_live_needs_broker"))


class BrokerConnection(Base):
    __tablename__ = "broker_connections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    credentials_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)  # nooit de sleutel zelf
    permissions: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="disconnected")
    verified_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)


# ── Markten ────────────────────────────────────────────────────────────────────────────────
class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(64))
    asset_class: Mapped[str] = mapped_column(String(16))
    venue: Mapped[str] = mapped_column(String(32))
    currency: Mapped[str] = mapped_column(String(3))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("symbol", "venue", name="uq_asset_symbol_venue"),)


class MarketBar(Base):
    __tablename__ = "market_data"
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), primary_key=True)
    interval: Mapped[str] = mapped_column(String(8), primary_key=True)
    ts: Mapped[datetime] = mapped_column(TS, primary_key=True)
    open: Mapped[float] = mapped_column(Money())
    high: Mapped[float] = mapped_column(Money())
    low: Mapped[float] = mapped_column(Money())
    close: Mapped[float] = mapped_column(Money())
    volume: Mapped[float] = mapped_column(Money(), default=0.0)
    source: Mapped[str] = mapped_column(String(32))
    fetched_at: Mapped[datetime] = mapped_column(TS)                # point-in-time
    quality: Mapped[str] = mapped_column(String(16), default="ok")


# ── Strategieën en backtests ───────────────────────────────────────────────────────────────
class StrategyRow(Base):
    __tablename__ = "strategies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)  # None = ingebouwd
    key: Mapped[str] = mapped_column(String(64))
    family: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text, default="")
    __table_args__ = (UniqueConstraint("org_id", "key", name="uq_strategy_org_key"),)


class StrategyVersion(Base):
    __tablename__ = "strategy_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    params: Mapped[dict] = mapped_column(JSON)
    spec: Mapped[dict] = mapped_column(JSON)                        # data, instap, uitstap, omvang, risico
    status: Mapped[str] = mapped_column(String(16), default="research")
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    __table_args__ = (UniqueConstraint("strategy_id", "version", name="uq_strategy_version"),
                      CheckConstraint("status IN ('research','paper','live_candidate','retired')", name="ck_sv_status"))


class Backtest(Base):
    __tablename__ = "backtests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    strategy_version_id: Mapped[int] = mapped_column(ForeignKey("strategy_versions.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    interval: Mapped[str] = mapped_column(String(8))
    data_label: Mapped[str] = mapped_column(String(16))
    settings: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)


# ── Voorstellen, risico, orders ────────────────────────────────────────────────────────────
class RiskPolicy(Base):
    __tablename__ = "risk_policies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    limits: Mapped[dict] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    created_by: Mapped[str] = mapped_column(String(64))


class TradeProposal(Base):
    __tablename__ = "trade_proposals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True, default=DEFAULT_ORG)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    source: Mapped[str] = mapped_column(String(64))
    asset_class: Mapped[str] = mapped_column(String(16))
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    direction: Mapped[str] = mapped_column(String(8))
    strategy_id: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), index=True)   # approved_by_guardian | vetoed | executed
    executed: Mapped[bool] = mapped_column(Boolean, default=False)


class RiskEvaluation(Base):
    __tablename__ = "risk_evaluations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("trade_proposals.id"), index=True)
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow)
    approved: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(Text)
    checks: Mapped[list] = mapped_column(JSON)
    limits_snapshot: Mapped[dict] = mapped_column(JSON)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    proposal_id: Mapped[int | None] = mapped_column(ForeignKey("trade_proposals.id"), nullable=True)
    evaluation_id: Mapped[int] = mapped_column(ForeignKey("risk_evaluations.id"))   # geen order zonder oordeel
    client_order_id: Mapped[str] = mapped_column(String(128), unique=True)        # idempotentie
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    asset_class: Mapped[str] = mapped_column(String(16))
    side: Mapped[str] = mapped_column(String(4))
    order_type: Mapped[str] = mapped_column(String(8), default="market")
    notional_eur: Mapped[float | None] = mapped_column(Money(), nullable=True)      # koop: bedrag
    quantity: Mapped[float | None] = mapped_column(Money(), nullable=True)          # verkoop: aantal
    filled_quantity: Mapped[float] = mapped_column(Money(), default=0.0)
    filled_notional_eur: Mapped[float] = mapped_column(Money(), default=0.0)
    status: Mapped[str] = mapped_column(String(20), index=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    __table_args__ = (
        CheckConstraint("side IN ('buy','sell')", name="ck_order_side"),
        CheckConstraint("status IN ('new','partially_filled','filled','cancelled','rejected')", name="ck_order_status"),
        CheckConstraint("(side = 'buy' AND notional_eur > 0) OR (side = 'sell' AND quantity > 0)", name="ck_order_size"),
    )


class Execution(Base):
    __tablename__ = "executions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow)
    symbol: Mapped[str] = mapped_column(String(64))
    side: Mapped[str] = mapped_column(String(4))
    quantity: Mapped[float] = mapped_column(Money())
    price_eur: Mapped[float] = mapped_column(Money())
    reference_price_eur: Mapped[float] = mapped_column(Money())    # koers vóór spread en slippage
    fee_eur: Mapped[float] = mapped_column(Money())
    data_label: Mapped[str] = mapped_column(String(16))
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_exec_qty"),)


class PositionRow(Base):
    __tablename__ = "positions"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_class: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[float] = mapped_column(Money())
    avg_price_eur: Mapped[float] = mapped_column(Money())
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class PortfolioValuation(Base):
    __tablename__ = "portfolio_valuations"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    ts: Mapped[datetime] = mapped_column(TS, primary_key=True)
    equity_eur: Mapped[float] = mapped_column(Money())
    cash_eur: Mapped[float] = mapped_column(Money())
    label: Mapped[str] = mapped_column(String(16))


# ── AI ─────────────────────────────────────────────────────────────────────────────────────
class ResearchReport(Base):
    __tablename__ = "ai_research_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    topic: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16))                 # running, done, failed
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)


class AgentDecision(Base):
    __tablename__ = "agent_decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("ai_research_reports.id"), index=True)
    agent_id: Mapped[str] = mapped_column(String(32))
    input_hash: Mapped[str] = mapped_column(String(64))
    output: Mapped[dict] = mapped_column(JSON)                      # gevalideerd tegen het output-schema
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


# ── Besturing en audit ─────────────────────────────────────────────────────────────────────
class SystemState(Base):
    __tablename__ = "system_state"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class AuditLog(Base):
    """Alleen toevoegen, nooit wijzigen."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True, default=DEFAULT_ORG)
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


# ── Onderzoek en leren (NEXUS Evolution) ───────────────────────────────────────────────────
class ResearchRun(Base):
    """Eén onderzoeksrun (ontdekking, audit, geplande taak) met samenvatting en kosten."""

    __tablename__ = "research_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True, default=DEFAULT_ORG)
    kind: Mapped[str] = mapped_column(String(32))                   # discovery, audit, job:<naam>
    interval: Mapped[str | None] = mapped_column(String(8), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="done")
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    report: Mapped[dict] = mapped_column(JSON, default=dict)
    ai_requests: Mapped[int] = mapped_column(Integer, default=0)
    ai_cost_usd: Mapped[float] = mapped_column(Money(), default=0)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)


class ModelVersion(Base):
    """Modelregister: elke strategieversie met status, poorten en herkomst. Promotie gaat alleen
    via een mens; live blijft dicht (zie ``controls.live_gate``)."""

    __tablename__ = "model_registry"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True, default=DEFAULT_ORG)
    key: Mapped[str] = mapped_column(String(64), index=True)       # familie of lab-strategie
    version: Mapped[int] = mapped_column(Integer)
    symbols: Mapped[list] = mapped_column(JSON)
    interval: Mapped[str] = mapped_column(String(8))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="research")
    role: Mapped[str | None] = mapped_column(String(16), nullable=True)   # champion, challenger
    gates: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    source_run_id: Mapped[int | None] = mapped_column(ForeignKey("research_runs.id"), nullable=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("model_registry.id"), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    __table_args__ = (
        UniqueConstraint("org_id", "key", "version", "interval", "symbols", name="uq_model_version"),
        CheckConstraint("status IN ('research','candidate','challenger','paper','champion','retired','rejected')",
                        name="ck_model_status"),
    )


class Hypothesis(Base):
    __tablename__ = "hypotheses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True, default=DEFAULT_ORG)
    source: Mapped[str] = mapped_column(String(32))                # audit, evolution, agent, human
    error_tag: Mapped[str | None] = mapped_column(String(48), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    statement: Mapped[str] = mapped_column(Text)
    test: Mapped[dict] = mapped_column(JSON, default=dict)          # familie, instrumenten, rooster
    status: Mapped[str] = mapped_column(String(16), default="open")
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    __table_args__ = (CheckConstraint("status IN ('open','testing','supported','rejected','inconclusive')",
                                      name="ck_hypothesis_status"),)


class DecisionRecord(Base):
    """Trade memory: elk besluit (uitgevoerd, afgewezen of gemist) met context en uitkomst."""

    __tablename__ = "decision_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True, default=DEFAULT_ORG)
    ts: Mapped[datetime] = mapped_column(TS, index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(16))                   # executed, rejected, missed
    source: Mapped[str] = mapped_column(String(32))                 # paper, strategy, council, manual, holding
    side: Mapped[str] = mapped_column(String(4))
    strategy_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    strategy_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    regime: Mapped[dict] = mapped_column(JSON, default=dict)
    indicators: Mapped[dict] = mapped_column(JSON, default=dict)
    news_context: Mapped[list] = mapped_column(JSON, default=list)
    agent_recommendations: Mapped[list] = mapped_column(JSON, default=list)
    entry_conditions: Mapped[dict] = mapped_column(JSON, default=dict)
    exit_conditions: Mapped[dict] = mapped_column(JSON, default=dict)
    size_eur: Mapped[float] = mapped_column(Money(), default=0)
    price: Mapped[float] = mapped_column(Money(), default=0)
    est_costs_eur: Mapped[float] = mapped_column(Money(), default=0)
    actual: Mapped[dict] = mapped_column(JSON, default=dict)
    proposal_id: Mapped[int | None] = mapped_column(ForeignKey("trade_proposals.id"), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[dict] = mapped_column(JSON, default=dict)       # termijnrendementen, resultaat
    outcome_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    error_tags: Mapped[list] = mapped_column(JSON, default=list)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    __table_args__ = (CheckConstraint("kind IN ('executed','rejected','missed')", name="ck_decision_kind"),
                      CheckConstraint("side IN ('buy','sell')", name="ck_decision_side"))


class NewsEvent(Base):
    __tablename__ = "news_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(48), index=True)
    source_kind: Mapped[str] = mapped_column(String(16))            # official, exchange, media
    url: Mapped[str] = mapped_column(String(1000))
    title: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime] = mapped_column(TS, index=True)
    fetched_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    category: Mapped[str] = mapped_column(String(32), index=True)
    assets: Mapped[list] = mapped_column(JSON, default=list)
    factuality: Mapped[str] = mapped_column(String(16))             # fact, speculation, mixed
    expectation: Mapped[dict] = mapped_column(JSON, default=dict)
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)
    reaction: Mapped[dict] = mapped_column(JSON, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # News Reactor (4.0): verwante berichten, latenties, feiten, relevantie.
    cluster_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    duplicate_of: Mapped[int | None] = mapped_column(Integer, nullable=True)
    analyzed_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    signal_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    relevance: Mapped[float | None] = mapped_column(Numeric(6, 4, asdecimal=False), nullable=True)
    facts: Mapped[list] = mapped_column(JSON, default=list)


class OrchestratorTask(Base):
    """Eén taak van NEXUS Central: expliciete status, wie, waarom, uitkomst. Geen vrije agent-lussen."""

    __tablename__ = "orchestrator_tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True, default=DEFAULT_ORG)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    department: Mapped[str] = mapped_column(String(24))
    agent: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)   # queued running done failed escalated cancelled
    priority: Mapped[int] = mapped_column(Integer, default=50)
    subject: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    history: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Money(), default=0)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class Briefing(Base):
    __tablename__ = "briefings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True, default=DEFAULT_ORG)
    day: Mapped[str] = mapped_column(String(10), index=True)
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class SocialSnapshot(Base):
    """Sociale meting voor één onderwerp (cashtag, contract) over een venster, met de bron en of die verbonden was."""

    __tablename__ = "social_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic: Mapped[str] = mapped_column(String(128), index=True)
    source: Mapped[str] = mapped_column(String(24))
    window_start: Mapped[datetime] = mapped_column(TS, index=True)
    window_end: Mapped[datetime] = mapped_column(TS)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class TokenCheck(Base):
    """On-chain veiligheidscontrole van een token. Zakt een verplichte controle, dan geen handelsvoorstel."""

    __tablename__ = "token_checks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chain: Mapped[str] = mapped_column(String(24))
    address: Mapped[str] = mapped_column(String(128), index=True)
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16))                 # pass, fail, unavailable
    checks: Mapped[list] = mapped_column(JSON, default=list)
    market: Mapped[dict] = mapped_column(JSON, default=dict)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    checked_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)


class CouncilRun(Base):
    __tablename__ = "council_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True, default=DEFAULT_ORG)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16))                 # done, failed, unavailable, budget
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    independent: Mapped[list] = mapped_column(JSON, default=list)
    debate: Mapped[list] = mapped_column(JSON, default=list)
    decision: Mapped[dict] = mapped_column(JSON, default=dict)
    proposal_id: Mapped[int | None] = mapped_column(ForeignKey("trade_proposals.id"), nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Money(), default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)


class AgentForecast(Base):
    """Een toetsbare voorspelling van één agent; wordt later afgerekend op de echte koers."""

    __tablename__ = "agent_forecasts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("council_runs.id"), index=True)
    agent: Mapped[str] = mapped_column(String(48), index=True)
    phase: Mapped[str] = mapped_column(String(16))                  # independent, debate
    symbol: Mapped[str] = mapped_column(String(32))
    ts: Mapped[datetime] = mapped_column(TS, index=True)
    price: Mapped[float] = mapped_column(Money())
    stance: Mapped[str] = mapped_column(String(24))
    prob_up: Mapped[float | None] = mapped_column(Numeric(6, 4, asdecimal=False), nullable=True)
    horizon_days: Mapped[int] = mapped_column(Integer)
    regime: Mapped[str | None] = mapped_column(String(16), nullable=True)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    resolved_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    realized_return: Mapped[float | None] = mapped_column(Numeric(12, 6, asdecimal=False), nullable=True)
    brier: Mapped[float | None] = mapped_column(Numeric(6, 4, asdecimal=False), nullable=True)
    hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class ExternalBatch(Base):
    """Geïmporteerde resultaten van een ander systeem (bijv. de Grok-bot)."""

    __tablename__ = "external_batches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True, default=DEFAULT_ORG)
    system: Mapped[str] = mapped_column(String(48))
    fmt: Mapped[str] = mapped_column(String(8))
    completeness: Mapped[str] = mapped_column(String(16))           # trades, aggregate
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    trades: Mapped[list] = mapped_column(JSON, default=list)
    issues: Mapped[list] = mapped_column(JSON, default=list)
    uploaded_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class JobRun(Base):
    __tablename__ = "job_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job: Mapped[str] = mapped_column(String(48), index=True)
    started_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    status: Mapped[str] = mapped_column(String(16))                 # ok, failed, skipped
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    ai_requests: Mapped[int] = mapped_column(Integer, default=0)
    ai_cost_usd: Mapped[float] = mapped_column(Money(), default=0)



Index("ix_orders_account_status", Order.account_id, Order.status)
Index("ix_exec_account_ts", Execution.account_id, Execution.ts)

PLANS = [  # voorgestelde prijzen, configureerbaar; inactief tot de juridische toets klaar is
    {"key": "starter", "name": "Starter", "price_eur_cents": 1900, "trial_days": 14,
     "limits": {"ai_requests_month": 100, "watchlists": 3, "strategies": 3, "paper_accounts": 1}},
    {"key": "pro", "name": "Pro", "price_eur_cents": 5900, "trial_days": 14,
     "limits": {"ai_requests_month": 1000, "watchlists": 20, "strategies": 20, "paper_accounts": 3}},
    {"key": "elite", "name": "Elite", "price_eur_cents": 14900, "trial_days": 14,
     "limits": {"ai_requests_month": 5000, "watchlists": 100, "strategies": 100, "paper_accounts": 10}},
]


class Database:
    def __init__(self, url: str, migrate: bool = True) -> None:
        kw: dict = {}
        if url.startswith("sqlite"):
            kw["connect_args"] = {"check_same_thread": False}
            if ":memory:" in url:
                kw["poolclass"] = StaticPool       # één gedeelde verbinding, anders is elke thread leeg
        self.url = url
        self.engine = create_engine(url, future=True, **kw)
        if ":memory:" in url or not migrate:
            Base.metadata.create_all(self.engine)
        else:
            upgrade(url)
        self.session = sessionmaker(self.engine, expire_on_commit=False)
        self._seed()

    def _seed(self) -> None:
        with self.session.begin() as s:
            for p in PLANS:
                if s.get(SubscriptionPlan, p["key"]) is None:
                    s.add(SubscriptionPlan(**p, active=False))
            if s.get(Organization, DEFAULT_ORG) is None:
                s.add(Organization(id=DEFAULT_ORG, name="JP-libau Holding", plan_key=None))

    def get_state(self, key: str, default=None):
        with self.session() as s:
            row = s.get(SystemState, key)
            return row.value if row else default

    def set_state(self, key: str, value: dict) -> None:
        with self.session.begin() as s:
            row = s.get(SystemState, key)
            if row:
                row.value, row.updated_at = value, utcnow()
            else:
                s.add(SystemState(key=key, value=value))

    def audit(self, actor: str, action: str, detail: dict | None = None, s: Session | None = None,
              org_id: int = DEFAULT_ORG) -> None:
        def add(sess: Session) -> None:
            # Hash-keten: elke regel bevat de hash van de vorige, zodat wijzigen of weghalen opvalt.
            prev = sess.scalars(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1)).first()
            ts = utcnow()
            body = json.dumps({"org": org_id, "ts": ts.isoformat(), "actor": actor, "action": action,
                               "detail": detail or {}, "prev": prev}, sort_keys=True, default=str)
            sess.add(AuditLog(org_id=org_id, ts=ts, actor=actor, action=action, detail=detail or {}, prev_hash=prev,
                              hash=hashlib.sha256(body.encode()).hexdigest()))
            sess.flush()
        if s is not None:
            add(s)
            return
        with self.session.begin() as s2:
            add(s2)

    def verify_audit_chain(self) -> dict:
        """Controleert de hele keten. Geeft het eerste gebroken id terug als er iets gewijzigd is."""
        with self.session() as s:
            prev = None
            n = 0
            for r in s.scalars(select(AuditLog).order_by(AuditLog.id)):
                if r.hash is None:          # regels van vóór de hash-keten
                    prev = None
                    continue
                body = json.dumps({"org": r.org_id, "ts": iso(r.ts), "actor": r.actor, "action": r.action,
                                   "detail": r.detail, "prev": r.prev_hash}, sort_keys=True, default=str)
                if r.prev_hash != prev or hashlib.sha256(body.encode()).hexdigest() != r.hash:
                    return {"ok": False, "broken_at": r.id, "checked": n}
                prev = r.hash
                n += 1
            return {"ok": True, "checked": n}

    def audit_entries(self, limit: int = 100, org_id: int = DEFAULT_ORG) -> list[dict]:
        with self.session() as s:
            rows = s.scalars(select(AuditLog).where(AuditLog.org_id == org_id)
                             .order_by(AuditLog.id.desc()).limit(limit)).all()
            return [{"id": r.id, "ts": iso(r.ts), "actor": r.actor, "action": r.action,
                     "detail": r.detail} for r in rows]


def upgrade(url: str) -> None:
    """Database naar de nieuwste migratie brengen (Alembic)."""
    from alembic import command
    from alembic.config import Config
    here = Path(__file__).resolve().parent
    cfg = Config()
    cfg.set_main_option("script_location", str(here / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")


class ProviderCheck(Base):
    """Eén echte verbindingstest met een externe bron. Geen sleutel = geen verzoek, en dat staat er ook zo."""

    __tablename__ = "provider_checks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(48), index=True)
    status: Mapped[str] = mapped_column(String(16))                 # ok, error, not_configured
    error_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    checked_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)


class AiCall(Base):
    """Elke aanroep via de AI Gateway: welke taak, welk model, hoe lang, wat het kostte en of het lukte."""

    __tablename__ = "ai_calls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task: Mapped[str] = mapped_column(String(48), index=True)
    provider: Mapped[str] = mapped_column(String(24), index=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16))                 # ok, error, skipped
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)


class Debate(Base):
    """Gestructureerde review van een onderzoeksbesluit door meerdere modellen plus vaste code."""

    __tablename__ = "debates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject: Mapped[str] = mapped_column(String(200))
    ref: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)   # bv. hypothesis:3
    status: Mapped[str] = mapped_column(String(16))                 # done, partial, unavailable
    author_provider: Mapped[str | None] = mapped_column(String(24), nullable=True)
    challenger_provider: Mapped[str | None] = mapped_column(String(24), nullable=True)
    independent: Mapped[bool] = mapped_column(Boolean, default=False)
    steps: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)


class NewsLabel(Base):
    """Onafhankelijk label (door de CEO of een andere mens, niet door de ontwikkelaar) voor een echt nieuwsbericht."""

    __tablename__ = "news_labels"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    news_id: Mapped[int] = mapped_column(ForeignKey("news_events.id"), index=True)
    label: Mapped[str] = mapped_column(String(32))
    labeller: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    __table_args__ = (UniqueConstraint("news_id", "labeller", name="uq_news_label"),)


class EventWorkflow(Base):
    """Eén nieuwsgebeurtenis door de hele organisatie: elke stap met tijd, bron en status (trace-id)."""

    __tablename__ = "event_workflows"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(40), unique=True)
    news_id: Mapped[int] = mapped_column(ForeignKey("news_events.id"), unique=True)
    status: Mapped[str] = mapped_column(String(16))                 # running, done, partial, failed
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    intelligence: Mapped[dict] = mapped_column(JSON, default=dict)
    steps: Mapped[list] = mapped_column(JSON, default=list)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)

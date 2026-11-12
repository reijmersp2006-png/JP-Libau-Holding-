"""Opslag van NEXUS zelf (los van de boekhouding van de holding).

Fase 1 gebruikt deze tabellen. Het volledige doel-schema voor PostgreSQL/TimescaleDB
(koersen, orders, fills, backtests, agent-runs) staat in ``docs/schema.sql``.
Standaard draait dit op SQLite; zet ``NEXUS_DATABASE_URL`` op een PostgreSQL-URL voor productie.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def iso(ts: datetime) -> str:
    """SQLite bewaart geen tijdzone; alles wat we opslaan is UTC."""
    return (ts if ts.tzinfo else ts.replace(tzinfo=UTC)).isoformat()


class Base(DeclarativeBase):
    pass


class SystemState(Base):
    """Sleutel-waarde voor de besturing: handelsmodus, noodstop."""

    __tablename__ = "system_state"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    """Alles wat de besturing verandert, wie het deed en waarom. Alleen toevoegen, nooit wijzigen."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class TradeProposal(Base):
    """Een handelsvoorstel met alle verplichte velden (zie ``proposals.TradeProposalIn``)."""

    __tablename__ = "trade_proposals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    source: Mapped[str] = mapped_column(String(64))          # wie stelde het voor (agent-id of "manual")
    asset_class: Mapped[str] = mapped_column(String(16))
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    direction: Mapped[str] = mapped_column(String(8))
    strategy_id: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)                # het volledige voorstel
    status: Mapped[str] = mapped_column(String(16), index=True)  # approved_by_guardian | vetoed
    executed: Mapped[bool] = mapped_column(Boolean, default=False)  # fase 1: altijd False


class RiskEvaluation(Base):
    """Het oordeel van de Risk Guardian, met elke check. Hoort bij precies één voorstel."""

    __tablename__ = "risk_evaluations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proposal_id: Mapped[int] = mapped_column(Integer, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    approved: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(Text)
    checks: Mapped[list] = mapped_column(JSON)
    limits_snapshot: Mapped[dict] = mapped_column(JSON)


class Database:
    def __init__(self, url: str) -> None:
        kw: dict = {}
        if url.startswith("sqlite"):
            kw["connect_args"] = {"check_same_thread": False}
            if ":memory:" in url:
                kw["poolclass"] = StaticPool       # één gedeelde verbinding, anders is elke thread leeg
        self.engine = create_engine(url, future=True, **kw)
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(self.engine, expire_on_commit=False)

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

    def audit(self, actor: str, action: str, detail: dict | None = None, s: Session | None = None) -> None:
        entry = AuditLog(actor=actor, action=action, detail=detail or {})
        if s is not None:
            s.add(entry)
            return
        with self.session.begin() as s2:
            s2.add(entry)

    def audit_entries(self, limit: int = 100) -> list[dict]:
        with self.session() as s:
            rows = s.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)).all()
            return [{"id": r.id, "ts": iso(r.ts), "actor": r.actor, "action": r.action,
                     "detail": r.detail} for r in rows]

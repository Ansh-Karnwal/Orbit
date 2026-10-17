"""Owner: Victor. SQLAlchemy 2 (sync) tables on SQLite (WAL). Only repo.py should import this."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import (JSON, Boolean, DateTime, Engine, ForeignKey, Index, Integer, String, Text,
                        TypeDecorator, UniqueConstraint, create_engine, event)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.config import get_settings


class UTCDateTime(TypeDecorator):
    """Stores naive UTC in SQLite, always returns tz-aware UTC. Rejects naive input."""
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime; all timestamps must be tz-aware UTC")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    type_annotation_map = {datetime: UTCDateTime, dict[str, Any]: JSON, list[Any]: JSON}


def _task_fk() -> Any:
    return ForeignKey("tasks.id")


class TaskRow(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    outcome_text: Mapped[str] = mapped_column(Text)
    constraints: Mapped[dict[str, Any]]
    limits: Mapped[dict[str, Any]]
    mode: Mapped[str]
    status: Mapped[str] = mapped_column(index=True)
    status_reason: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(default="manual")
    creao_ref: Mapped[str | None]
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class ProviderRow(Base):
    __tablename__ = "providers"
    task_id: Mapped[str] = mapped_column(_task_fk(), primary_key=True)
    id: Mapped[str] = mapped_column(primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str]
    channel: Mapped[str]
    handle: Mapped[str] = mapped_column(index=True)
    portal_url: Mapped[str | None]


class FactRow(Base):
    __tablename__ = "facts"
    __table_args__ = (UniqueConstraint("task_id", "key", "version", name="uq_facts_task_key_ver"),)
    id: Mapped[str] = mapped_column(primary_key=True)
    task_id: Mapped[str] = mapped_column(_task_fk())
    key: Mapped[str]
    value: Mapped[Any] = mapped_column(JSON)
    currency: Mapped[str | None]
    scope: Mapped[str | None]
    source_id: Mapped[str]
    observed_at: Mapped[datetime]
    valid_until: Mapped[datetime | None]
    status: Mapped[str]
    version: Mapped[int]
    supersedes: Mapped[str | None]


class StepRow(Base):
    __tablename__ = "steps"
    id: Mapped[str] = mapped_column(primary_key=True)
    task_id: Mapped[str] = mapped_column(_task_fk(), index=True)
    kind: Mapped[str]
    provider_id: Mapped[str | None]
    depends_on: Mapped[list[Any]]
    state: Mapped[str]
    attempts: Mapped[int]
    max_attempts: Mapped[int]
    idempotency_key: Mapped[str] = mapped_column(index=True)
    not_before: Mapped[datetime | None]
    result: Mapped[dict[str, Any] | None]
    error: Mapped[str | None] = mapped_column(Text)
    plan_version: Mapped[int]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class ActionRow(Base):
    __tablename__ = "actions"
    id: Mapped[str] = mapped_column(primary_key=True)
    task_id: Mapped[str] = mapped_column(_task_fk(), index=True)
    step_id: Mapped[str]
    adapter: Mapped[str]
    operation: Mapped[str]
    idempotency_key: Mapped[str] = mapped_column(unique=True)
    request: Mapped[dict[str, Any]]
    status: Mapped[str]
    provider_ref: Mapped[str | None]
    result: Mapped[dict[str, Any] | None]
    evidence_ids: Mapped[list[Any]]
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]


class InboundRow(Base):
    __tablename__ = "inbound_events"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_inbound_source_ext"),)
    id: Mapped[str] = mapped_column(primary_key=True)
    source: Mapped[str]
    external_id: Mapped[str]
    task_id: Mapped[str | None] = mapped_column(_task_fk(), index=True)
    provider_id: Mapped[str | None]
    sender_handle: Mapped[str | None]
    text: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]]
    received_at: Mapped[datetime]
    processed: Mapped[bool] = mapped_column(Boolean, default=False)


class ApprovalRow(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(primary_key=True)
    task_id: Mapped[str] = mapped_column(_task_fk(), index=True)
    proposal: Mapped[dict[str, Any]]
    proposal_hash: Mapped[str]
    status: Mapped[str]
    approver: Mapped[str | None]
    requested_at: Mapped[datetime]
    decided_at: Mapped[datetime | None]
    expires_at: Mapped[datetime | None]
    invalidated_reason: Mapped[str | None] = mapped_column(Text)


class EvidenceRow(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(primary_key=True)
    task_id: Mapped[str] = mapped_column(_task_fk(), index=True)
    kind: Mapped[str]
    source: Mapped[str]
    uri: Mapped[str | None]
    mime_type: Mapped[str | None]
    sha256: Mapped[str | None]
    extracted: Mapped[dict[str, Any]]
    claim_level: Mapped[str | None]
    is_fixture: Mapped[bool] = mapped_column(Boolean)
    provider_ref: Mapped[str | None]
    captured_at: Mapped[datetime]


class VerificationRow(Base):
    __tablename__ = "verifications"
    id: Mapped[str] = mapped_column(primary_key=True)
    task_id: Mapped[str] = mapped_column(_task_fk(), index=True)
    approval_id: Mapped[str | None]
    predicates: Mapped[list[Any]]
    verdict: Mapped[str]
    explanation: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


class TimelineRow(Base):
    __tablename__ = "timeline"
    __table_args__ = (UniqueConstraint("task_id", "seq", name="uq_timeline_task_seq"),)
    id: Mapped[str] = mapped_column(primary_key=True)
    task_id: Mapped[str] = mapped_column(_task_fk())
    seq: Mapped[int]
    type: Mapped[str]
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]]
    at: Mapped[datetime]


class BudgetCounterRow(Base):
    __tablename__ = "budget_counters"
    task_id: Mapped[str] = mapped_column(_task_fk(), primary_key=True)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)


Index("ix_facts_task_key_version", FactRow.task_id, FactRow.key, FactRow.version)


# ---------------------------------------------------------------- engine / sessions
_engine: Engine | None = None
_sessionmaker: sessionmaker[Session] | None = None


def _make_engine(url: str) -> Engine:
    if url.startswith("sqlite:///") and not url.endswith(":memory:"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):
        # Take over transaction control from pysqlite so we can BEGIN IMMEDIATE (see _on_begin).
        dbapi_conn.isolation_level = None
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn):
        # Write lock up front: read-then-write sequences (seq allocation, version bumps,
        # dedup) can't interleave across threads, and never hit SQLITE_BUSY on upgrade.
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


def init_db(url: str | None = None) -> None:
    """Create (or reuse) the engine for `url` (default: settings.database_url) and create tables."""
    global _engine, _sessionmaker
    url = url or get_settings().database_url
    if _engine is None or str(_engine.url) != url:
        if _engine is not None:
            _engine.dispose()
        _engine = _make_engine(url)
        _sessionmaker = sessionmaker(_engine, expire_on_commit=False)
    Base.metadata.create_all(_engine)


def reset_db() -> None:
    """Drop and recreate every table (used by /demo/reset)."""
    if _engine is None:
        init_db()
    Base.metadata.drop_all(_engine)
    Base.metadata.create_all(_engine)


def session() -> Session:
    if _sessionmaker is None:
        init_db()
    return _sessionmaker()

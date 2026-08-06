"""Normalized layer — the ingest stage's output.

Every table maps 1:1 to a class (TECHSPEC decision). Timestamps are epoch-ms
UTC integers; unit-bearing columns are unit-named (`duration_ms`, `cost_usd`).
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sdl_flow_optimiser.models.base import JSON_VARIANT, Base


class Project(Base):
    """A repo identity; worktrees map to their main project via parent."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(200), unique=True)
    path: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(20), default="main")  # main | worktree
    parent_project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)


class Session(Base):
    """One omp session transcript file."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    title_source: Mapped[str | None] = mapped_column(String(20), nullable=True)  # auto | manual
    started_at_ms: Mapped[int] = mapped_column(BigInteger, index=True)
    ended_at_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    file_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parsed_at_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    project: Mapped[Project] = relationship()
    events: Mapped[list[Event]] = relationship(back_populates="session", cascade="all, delete-orphan")


class Event(Base):
    """Lossless raw event, one row per JSONL record."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)  # order within the file
    type: Mapped[str] = mapped_column(String(50))
    ts_ms: Mapped[int] = mapped_column(BigInteger, index=True)
    raw_json: Mapped[dict[str, object]] = mapped_column(JSON_VARIANT)

    session: Mapped[Session] = relationship(back_populates="events")

    __table_args__ = (Index("ix_events_session_seq", "session_id", "seq"),)


class AssistantCall(Base):
    """An LLM completion: service time, tokens, cost. `interrupted` marks
    "Interrupted by user" stop reasons — a real stall signal."""

    __tablename__ = "assistant_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    ts_ms: Mapped[int] = mapped_column(BigInteger)
    model: Mapped[str] = mapped_column(String(200))
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cache_read: Mapped[int] = mapped_column(Integer, default=0)
    cache_write: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    interrupted: Mapped[bool] = mapped_column(Boolean, default=False)


class ToolExecution(Base):
    """One tool call, resolved from the 3-event join (toolCall in the
    assistant message → tool_execution_start → toolResult) at ingest."""

    __tablename__ = "tool_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    tool_call_id: Mapped[str] = mapped_column(String(100), index=True)
    tool_name: Mapped[str] = mapped_column(String(100))
    intent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    args_json: Mapped[dict[str, object] | None] = mapped_column(JSON_VARIANT, nullable=True)
    started_at_ms: Mapped[int] = mapped_column(BigInteger)
    finished_at_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    wall_time_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_error: Mapped[bool] = mapped_column(Boolean, default=False)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)


class UserMessage(Base):
    """User inputs, kept verbatim — text is the embedding/linkage source."""

    __tablename__ = "user_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    ts_ms: Mapped[int] = mapped_column(BigInteger)
    text: Mapped[str] = mapped_column(Text)


class IngestRun(Base):
    """Audit row for one ingest pass: coverage is reported, never silent."""

    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at_ms: Mapped[int] = mapped_column(BigInteger)
    ended_at_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    files_seen: Mapped[int] = mapped_column(Integer, default=0)
    files_parsed: Mapped[int] = mapped_column(Integer, default=0)
    files_skipped: Mapped[int] = mapped_column(Integer, default=0)
    coverage_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)


class IngestManifest(Base):
    """Per-file parse state — what makes re-runs incremental."""

    __tablename__ = "ingest_manifests"

    file_path: Mapped[str] = mapped_column(String(1000), primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64))
    parsed_at_ms: Mapped[int] = mapped_column(BigInteger)
    ingest_run_id: Mapped[int | None] = mapped_column(ForeignKey("ingest_runs.id"), nullable=True)

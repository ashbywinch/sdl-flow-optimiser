"""Derived layer — classifier, segmentation, metrics, recommendations, findings.

Recomputable per analysis run; never touches the normalized layer's raw
fidelity. `AnalysisRun` is the spine: everything below references it, which is
what makes the V2 dashboard a time series over runs.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sdl_flow_optimiser.models.base import JSON_VARIANT, Base


class PhaseDefinition(Base):
    """The 8 user-defined phases + classifier rule signatures, versioned."""

    __tablename__ = "phase_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    version: Mapped[str] = mapped_column(String(20))
    rules_json: Mapped[dict[str, object]] = mapped_column(JSON_VARIANT)


class PhaseAssignment(Base):
    """One event → phase with confidence and the classifier that decided."""

    __tablename__ = "phase_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    phase_id: Mapped[int] = mapped_column(ForeignKey("phase_definitions.id"))
    confidence: Mapped[float] = mapped_column(Float)
    classifier: Mapped[str] = mapped_column(String(30))  # rule | embedding | combined


class ClassifierEval(Base):
    """S1 output: precision/recall per phase per classifier on the labeled sample."""

    __tablename__ = "classifier_evals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phase_id: Mapped[int] = mapped_column(ForeignKey("phase_definitions.id"))
    classifier: Mapped[str] = mapped_column(String(30))
    precision: Mapped[float] = mapped_column(Float)
    recall: Mapped[float] = mapped_column(Float)
    sample_size: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class WorkItem(Base):
    """A unit of work. kind: session (v1) | doc_linked | pr (if S2 proves feasible)."""

    __tablename__ = "work_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="session")
    session_ids: Mapped[list[str]] = mapped_column(JSON_VARIANT)  # one or more sessions
    started_at_ms: Mapped[int] = mapped_column(BigInteger)
    ended_at_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | done | merged

    phases: Mapped[list[WorkItemPhase]] = relationship(back_populates="work_item", cascade="all, delete-orphan")


class WorkItemPhase(Base):
    """The phase *walk* per item — repeats and non-linear order are native."""

    __tablename__ = "work_item_phases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    work_item_id: Mapped[int] = mapped_column(ForeignKey("work_items.id"), index=True)
    phase_id: Mapped[int] = mapped_column(ForeignKey("phase_definitions.id"))
    position: Mapped[int] = mapped_column(Integer)  # 0-based order within the item
    started_at_ms: Mapped[int] = mapped_column(BigInteger)
    ended_at_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    work_item: Mapped[WorkItem] = relationship(back_populates="phases")


class IdleGap(Base):
    """Raw gap duration; stored, never interpreted — except task_switch,
    set when the gap overlaps activity in another session (user decision)."""

    __tablename__ = "idle_gaps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    started_at_ms: Mapped[int] = mapped_column(BigInteger)
    ended_at_ms: Mapped[int] = mapped_column(BigInteger)
    duration_ms: Mapped[int] = mapped_column(BigInteger)
    task_switch: Mapped[bool] = mapped_column(Boolean, default=False)
    overlapping_session_ids: Mapped[list[str] | None] = mapped_column(JSON_VARIANT, nullable=True)


class WorkItemLink(Base):
    """work_item → work_item: doc_reference | embedding | pr, with evidence."""

    __tablename__ = "work_item_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_work_item_id: Mapped[int] = mapped_column(ForeignKey("work_items.id"), index=True)
    to_work_item_id: Mapped[int] = mapped_column(ForeignKey("work_items.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # doc_reference | embedding | pr
    evidence: Mapped[dict[str, object] | None] = mapped_column(JSON_VARIANT, nullable=True)
    confidence: Mapped[float] = mapped_column(Float)


class DocReference(Base):
    """Raw doc-written → doc-read evidence feeding WorkItemLink (S3)."""

    __tablename__ = "doc_references"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    to_session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    path: Mapped[str] = mapped_column(String(1000))
    ts_ms: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(20))  # written | read


class PR(Base):
    """Pull request — the review-queue item. Only populated if S2 proves
    attribution feasible. Links to its work item so the review loop is part
    of the work item's phase walk (the bottleneck metric needs this)."""

    __tablename__ = "prs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    work_item_id: Mapped[int | None] = mapped_column(ForeignKey("work_items.id"), nullable=True, index=True)
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    opened_at_ms: Mapped[int] = mapped_column(BigInteger)
    merged_at_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    state: Mapped[str] = mapped_column(String(20), default="open")
    source_confidence: Mapped[float] = mapped_column(Float)


class AnalysisRun(Base):
    """The spine: one row per pipeline run; the V2 dashboard plots runs."""

    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at_ms: Mapped[int] = mapped_column(BigInteger)
    ended_at_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | done | failed


class Metric(Base):
    """One measured value per project × time bucket per run, with confidence."""

    __tablename__ = "metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analysis_run_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    bucket: Mapped[str | None] = mapped_column(String(30), nullable=True)  # e.g. 2026-W32
    name: Mapped[str] = mapped_column(String(100))
    value: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    sources_json: Mapped[dict[str, object] | None] = mapped_column(JSON_VARIANT, nullable=True)


class PhaseSequence(Base):
    """An SDLC "version" in evidence: a distinct phase walk, with its count."""

    __tablename__ = "phase_sequences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analysis_run_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    bucket: Mapped[str | None] = mapped_column(String(30), nullable=True)
    sequence: Mapped[list[int]] = mapped_column(JSON_VARIANT)  # ordered phase ids
    count: Mapped[int] = mapped_column(Integer)


class Bottleneck(Base):
    """The identified constraint per run: phase, queue, utilization, evidence."""

    __tablename__ = "bottlenecks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analysis_run_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    phase_id: Mapped[int | None] = mapped_column(ForeignKey("phase_definitions.id"), nullable=True)
    evidence_json: Mapped[dict[str, object]] = mapped_column(JSON_VARIANT)
    queue_length: Mapped[float | None] = mapped_column(Float, nullable=True)
    utilization: Mapped[float | None] = mapped_column(Float, nullable=True)


class Recommendation(Base):
    """The single highest-impact actionable change, with evidence refs."""

    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analysis_run_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    target: Mapped[str] = mapped_column(String(200))  # what to change
    expected_impact: Mapped[str] = mapped_column(String(500))
    rationale: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[dict[str, object]] = mapped_column(JSON_VARIANT)
    status: Mapped[str] = mapped_column(String(20), default="proposed")  # proposed | adopted | declined


class CandidateLever(Base):
    """Ranked alternatives behind the recommendation (advisory only)."""

    __tablename__ = "candidate_levers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recommendation_id: Mapped[int] = mapped_column(ForeignKey("recommendations.id"), index=True)
    lever: Mapped[str] = mapped_column(String(200))
    rank: Mapped[int] = mapped_column(Integer)
    impact_score: Mapped[float] = mapped_column(Float)
    feasibility: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)


class Finding(Base):
    """Investigation output: question → answer, evidence, confidence. Gating:
    unresolved findings mark dependent metrics' confidence as unvalidated."""

    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question: Mapped[str] = mapped_column(String(500))
    answer: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[dict[str, object] | None] = mapped_column(JSON_VARIANT, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | resolved

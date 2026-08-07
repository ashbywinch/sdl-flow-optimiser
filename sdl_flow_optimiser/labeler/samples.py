"""Adjudicable phase selection — from committed evidence files, no store.

A sample is one phase (the unit the human judges): its opening words, its
predicted phase, and the human's ground-truth label where one exists.
Sampling kinds: random, low-confidence (confidence < 0.5, the "needs eyes"
bucket), disagreements (classifier vs ground truth). Every phase is
adjudicable — there is no delegation concept at phase level.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TypedDict

from sdl_flow_optimiser.findings.attribution_feasibility import dump_rows, load_ground_truth

LOW_CONFIDENCE_CUTOFF = 0.5


class Sample(TypedDict):
    phase_id: str
    session: str
    session_id: str
    user: str
    pred_phase: int
    confidence: float
    truth_phase: int | None
    tools: int


@dataclass(frozen=True)
class SampleCounts:
    """The adjudication buckets: how many phases need eyes, and how many
    already carry the human's label."""

    total: int
    lowconf: int
    disagreements: int
    labeled: int


@dataclass(frozen=True)
class SamplePartition:
    """All phases split by adjudication need."""

    lowconf: list[Sample]
    disagreements: list[Sample]


def build_samples() -> list[Sample]:
    """All sample phases with predictions and the human's labels where they
    exist. Deterministic: committed files only."""
    ground_truth = load_ground_truth()
    samples: list[Sample] = []
    for row in dump_rows():
        samples.append(
            {
                "phase_id": row.phase_id,
                "session": row.label,
                "session_id": row.session,
                "user": row.user,
                "pred_phase": row.pred_phase,
                "confidence": row.confidence,
                "truth_phase": ground_truth.get(row.phase_id),
                "tools": len(row.calls),
            }
        )
    return samples


def _partition(all_samples: list[Sample]) -> SamplePartition:
    lowconf = [s for s in all_samples if s["confidence"] < LOW_CONFIDENCE_CUTOFF]
    disagreements = [s for s in all_samples if s["truth_phase"] is not None and s["truth_phase"] != s["pred_phase"]]
    return SamplePartition(lowconf=lowconf, disagreements=disagreements)


def _pool_for(kind: str, all_samples: list[Sample]) -> list[Sample]:
    """The sample pool for a sampling kind: all phases, or the low-confidence
    / disagreement adjudication buckets."""
    if kind == "all":
        return all_samples
    partition = _partition(all_samples)
    if kind == "lowconf":
        return partition.lowconf
    if kind == "disagreements":
        return partition.disagreements
    if kind == "random":
        return all_samples
    raise ValueError(f"unknown sampling kind: {kind}")


def select_samples(kind: str, n: int, seed: int | None = None) -> list[Sample]:
    """Pick n phases of the given kind. random is seeded for reproducibility
    when a seed is given (tests); the web UI leaves it unseeded."""
    pool = _pool_for(kind, build_samples())
    if seed is not None:
        rng = random.Random(seed)
        return rng.sample(pool, min(n, len(pool)))
    return random.sample(pool, min(n, len(pool)))


def sample_counts() -> SampleCounts:
    all_samples = build_samples()
    partition = _partition(all_samples)
    labeled = sum(1 for s in all_samples if s["truth_phase"] is not None)
    return SampleCounts(
        total=len(all_samples),
        lowconf=len(partition.lowconf),
        disagreements=len(partition.disagreements),
        labeled=labeled,
    )

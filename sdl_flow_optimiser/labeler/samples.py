"""Adjudicable sample selection — from committed evidence files, no store.

A sample is one tool execution with its predicted phase, confidence, and the
analyst's ground-truth label. Sampling kinds: random, low-confidence
(confidence < 0.5, the "needs eyes" bucket), disagreements (classifier vs
ground truth). Delegation events are excluded from adjudication — their
phase is inherited, not judged.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any, TypedDict

from sdl_flow_optimiser.findings.attribution_feasibility import DumpRow, dump_rows, load_ground_truth, sample_execs
from sdl_flow_optimiser.findings.labels import Labels
from sdl_flow_optimiser.phase_attribution import classify_with_context

LOW_CONFIDENCE_CUTOFF = 0.5


class Sample(TypedDict):
    call_id: str
    session: str
    session_id: str
    tool: str
    intent: str
    args: str
    pred_phase: int
    confidence: float
    delegation: bool
    truth_phase: int
    label: dict[str, Any] | None


@dataclass(frozen=True)
class SampleCounts:
    """The adjudication buckets: how many samples need eyes, and how many
    already have the analyst's label."""

    total: int
    lowconf: int
    disagreements: int
    labeled: int


def build_samples() -> list[Sample]:
    """All adjudicable samples with predictions, grouped per session for
    context-aware classification. Deterministic: committed files only."""
    ground_truth = load_ground_truth()
    labels = Labels().latest_labels_map()
    by_session: dict[str, list[DumpRow]] = defaultdict(list)
    for row in dump_rows():
        by_session[row.label].append(row)
    samples: list[Sample] = []
    for execs in by_session.values():
        sampled = sample_execs(execs)
        for ex, classified in zip(sampled, classify_with_context(sampled), strict=True):
            truth = ground_truth.get(ex.call_id)
            if truth is None:
                continue
            samples.append(
                {
                    "call_id": ex.call_id,
                    "session": ex.label,
                    "session_id": ex.session,
                    "tool": ex.tool,
                    "intent": ex.intent,
                    "args": ex.args,
                    "pred_phase": classified.prediction.phase_id,
                    "confidence": round(classified.prediction.confidence, 2),
                    "delegation": classified.delegation,
                    "truth_phase": truth,
                    "label": asdict(labels[ex.call_id]) if ex.call_id in labels else None,
                }
            )
    return samples


@dataclass(frozen=True)
class SamplePartition:
    """All samples split by adjudication need."""

    adjudicable: list[Sample]
    lowconf: list[Sample]
    disagreements: list[Sample]


def _partition(all_samples: list[Sample]) -> SamplePartition:
    adjudicable = [s for s in all_samples if not s["delegation"]]
    lowconf = [s for s in adjudicable if s["confidence"] < LOW_CONFIDENCE_CUTOFF]
    disagreements = [s for s in adjudicable if s["truth_phase"] != s["pred_phase"]]
    return SamplePartition(adjudicable=adjudicable, lowconf=lowconf, disagreements=disagreements)


def _pool_for(kind: str, all_samples: list[Sample]) -> list[Sample]:
    """The sample pool for a sampling kind. random excludes delegation;
    lowconf and disagreements are the adjudication buckets; all is raw."""
    if kind == "all":
        return all_samples
    partition = _partition(all_samples)
    if kind == "lowconf":
        return partition.lowconf
    if kind == "disagreements":
        return partition.disagreements
    if kind == "random":
        return partition.adjudicable
    raise ValueError(f"unknown sampling kind: {kind}")


def select_samples(kind: str, n: int, seed: int | None = None) -> list[Sample]:
    """Pick n samples of the given kind. random is seeded for reproducibility
    when a seed is given (tests); the web UI leaves it unseeded."""
    pool = _pool_for(kind, build_samples())
    if seed is not None:
        rng = random.Random(seed)
        return rng.sample(pool, min(n, len(pool)))
    return random.sample(pool, min(n, len(pool)))


def sample_counts() -> SampleCounts:
    all_samples = build_samples()
    partition = _partition(all_samples)
    labeled = sum(1 for s in all_samples if s["label"])
    return SampleCounts(
        total=len(partition.adjudicable),
        lowconf=len(partition.lowconf),
        disagreements=len(partition.disagreements),
        labeled=labeled,
    )

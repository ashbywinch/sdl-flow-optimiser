"""Adjudicable sample selection — from committed evidence files, no store.

A sample is one tool execution with its predicted phase, confidence, and the
analyst's ground-truth label. Sampling kinds: random, low-confidence
(confidence < 0.5, the "needs eyes" bucket), disagreements (classifier vs
ground truth). Delegation events are excluded from adjudication — their
phase is inherited, not judged.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any, TypedDict

from sdl_flow_optimiser.findings.attribution_feasibility import (
    classify_with_context,
    load_ground_truth,
    sample_execs,
)
from sdl_flow_optimiser.labeler.labels import load_labels

DUMP_PATH = Path(__file__).resolve().parent.parent / "findings" / "s1_dump.jsonl"

LOW_CONFIDENCE_CUTOFF = 0.5


class Sample(TypedDict):
    call_id: str
    session: str
    tool: str
    intent: str
    args: str
    pred_phase: int
    confidence: float
    delegation: bool
    truth_phase: int
    label: dict[str, Any] | None


def _dump_rows() -> list[dict[str, str]]:
    return [json.loads(line) for line in DUMP_PATH.read_text(encoding="utf-8").splitlines()]


def build_samples() -> list[Sample]:
    """All adjudicable samples with predictions, grouped per session for
    context-aware classification. Deterministic: committed files only."""
    ground_truth = load_ground_truth()
    labels = load_labels()
    by_session: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in _dump_rows():
        by_session[row["label"]].append(row)
    samples: list[Sample] = []
    for execs in by_session.values():
        sampled = sample_execs(execs)
        for ex, (pred, delegation) in zip(sampled, classify_with_context(sampled), strict=True):
            truth = ground_truth.get(ex["call_id"])
            if truth is None:
                continue
            samples.append(
                {
                    "call_id": ex["call_id"],
                    "session": ex["label"],
                    "tool": ex["tool"],
                    "intent": ex["intent"],
                    "args": ex["args"],
                    "pred_phase": pred.phase_id,
                    "confidence": round(pred.confidence, 2),
                    "delegation": delegation,
                    "truth_phase": truth,
                    "label": labels.get(ex["call_id"]),
                }
            )
    return samples


def select_samples(kind: str, n: int, seed: int | None = None) -> list[Sample]:
    """Pick n samples of the given kind. random is seeded for reproducibility
    when a seed is given (tests); the web UI leaves it unseeded."""
    all_samples = build_samples()
    if kind == "all":
        pool = all_samples
    elif kind == "lowconf":
        pool = [s for s in all_samples if not s["delegation"] and s["confidence"] < LOW_CONFIDENCE_CUTOFF]
    elif kind == "disagreements":
        pool = [s for s in all_samples if not s["delegation"] and s["truth_phase"] != s["pred_phase"]]
    elif kind == "random":
        pool = [s for s in all_samples if not s["delegation"]]
    else:
        raise ValueError(f"unknown sampling kind: {kind}")
    if seed is not None:
        rng = random.Random(seed)
        return rng.sample(pool, min(n, len(pool)))
    return random.sample(pool, min(n, len(pool)))


def sample_counts() -> dict[str, int]:
    all_samples = build_samples()
    adjudicable = [s for s in all_samples if not s["delegation"]]
    lowconf = [s for s in adjudicable if s["confidence"] < LOW_CONFIDENCE_CUTOFF]
    disagreements = [s for s in adjudicable if s["truth_phase"] != s["pred_phase"]]
    return {
        "total": len(adjudicable),
        "lowconf": len(lowconf),
        "disagreements": len(disagreements),
        "labeled": sum(1 for s in all_samples if s["label"]),
    }

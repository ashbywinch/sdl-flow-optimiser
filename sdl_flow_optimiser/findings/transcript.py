"""Transcript extraction — the session as a readable conversation.

The session detail view renders the actual transcript: user messages, the
agent's text replies, and tool calls in order, each tool call carrying its
phase prediction, confidence, the analyst's label, and any user
adjudication. Thinking blocks and tool result payloads are dropped — they
are noise at transcript scale; tool results leave a thin marker.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sdl_flow_optimiser.findings.labels import Label
from sdl_flow_optimiser.phase_attribution import PhasePrediction, classify_with_context

# Harness-injected preamble: the opening "user" message in some sessions is
# a machine-generated prompt (code-review requests, file dumps) — huge and
# structured, not the user's voice. The user's real opening is short.
# Skip the FIRST user message when it exceeds this length.
PREAMBLE_MAX = 1500


@dataclass(frozen=True)
class Run:
    """A same-phase contiguous stretch of tool calls — the unit the user
    adjudicates. Individual tool calls are not judged: only a stretch in
    its chat context can be classified accurately."""

    run_id: str
    phase: int
    confidence: float
    start: int  # transcript item index (inclusive)
    end: int  # transcript item index (inclusive)
    call_ids: tuple[str, ...]
    first_intent: str


def compute_runs(items: list[dict[str, Any]], session_id: str) -> list[Run]:
    """Maximal consecutive same-phase tool-call stretches. Any non-tool-call
    item (a user or agent message) breaks contiguity and starts a new run.
    run_id is stable across reads of the same frozen session."""
    runs: list[Run] = []
    current: list[dict[str, Any]] = []
    current_start = -1
    current_phase: int | None = None
    for i, it in enumerate(items):
        if it["kind"] != "tool_call":
            if current:
                runs.append(_finish_run(current, current_start, session_id))
                current = []
                current_phase = None
            continue
        if current_phase is not None and it["pred_phase"] != current_phase:
            runs.append(_finish_run(current, current_start, session_id))
            current = []
        if not current:
            current_start = i
            current_phase = it["pred_phase"]
        current.append(it)
    if current:
        runs.append(_finish_run(current, current_start, session_id))
    return runs


def _finish_run(calls: list[dict[str, Any]], start: int, session_id: str) -> Run:
    phase = int(calls[0]["pred_phase"])
    confidence = max(float(c["confidence"]) for c in calls)
    end = start + len(calls) - 1
    return Run(
        run_id=f"{session_id}#{start}-{end}",
        phase=phase,
        confidence=confidence,
        start=start,
        end=end,
        call_ids=tuple(str(c["call_id"]) for c in calls),
        first_intent=str(calls[0].get("intent", "") or calls[0].get("tool", "")),
    )


def extract_transcript(path: Path) -> list[dict[str, Any]]:
    """One item per renderable event, in file order.

    Item kinds: user (your words), assistant (the agent's text), tool_call
    (classified), tool_result (marker only). The harness-injected opening
    prompt is dropped, not rendered.
    """
    items: list[dict[str, Any]] = []
    start_by_call: dict[str, dict[str, str]] = {}  # call_id -> intent/args from tool_execution_start
    first_user_seen = False
    with open(path, errors="replace") as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if o.get("type") == "message":
                m = o.get("message", {})
                role = m.get("role")
                if role == "user":
                    text = " ".join(
                        c.get("text", "")
                        for c in m.get("content", [])
                        if isinstance(c, dict) and c.get("type") == "text"
                    )
                    if text:
                        if not first_user_seen:
                            first_user_seen = True
                            if len(text) > PREAMBLE_MAX:
                                continue  # harness preamble, not the user's voice
                        items.append({"kind": "user", "text": text})
                elif role == "assistant":
                    for block in m.get("content", []):
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "text" and block.get("text"):
                            items.append({"kind": "assistant", "text": block["text"]})
                        elif block.get("type") == "toolCall":
                            items.append(
                                {
                                    "kind": "tool_call",
                                    "call_id": block.get("id", ""),
                                    "tool": block.get("name", ""),
                                    "args": json.dumps(block.get("arguments", {}), default=str)[:400],
                                }
                            )
                elif role == "toolResult":
                    items.append({"kind": "tool_result", "call_id": m.get("toolCallId", "")})
            elif o.get("type") == "custom" and o.get("customType") == "tool_execution_start":
                d = o.get("data", {})
                start_by_call[d.get("toolCallId", "")] = {
                    "intent": d.get("intent", ""),
                    "args": json.dumps(d.get("args", {}), default=str)[:400],
                }
    # merge execution metadata into tool_call items and classify in order
    tool_calls = [it for it in items if it["kind"] == "tool_call"]
    execs = [
        {
            "call_id": str(it["call_id"]),
            "tool": str(it["tool"]),
            "intent": str(start_by_call.get(it["call_id"], {}).get("intent", "")),
            "args": str(start_by_call.get(it["call_id"], {}).get("args", it["args"])),
        }
        for it in tool_calls
    ]
    preds: list[tuple[PhasePrediction, bool]] = classify_with_context(execs)
    by_call = {e["call_id"]: (p, d) for e, (p, d) in zip(execs, preds, strict=True)}
    for it in tool_calls:
        pred, delegation = by_call[it["call_id"]]
        it["intent"] = start_by_call.get(it["call_id"], {}).get("intent", "")
        it["pred_phase"] = pred.phase_id
        it["confidence"] = round(pred.confidence, 2)
        it["delegation"] = delegation
    return items


def annotate_transcript(
    items: list[dict[str, Any]],
    ground_truth: dict[str, int],
    labels: dict[str, Any],
) -> list[dict[str, Any]]:
    """Attach the analyst's label and the user's adjudication to tool calls."""
    for it in items:
        if it["kind"] == "tool_call":
            it["analyst_phase"] = ground_truth.get(it["call_id"])
            label = labels.get(it["call_id"])
            it["label"] = asdict(label) if isinstance(label, Label) else label
    return items

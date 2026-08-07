"""Transcript extraction — the session as a readable conversation.

The session detail view renders the actual transcript: user messages, the
agent's text replies, and tool calls in order, each tool call carrying its
phase prediction, confidence, the analyst's label, and any user
adjudication. Thinking blocks and tool result payloads are dropped — they
are noise at transcript scale; tool results leave a thin marker.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sdl_flow_optimiser.findings.attribution_feasibility import classify_with_context
from sdl_flow_optimiser.findings.labels import Label
from sdl_flow_optimiser.phase_attribution import PhasePrediction

# Harness-injected preamble: the opening "user" message in some sessions is
# a machine-generated prompt (code-review requests, file dumps) — huge and
# structured, not the user's voice. The user's real opening is short.
# Skip the FIRST user message when it exceeds this length.
PREAMBLE_MAX = 1500


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

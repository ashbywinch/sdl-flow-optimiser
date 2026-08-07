"""Transcript — the session read as a conversation.

The object the user reads and judges (registered in the object model):
user messages, the agent's text replies, and tool calls in order, each tool
call carrying its phase prediction, confidence, the analyst's label, and
any user adjudication. The class owns its items: from_session_file builds
them, annotate attaches the analyst's labels and user verdicts, runs()
segments into same-phase stretches. Thinking blocks and tool result
payloads are dropped — noise at transcript scale.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sdl_flow_optimiser.findings.labels import Label
from sdl_flow_optimiser.phase_attribution import Execution, classify_with_context

# Harness-injected preamble: the opening "user" message in some sessions is
# a machine-generated prompt (code-review requests, file dumps) — huge and
# structured, not the user's voice. The user's real opening is short.
# Skip the FIRST user message when it exceeds this length.
PREAMBLE_MAX = 1500


@dataclass
class TranscriptItem:
    """One event in the conversation. kind: user | assistant | tool_call |
    tool_result; tool_call items carry the phase classification and the
    analyst's adjudication."""

    kind: str
    text: str = ""
    call_id: str = ""
    tool: str = ""
    args: str = ""
    intent: str = ""
    pred_phase: int | None = None
    confidence: float = 0.0
    delegation: bool = False
    analyst_phase: int | None = None
    label: Label | None = None


@dataclass(frozen=True)
class ExecutionMeta:
    """Execution metadata captured by the harness at tool start: the agent's
    intent string and the serialized arguments."""

    intent: str
    args: str


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


class Transcript:
    """The session as a conversation, with classification and adjudication.

    Item kinds: user (your words), assistant (the agent's text), tool_call
    (classified), tool_result (marker only). The harness-injected opening
    prompt is dropped, not rendered.
    """

    def __init__(self, session_id: str, items: list[TranscriptItem]) -> None:
        self.session_id = session_id
        self.items = items

    @classmethod
    def from_session_file(cls, path: Path) -> Transcript:
        """Parse a session file into a classified transcript."""
        items: list[TranscriptItem] = []
        start_by_call: dict[str, ExecutionMeta] = {}  # call_id -> intent/args
        with open(path, errors="replace") as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cls._consume_line(o, items, start_by_call)
        # Harness preamble: the opening user message, when it is a huge
        # machine-generated prompt, is not the user's voice — drop it.
        for i, it in enumerate(items):
            if it.kind == "user":
                if len(it.text) > PREAMBLE_MAX:
                    del items[i]
                break
        transcript = cls(session_id=path.name, items=items)
        transcript._classify(start_by_call)
        return transcript

    @staticmethod
    def _user_text(m: Any) -> str:
        """The joined text of a user message (empty when none)."""
        return " ".join(
            c.get("text", "") for c in m.get("content", []) if isinstance(c, dict) and c.get("type") == "text"
        )

    @staticmethod
    def _assistant_items(m: Any) -> list[TranscriptItem]:
        """The text and tool-call items one assistant message contributes."""
        items: list[TranscriptItem] = []
        for block in m.get("content", []):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and block.get("text"):
                items.append(TranscriptItem(kind="assistant", text=block["text"]))
            elif block.get("type") == "toolCall":
                items.append(
                    TranscriptItem(
                        kind="tool_call",
                        call_id=block.get("id", ""),
                        tool=block.get("name", ""),
                        args=json.dumps(block.get("arguments", {}), default=str)[:400],
                    )
                )
        return items

    @classmethod
    def _consume_line(cls, o: Any, items: list[TranscriptItem], start_by_call: dict[str, ExecutionMeta]) -> None:
        """Append the items and execution metadata one session-file line
        contributes."""
        if o.get("type") != "message":
            if o.get("type") == "custom" and o.get("customType") == "tool_execution_start":
                d = o.get("data", {})
                start_by_call[d.get("toolCallId", "")] = ExecutionMeta(
                    intent=d.get("intent", ""),
                    args=json.dumps(d.get("args", {}), default=str)[:400],
                )
            return
        m = o.get("message", {})
        role = m.get("role")
        if role == "user":
            text = cls._user_text(m)
            if text:
                items.append(TranscriptItem(kind="user", text=text))
        elif role == "assistant":
            items.extend(cls._assistant_items(m))
        elif role == "toolResult":
            items.append(TranscriptItem(kind="tool_result", call_id=m.get("toolCallId", "")))

    def _classify(self, start_by_call: dict[str, ExecutionMeta]) -> None:
        """Merge execution metadata into tool_call items and classify in order."""
        tool_calls = [it for it in self.items if it.kind == "tool_call"]
        execs = [
            Execution(
                call_id=it.call_id,
                tool=it.tool,
                intent=start_by_call.get(it.call_id, ExecutionMeta("", "")).intent,
                args=start_by_call.get(it.call_id, ExecutionMeta("", it.args)).args or it.args,
            )
            for it in tool_calls
        ]
        classified = classify_with_context(execs)
        by_call = {e.call_id: c for e, c in zip(execs, classified, strict=True)}
        for it in tool_calls:
            result = by_call[it.call_id]
            it.intent = start_by_call.get(it.call_id, ExecutionMeta("", "")).intent
            it.pred_phase = result.prediction.phase_id
            it.confidence = round(result.prediction.confidence, 2)
            it.delegation = result.delegation

    def annotate(self, ground_truth: dict[str, int], labels: dict[str, Label]) -> None:
        """Attach the analyst's label and the user's adjudication to tool calls."""
        for it in self.items:
            if it.kind == "tool_call":
                it.analyst_phase = ground_truth.get(it.call_id)
                it.label = labels.get(it.call_id)

    def runs(self) -> list[Run]:
        """Maximal consecutive same-phase tool-call stretches. Any
        non-tool-call item (a user or agent message) breaks contiguity and
        starts a new run. run_id is stable across reads of the same frozen
        session."""
        runs: list[Run] = []
        current: list[TranscriptItem] = []
        current_start = -1
        current_phase: int | None = None
        for i, it in enumerate(self.items):
            if it.kind != "tool_call":
                if current:
                    runs.append(self._finish_run(current, current_start))
                    current = []
                    current_phase = None
                continue
            if current_phase is not None and it.pred_phase != current_phase:
                runs.append(self._finish_run(current, current_start))
                current = []
            if not current:
                current_start = i
                current_phase = it.pred_phase
            current.append(it)
        if current:
            runs.append(self._finish_run(current, current_start))
        return runs

    def _finish_run(self, calls: list[TranscriptItem], start: int) -> Run:
        phase = calls[0].pred_phase
        assert phase is not None, "run tool calls are always classified"  # runs() filters unclassified items
        confidence = max(float(c.confidence) for c in calls)
        end = start + len(calls) - 1
        return Run(
            run_id=f"{self.session_id}#{start}-{end}",
            phase=phase,
            confidence=confidence,
            start=start,
            end=end,
            call_ids=tuple(str(c.call_id) for c in calls),
            first_intent=str(calls[0].intent or calls[0].tool),
        )

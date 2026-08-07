"""Transcript — the session read as a conversation.

The object the user reads and judges (registered in the object model):
user messages, the agent's text replies, and tool calls in order, each
phase — the span from one user message to the next — carrying the
classification of the work the human was doing, and any user
adjudication. The class owns its items: from_session_file builds them,
annotate attaches the analyst's labels and user verdicts, runs()
segments into human-centric phases. Thinking blocks and tool result
payloads are dropped — noise at transcript scale.
"""

from __future__ import annotations

import json
from collections import Counter
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
class PhaseVote:
    """The phase a span's tool-call evidence points to, with the confidence
    of its best call."""

    phase_id: int
    confidence: float


@dataclass(frozen=True)
class Run:
    """A phase — the human's unit of work: the span of the chat from one
    user message to the next, classified by what the human was doing.
    The user adjudicates phases, not individual tool calls."""

    run_id: str
    phase: int
    confidence: float
    start: int  # transcript item index (inclusive) — the opening user message
    end: int  # transcript item index (inclusive)
    call_ids: tuple[str, ...]
    first_intent: str  # the user's opening message of the phase


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
        """Human-centric phases: the unit the user judges is the span of the
        chat from one user message to the next — what the human was doing.
        The agent's replies, tool results, and tool calls all belong to the
        current phase; only a new user message starts a new one. Phases
        with no tool evidence (a question answered) fold into the next
        phase. Adjacent phases with the same classification merge — the
        human stayed in one phase across several short messages. run_id is
        stable across reads of the same frozen session."""
        phases: list[Run] = []
        current: list[TranscriptItem] = []
        current_start = -1
        for i, it in enumerate(self.items):
            if it.kind == "user" and current and any(c.kind == "tool_call" for c in current):
                phases.append(self._finish_run(current, current_start))
                current = []
                current_start = i
            # conversation-only stretch: keep accumulating — it is part
            # of the work the next user message directs
            if not current:
                current_start = i
            current.append(it)
        if current and any(c.kind == "tool_call" for c in current):
            phases.append(self._finish_run(current, current_start))
        return self._merge_same_phase(phases)

    @staticmethod
    def _merge_same_phase(phases: list[Run]) -> list[Run]:
        """Join adjacent phases the classifier gives the same phase — one
        stretch of the human's work, not N cards that look identical."""
        merged: list[Run] = []
        for p in phases:
            if merged and merged[-1].phase == p.phase:
                prev = merged[-1]
                merged[-1] = Run(
                    run_id=prev.run_id,
                    phase=prev.phase,
                    confidence=max(prev.confidence, p.confidence),
                    start=prev.start,
                    end=p.end,
                    call_ids=prev.call_ids + p.call_ids,
                    first_intent=prev.first_intent,
                )
            else:
                merged.append(p)
        return merged

    @staticmethod
    def _majority_phase(calls: list[TranscriptItem]) -> PhaseVote:
        """The span's dominant phase among its non-delegation tool calls,
        with the confidence of the winning phase (its best call)."""
        votes = Counter(it.pred_phase for it in calls if not it.delegation)
        if not votes:
            votes = Counter(it.pred_phase for it in calls)
        if not votes:
            return PhaseVote(0, 0.0)
        phase_id, _count = votes.most_common(1)[0]
        assert phase_id is not None  # calls are filtered to classified items
        confidence = max((it.confidence for it in calls if it.pred_phase == phase_id), default=0.5)
        return PhaseVote(phase_id, confidence)

    @staticmethod
    def _phase_opener(items: list[TranscriptItem]) -> str:
        """The phase's opening intent: the user's first message, else the
        first tool's name."""
        user_text = next((it.text for it in items if it.kind == "user"), "")
        if user_text:
            return user_text[:200]
        return next((str(it.tool) for it in items if it.kind == "tool_call"), "")

    def _finish_run(self, items: list[TranscriptItem], start: int) -> Run:
        """One phase: the span's dominant phase among its non-delegation
        tool calls (the evidence of the work the human directed), the user's
        opening message as the phase's intent."""
        calls = [it for it in items if it.kind == "tool_call" and it.pred_phase is not None]
        vote = self._majority_phase(calls)
        end = start + len(items) - 1
        return Run(
            run_id=f"{self.session_id}#{start}-{end}",
            phase=vote.phase_id,
            confidence=vote.confidence,
            start=start,
            end=end,
            call_ids=tuple(str(it.call_id) for it in items if it.kind == "tool_call"),
            first_intent=self._phase_opener(items),
        )

"""Labeler web app — FastAPI backend + static frontend.

Run: make web (uvicorn on 127.0.0.1:8010). Local tool, no auth, JSON
persistence. The frontend is static files; the API serves samples, the
surrounding transcript context for each, and session association. Every
response is a named record — the coding standard's semantic types over
bare dicts — serialized by FastAPI to the same JSON the frontend consumes.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse

from sdl_flow_optimiser.findings.attribution_feasibility import STORE, dump_rows, extract_executions, load_ground_truth
from sdl_flow_optimiser.findings.labels import (
    ASSOCIATIONS_PATH,
    LABELS_PATH,
    Association,
    Label,
    Labels,
    RunVerdict,
)
from sdl_flow_optimiser.findings.transcript import Transcript, TranscriptItem
from sdl_flow_optimiser.labeler.samples import Sample, SampleCounts, build_samples, sample_counts, select_samples
from sdl_flow_optimiser.phase_attribution import PHASE_NAMES, classify_with_context

STATIC = Path(__file__).parent / "static"
WINDOW = 5
NO_CACHE = {"Cache-Control": "no-store"}


@dataclass
class ContextEvent:
    """One execution in the context window around a sample."""

    tool: str
    intent: str
    phase: int
    confidence: float
    this_sample: bool


@dataclass
class ContextResponse:
    """The events surrounding one sample, with paging flags."""

    session: str
    events: list[ContextEvent]
    more_before: bool
    more_after: bool


@dataclass
class RunDetail:
    """One activity run as the API reports it: the segment plus the user's
    verdict (None until adjudicated)."""

    run_id: str
    phase: int
    confidence: float
    start: int
    end: int
    call_count: int
    first_intent: str
    verdict: RunVerdict | None = None


@dataclass
class SessionDetail:
    """A whole session as a readable transcript: user messages, agent text,
    and classified tool calls in order. The session is the unit of work —
    this is the surf-and-judge surface."""

    id: str
    transcript: list[TranscriptItem]
    tool_calls: int
    runs: list[RunDetail]


@dataclass
class SessionSummary:
    """One row in the session list: identity, opening, and activity."""

    id: str
    repo: str
    repo_name: str
    title: str
    opening: str
    started_at: str
    ended_at: str
    tools: dict[str, int]
    user_messages: int
    agent_run: bool


def create_app(
    labels_path: Path = LABELS_PATH,
    associations_path: Path = ASSOCIATIONS_PATH,
) -> FastAPI:
    app = FastAPI(title="sdl-flow-optimiser labeler")
    stores = Labels(labels_path, associations_path)

    @app.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/app.js")
    def script() -> FileResponse:
        return FileResponse(STATIC / "app.js")

    @app.get("/api/sample-sets")
    def sample_sets() -> SampleCounts:
        return sample_counts()

    @app.get("/api/samples")
    def samples(kind: str = "random", n: int = 20, seed: int | None = None) -> list[Sample]:
        try:
            return select_samples(kind, n, seed)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/samples/{call_id}/context")
    def context(call_id: str, window: int = WINDOW, offset: int = 0) -> ContextResponse:
        """Surrounding events around one sample in its own session transcript."""
        rows = build_samples()
        sample = next((s for s in rows if s["call_id"] == call_id), None)
        if sample is None:
            raise HTTPException(status_code=404, detail="unknown call_id")
        session_file = next((r.session for r in dump_rows() if r.call_id == call_id), None)
        if session_file is None:
            raise HTTPException(status_code=404, detail="sample not in dump")
        path = next(
            (d / session_file for d in STORE.iterdir() if d.is_dir() and (d / session_file).exists()),
            None,
        )
        if path is None:
            raise HTTPException(status_code=404, detail="session file not on this machine")
        execs = extract_executions(path)
        index = next((i for i, e in enumerate(execs) if e.call_id == call_id), None)
        if index is None:
            raise HTTPException(status_code=404, detail="call not in this session")
        preds = classify_with_context(execs)
        lo = max(0, index - window - offset)
        hi = min(len(execs), index + window + 1 + offset)
        events = [
            ContextEvent(
                tool=e.tool,
                intent=e.intent,
                phase=classified.prediction.phase_id,
                confidence=round(classified.prediction.confidence, 2),
                this_sample=e.call_id == call_id,
            )
            for e, classified in zip(execs[lo:hi], preds[lo:hi], strict=True)
        ]
        return ContextResponse(
            session=sample["session"],
            events=events,
            more_before=lo > 0,
            more_after=hi < len(execs),
        )

    @app.post("/api/labels")
    def label(
        call_id: str = Body(...),
        agree: bool = Body(...),
        phase: int | None = Body(None),
        comment: str = Body(""),
    ) -> Label:
        if phase is not None and phase not in PHASE_NAMES:
            raise HTTPException(status_code=400, detail=f"phase must be one of {sorted(PHASE_NAMES)}")
        return stores.add_label(call_id, agree, phase, comment)

    @app.get("/api/sessions")
    def sessions() -> list[SessionSummary]:
        return _list_sessions()

    @app.get("/api/sessions/{session_id}")
    def session_detail(session_id: str) -> SessionDetail:
        """A whole session as a readable transcript: user messages, agent
        text, and classified tool calls in order. The session is the unit of
        work — this is the surf-and-judge surface."""
        path = next(
            (d / session_id for d in STORE.iterdir() if d.is_dir() and (d / session_id).exists()),
            None,
        )
        # containment: a crafted session_id (e.g. percent-encoded ../) must
        # not read files outside the store — the labeler is LAN-reachable
        if path is None or not path.resolve().is_relative_to(STORE.resolve()):
            raise HTTPException(status_code=404, detail="session not on this machine")
        transcript = Transcript.from_session_file(path)
        transcript.annotate(load_ground_truth(), stores.latest_labels_map())
        runs = transcript.runs()
        verdicts = stores.latest_run_verdicts()
        run_details = [
            RunDetail(
                run_id=r.run_id,
                phase=r.phase,
                confidence=r.confidence,
                start=r.start,
                end=r.end,
                call_count=len(r.call_ids),
                first_intent=r.first_intent,
                verdict=verdicts.get(r.run_id),
            )
            for r in runs
        ]
        return SessionDetail(
            id=session_id,
            transcript=transcript.items,
            tool_calls=sum(1 for it in transcript.items if it.kind == "tool_call"),
            runs=run_details,
        )

    @app.delete("/api/labels/{call_id}")
    def delete_label_endpoint(call_id: str) -> dict[str, bool]:
        """Undo an adjudication (append-only tombstone)."""
        stores.remove_label(call_id)
        return {"ok": True}

    @app.post("/api/runs/{run_id}/verdict")
    def run_verdict(run_id: str, phase: int = Body(...), comment: str = Body("")) -> RunVerdict:
        """The user's verdict on one activity run: the phase they say it was
        (defaults to the guess when they confirm)."""
        if phase not in PHASE_NAMES:
            raise HTTPException(status_code=400, detail=f"phase must be one of {sorted(PHASE_NAMES)}")
        return stores.add_run_verdict(run_id, phase, comment)

    @app.delete("/api/runs/{run_id}/verdict")
    def delete_run_verdict(run_id: str) -> dict[str, bool]:
        stores.remove_run_verdict(run_id)
        return {"ok": True}

    @app.get("/api/associations")
    def associations() -> list[Association]:
        return stores.associations()

    @app.post("/api/associations")
    def associate(a: str = Body(...), b: str = Body(...)) -> Association:
        if a == b:
            raise HTTPException(status_code=400, detail="cannot associate a session with itself")
        return stores.add_association(a, b)

    @app.delete("/api/associations")
    def remove_association_endpoint(a: str = Body(...), b: str = Body(...)) -> dict[str, bool]:
        """Remove a session pair (undo a mis-made association)."""
        stores.remove_association(a, b)
        return {"ok": True}

    return app


def _repo_display_name(dir_name: str) -> str:
    """Human-readable repo name from the store's hashed directory name:
    home-houses-<hash> -> houses; -Documents-code-chat-workflow ->
    chat-workflow; -.paseo-worktrees-<hash>-brave-spider -> worktree:
    brave-spider."""
    m = re.search(r"paseo-worktrees-[0-9a-z]+-(.+)$", dir_name)
    if m:
        return f"worktree: {m.group(1)}"
    name = dir_name
    fallback = dir_name
    for prefix, label in (("home-", ""), ("-Documents-code-", ""), ("tmp-tmp-", "tmp"), ("-", "")):
        if name.startswith(prefix):
            name = name[len(prefix) :]
            fallback = label or name
            break
    return re.sub(r"-?[0-9a-f]{32,}$", "", name) or fallback


@dataclass
class SessionScan:
    """Accumulated facts about one session file as its lines are read:
    title, opening user message, timestamps, first-10 tools."""

    title: str = ""
    first_user: str = ""
    started_at: str = ""
    ended_at: str = ""
    tools: list[str] = field(default_factory=list)
    user_messages: int = 0
    _first_user_seen: bool = False

    @staticmethod
    def _texts(m: Any) -> list[str]:
        """The text blocks of a message."""
        return [c.get("text", "") for c in m.get("content", []) if isinstance(c, dict) and c.get("type") == "text"]

    def _fold_message(self, m: Any) -> None:
        """A user message updates the opening (skipping a huge harness
        preamble) and the message count; other roles contribute nothing."""
        if m.get("role") != "user":
            return
        texts = self._texts(m)
        if texts and not self._first_user_seen:
            self._first_user_seen = True
            if len(texts[0]) > 1500:
                return  # harness-injected preamble — not the user's voice
        if texts:
            self.first_user = self.first_user or texts[0]
            self.user_messages += 1

    def _fold_custom(self, o: Any) -> None:
        """A tool execution start appends to the first-10 tool mix."""
        if o.get("customType") == "tool_execution_start" and len(self.tools) < 10:
            self.tools.append(o.get("data", {}).get("toolName", ""))

    def feed(self, o: Any) -> None:
        """Fold one parsed session-file line into the scan."""
        t = o.get("type")
        if t == "session" and not self.started_at:
            self.started_at = o.get("timestamp", "")
        elif t in ("title", "title_change") and not self.title:
            self.title = o.get("title", "")
        elif t == "message":
            self._fold_message(o.get("message", {}))
        elif t == "custom":
            self._fold_custom(o)
        ts = o.get("timestamp")
        if ts:
            self.ended_at = ts


def _list_sessions() -> list[SessionSummary]:
    """Every session in the store with its opening — the surf-and-associate
    list. Reads the store (this machine)."""
    sessions: list[SessionSummary] = []
    for d in sorted(STORE.iterdir()):
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*.jsonl")):
            scan = SessionScan()
            with open(path, errors="replace") as fh:
                for line in fh:
                    try:
                        o = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    scan.feed(o)
                    if scan.title and scan.first_user and scan.started_at and len(scan.tools) >= 10:
                        break
            sessions.append(
                SessionSummary(
                    id=path.name,
                    repo=d.name,
                    repo_name=_repo_display_name(d.name),
                    title=scan.title,
                    opening=scan.first_user[:160],
                    started_at=scan.started_at,
                    ended_at=scan.ended_at,
                    tools=dict(Counter(scan.tools).most_common(4)),
                    user_messages=scan.user_messages,
                    agent_run=scan.user_messages == 0,
                )
            )
    sessions.sort(key=lambda s: s.started_at)
    return sessions


app = create_app()

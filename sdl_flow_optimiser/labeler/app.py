"""Labeler web app — FastAPI backend + static frontend.

Run: make web (uvicorn on 127.0.0.1:8010). Local tool, no auth, JSON
persistence. The frontend is static files; the API serves samples, the
surrounding transcript context for each, and session association.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse

from sdl_flow_optimiser.findings.attribution_feasibility import (
    STORE,
    classify_with_context,
    extract_executions,
    load_ground_truth,
)
from sdl_flow_optimiser.labeler.labels import (
    ASSOCIATIONS_PATH,
    LABELS_PATH,
    delete_label,
    load_associations,
    load_labels,
    remove_association,
    save_association,
    save_label,
)
from sdl_flow_optimiser.labeler.samples import Sample, build_samples, sample_counts, select_samples
from sdl_flow_optimiser.labeler.transcript import annotate_transcript, extract_transcript
from sdl_flow_optimiser.phase_attribution import PHASE_NAMES

STATIC = Path(__file__).parent / "static"
WINDOW = 5
NO_CACHE = {"Cache-Control": "no-store"}


def create_app(
    labels_path: Path = LABELS_PATH,
    associations_path: Path = ASSOCIATIONS_PATH,
) -> FastAPI:
    app = FastAPI(title="sdl-flow-optimiser labeler")

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
    def sample_sets() -> dict[str, int]:
        return sample_counts()

    @app.get("/api/samples")
    def samples(kind: str = "random", n: int = 20, seed: int | None = None) -> list[Sample]:
        try:
            return select_samples(kind, n, seed)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/samples/{call_id}/context")
    def context(call_id: str, window: int = WINDOW, offset: int = 0) -> dict[str, Any]:
        """Surrounding events around one sample in its own session transcript."""
        rows = build_samples()
        sample = next((s for s in rows if s["call_id"] == call_id), None)
        if sample is None:
            raise HTTPException(status_code=404, detail="unknown call_id")
        session_file = next((r["session"] for r in _dump_rows() if r["call_id"] == call_id), None)
        if session_file is None:
            raise HTTPException(status_code=404, detail="sample not in dump")
        path = next(
            (d / session_file for d in STORE.iterdir() if d.is_dir() and (d / session_file).exists()),
            None,
        )
        if path is None:
            raise HTTPException(status_code=404, detail="session file not on this machine")
        execs = extract_executions(path)
        index = next((i for i, e in enumerate(execs) if e["call_id"] == call_id), None)
        if index is None:
            raise HTTPException(status_code=404, detail="call not in this session")
        preds = classify_with_context(execs)
        lo = max(0, index - window - offset)
        hi = min(len(execs), index + window + 1 + offset)
        events = [
            {
                "tool": e["tool"],
                "intent": e["intent"],
                "phase": pred[0].phase_id,
                "confidence": round(pred[0].confidence, 2),
                "this_sample": e["call_id"] == call_id,
            }
            for e, pred in zip(execs[lo:hi], preds[lo:hi], strict=True)
        ]
        return {
            "session": sample["session"],
            "events": events,
            "more_before": lo > 0,
            "more_after": hi < len(execs),
        }

    @app.post("/api/labels")
    def label(
        call_id: str = Body(...),
        agree: bool = Body(...),
        phase: int | None = Body(None),
        comment: str = Body(""),
    ) -> dict[str, Any]:
        if phase is not None and phase not in PHASE_NAMES:
            raise HTTPException(status_code=400, detail=f"phase must be one of {sorted(PHASE_NAMES)}")
        return save_label(call_id, agree, phase, comment, labels_path)

    @app.get("/api/sessions")
    def sessions() -> list[dict[str, Any]]:
        return _list_sessions()

    @app.get("/api/sessions/{session_id}")
    def session_detail(session_id: str) -> dict[str, Any]:
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
        items = extract_transcript(path)
        annotate_transcript(items, load_ground_truth(), load_labels(labels_path))
        tool_calls = [it for it in items if it["kind"] == "tool_call"]
        return {"id": session_id, "transcript": items, "tool_calls": len(tool_calls)}

    @app.delete("/api/labels/{call_id}")
    def delete_label_endpoint(call_id: str) -> dict[str, bool]:
        """Undo an adjudication."""
        delete_label(call_id, labels_path)
        return {"ok": True}

    @app.get("/api/associations")
    def associations() -> list[dict[str, Any]]:
        return [dict(v) for v in load_associations(associations_path).values()]

    @app.post("/api/associations")
    def associate(a: str = Body(...), b: str = Body(...)) -> dict[str, Any]:
        if a == b:
            raise HTTPException(status_code=400, detail="cannot associate a session with itself")
        return save_association(a, b, associations_path)

    @app.delete("/api/associations")
    def remove_association_endpoint(a: str = Body(...), b: str = Body(...)) -> dict[str, bool]:
        """Remove a session pair (undo a mis-made association)."""
        remove_association(a, b, associations_path)
        return {"ok": True}

    return app


def _dump_rows() -> list[dict[str, str]]:
    path = Path(__file__).resolve().parent.parent / "findings" / "s1_dump.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


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


def _list_sessions() -> list[dict[str, Any]]:
    """Every session in the store with its opening — the surf-and-associate
    list. Reads the store (this machine)."""
    sessions: list[dict[str, Any]] = []
    for d in sorted(STORE.iterdir()):
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*.jsonl")):
            title = ""
            first_user = ""
            started_at = ""
            ended_at = ""
            tools: list[str] = []
            first_user_seen = False
            user_messages = 0
            with open(path, errors="replace") as fh:
                for line in fh:
                    try:
                        o = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    t = o.get("type")
                    if t == "session" and not started_at:
                        started_at = o.get("timestamp", "")
                    elif t in ("title", "title_change") and not title:
                        title = o.get("title", "")
                    elif t == "message":
                        m = o.get("message", {})
                        if m.get("role") == "user":
                            texts = [
                                c.get("text", "")
                                for c in m.get("content", [])
                                if isinstance(c, dict) and c.get("type") == "text"
                            ]
                            if texts:
                                if not first_user_seen:
                                    first_user_seen = True
                                    if len(texts[0]) > 1500:
                                        continue  # harness-injected preamble
                                first_user = first_user or texts[0]
                                user_messages += 1
                    elif t == "custom" and o.get("customType") == "tool_execution_start" and len(tools) < 10:
                        tools.append(o.get("data", {}).get("toolName", ""))
                    ts = o.get("timestamp")
                    if ts:
                        ended_at = ts
                    if title and first_user and started_at and len(tools) >= 10:
                        break
            sessions.append(
                {
                    "id": path.name,
                    "repo": d.name,
                    "repo_name": _repo_display_name(d.name),
                    "title": title,
                    "opening": first_user[:160],
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "tools": dict(Counter(tools).most_common(4)),
                    "user_messages": user_messages,
                    "agent_run": user_messages == 0,
                }
            )
    sessions.sort(key=lambda s: s["started_at"])
    return sessions


app = create_app()

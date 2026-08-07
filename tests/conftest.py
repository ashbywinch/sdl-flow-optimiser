"""Shared fixtures: a fake omp session store built from the committed dump.

The real session store (~/.omp/agent/sessions) is an unwanted dependency —
tests must run identically in CI (no store) and locally (store present), so
the store is injected as a parameter (per testing-standards: parameter
injection first, never monkeypatch) and faked from the committed evidence.

The fake is derived from s1_dump.jsonl: every sampled execution becomes a
tool_execution_start line (plus the surrounding message records) in a
session file named exactly as the dump's `session` field, inside a store
directory whose name contains the sample's project prefix. The sampled
executions therefore match the real sessions' — classification, transcripts,
and confirm rows reproduce — while the store lives in tmp_path.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from sdl_flow_optimiser.findings.attribution_feasibility import DUMP_PATH, SAMPLE


def _roundtrip_args(raw: str) -> Any:
    """Recover the original arguments object from the dump's serialized form.
    Truncated rows (the 220-char cut) fall back to the raw string."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _build_fake_store(root: Path) -> Path:
    by_session: dict[str, list[dict[str, Any]]] = {}
    for line in DUMP_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        by_session.setdefault(row["session"], []).append(row)
    store = root / "store"
    for proj, stamp, _label in SAMPLE:
        proj_dir = store / f"{proj}-fake-{stamp}"
        proj_dir.mkdir(parents=True, exist_ok=True)
        for session_name, rows in by_session.items():
            if stamp not in session_name:
                continue
            lines: list[dict[str, Any]] = [
                {"type": "session", "timestamp": "2026-08-01T07-31-57"},
                {"type": "title", "title": f"fake session {stamp}", "timestamp": "2026-08-01T07-31-58"},
                {
                    "type": "message",
                    "message": {"role": "user", "content": [{"type": "text", "text": "ok let's make a plan"}]},
                },
                {
                    "type": "message",
                    "message": {"role": "assistant", "content": [{"type": "text", "text": "sure, here's the plan"}]},
                },
            ]
            for row in rows:
                args = _roundtrip_args(row["args"])
                lines.append(
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {"type": "toolCall", "id": row["call_id"], "name": row["tool"], "arguments": args}
                            ],
                        },
                    }
                )
                lines.append({"type": "message", "message": {"role": "toolResult", "toolCallId": row["call_id"]}})
                lines.append(
                    {
                        "type": "custom",
                        "customType": "tool_execution_start",
                        "data": {
                            "toolCallId": row["call_id"],
                            "toolName": row["tool"],
                            "intent": row["intent"],
                            "args": args,
                        },
                        "timestamp": "2026-08-01T07-32-00",
                    }
                )
            path = proj_dir / session_name
            path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    return store


@pytest.fixture
def fake_store(tmp_path: Path) -> Path:
    """A tmp session store whose sampled executions match the committed dump."""
    return _build_fake_store(tmp_path)

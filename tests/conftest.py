"""Shared fixtures: a fake omp session store built from the committed dump.

The real session store (~/.omp/agent/sessions) is an unwanted dependency —
tests must run identically in CI (no store) and locally (store present), so
the store is injected as a parameter (per testing-standards: parameter
injection first, never monkeypatch) and faked from the committed evidence.

The fake is derived from s1_dump.jsonl: every phase record becomes a user
message (the phase's opener) followed by its calls as tool_execution_start
lines plus the surrounding message records, inside a store directory named
per the sample's project prefix. The phases — and therefore the
classification, run_ids, and confirm rows — reproduce exactly: the same
user-message boundaries and the same calls in the same order.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from sdl_flow_optimiser.findings.attribution_feasibility import DUMP_PATH, SAMPLE


def _roundtrip_args(raw: str) -> Any:
    """Recover the original arguments object from the dump's serialized form.
    Truncated rows (the 400-char cut) fall back to the raw string."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


@pytest.fixture(scope="session")
def _phase_dump_records() -> list[dict[str, Any]]:
    """Parse the committed phase dump once — the expensive part; each test
    rebuilds only the in-memory store files from it (testing standard:
    pre-process expensive fixtures once)."""
    records: list[dict[str, Any]] = []
    for line in DUMP_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def _build_fake_store(root: Path, records: list[dict[str, Any]]) -> Path:
    phases_by_session: dict[str, list[dict[str, Any]]] = {}
    for row in records:
        phases_by_session.setdefault(row["session"], []).append(row)
    store = root / "store"
    for proj, stamp, _label in SAMPLE:
        proj_dir = store / f"{proj}-fake-{stamp}"
        proj_dir.mkdir(parents=True, exist_ok=True)
        for session_name, phases in phases_by_session.items():
            if stamp not in session_name:
                continue
            lines: list[dict[str, Any]] = [
                {"type": "session", "timestamp": "2026-08-01T07-31-57"},
                {"type": "title", "title": f"fake session {stamp}", "timestamp": "2026-08-01T07-31-58"},
            ]
            for phase in phases:
                if phase.get("user"):
                    lines.append(
                        {
                            "type": "message",
                            "message": {"role": "user", "content": [{"type": "text", "text": phase["user"]}]},
                        }
                    )
                    lines.append(
                        {
                            "type": "message",
                            "message": {
                                "role": "assistant",
                                "content": [{"type": "text", "text": "sure, here's the plan"}],
                            },
                        }
                    )
                for call in phase["calls"]:
                    args = _roundtrip_args(call["args"])
                    lines.append(
                        {
                            "type": "message",
                            "message": {
                                "role": "assistant",
                                "content": [
                                    {"type": "toolCall", "id": call["call_id"], "name": call["tool"], "arguments": args}
                                ],
                            },
                        }
                    )
                    lines.append({"type": "message", "message": {"role": "toolResult", "toolCallId": call["call_id"]}})
                    lines.append(
                        {
                            "type": "custom",
                            "customType": "tool_execution_start",
                            "data": {
                                "toolCallId": call["call_id"],
                                "toolName": call["tool"],
                                "intent": call["intent"],
                                "args": args,
                            },
                            "timestamp": "2026-08-01T07-32-00",
                        }
                    )
            path = proj_dir / session_name
            path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    return store


REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def fs_with_repo(fs) -> None:
    """The committed evidence and labeler assets stay readable over the
    fake filesystem; all writes are in-memory. Only the directories the
    tests actually read are mounted, so accidental writes stay confined to
    the fake FS."""
    fs.add_real_paths(
        [
            str(REPO_ROOT / "analysis"),
            str(REPO_ROOT / "sdl_flow_optimiser"),
        ]
    )


@pytest.fixture
def fake_store(fs_with_repo, _phase_dump_records) -> Path:
    """A fake session store whose phases match the committed dump, built in
    the in-memory filesystem (testing standard: fakefs wherever possible)."""
    return _build_fake_store(Path("/store"), _phase_dump_records)

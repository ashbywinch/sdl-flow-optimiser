"""Append-only stores for adjudications and session associations.

Every write appends a record line; nothing is ever rewritten or
hard-deleted — removal appends a tombstone (ux-standards P12: supersede,
never overwrite; soft deletes). `latest` returns the newest non-deleted
record. Files are JSONL; the app is long-running and the files are
evidence, so every method reads the file fresh.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent.parent / "findings"
LABELS_PATH = HERE / "s1_labels.jsonl"
ASSOCIATIONS_PATH = HERE / "s1_associations.jsonl"


@dataclass(frozen=True)
class Label:
    """One adjudication of one sample: agree, optional corrected phase, comment."""

    call_id: str
    agree: bool
    phase: int | None
    comment: str
    updated_at_ms: int


@dataclass(frozen=True)
class Association:
    """A session pair that is one piece of work (order-independent)."""

    a: str
    b: str
    created_at_ms: int


@dataclass(frozen=True)
class RunVerdict:
    """The user's adjudication of one activity run: the phase they say it was."""

    run_id: str
    phase: int
    comment: str
    updated_at_ms: int


class Labels:
    """The label and association stores — the domain object, not a pattern
    name (the coding standard now says so explicitly)."""

    def __init__(self, labels_path: Path = LABELS_PATH, associations_path: Path = ASSOCIATIONS_PATH) -> None:
        self._labels_path = labels_path
        self._associations_path = associations_path

    @staticmethod
    def _label_from_line(line: dict[str, Any]) -> Label:
        return Label(
            call_id=str(line["call_id"]),
            agree=bool(line["agree"]),
            phase=int(line["phase"]) if line.get("phase") is not None else None,
            comment=str(line.get("comment", "")),
            updated_at_ms=int(line["updated_at_ms"]),
        )

    @staticmethod
    def _association_from_line(line: dict[str, Any]) -> Association:
        return Association(
            a=str(line["a"]),
            b=str(line["b"]),
            created_at_ms=int(line["created_at_ms"]),
        )

    @staticmethod
    def _run_verdict_from_line(line: dict[str, Any]) -> RunVerdict:
        return RunVerdict(
            run_id=str(line["run_id"]),
            phase=int(line["phase"]),
            comment=str(line.get("comment", "")),
            updated_at_ms=int(line["updated_at_ms"]),
        )

    @staticmethod
    def _read(path: Path) -> list[Any]:
        """Raw JSON lines from the file — the deserialization boundary. Each
        line's shape is unknown until dispatched by the *_from_line
        deserializers below (the sanctioned spot for bare dicts: raw JSON in,
        domain class out)."""
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # torn trailing line (kill/ENOSPC mid-append) — skip, never crash reads
        return rows

    @staticmethod
    def _append(path: Path, payload: str) -> None:
        """Append one serialized JSON line — the write boundary."""
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(payload + "\n")

    # ---- labels ----

    def add_label(self, call_id: str, agree: bool, phase: int | None, comment: str) -> Label:
        label = Label(
            call_id=call_id,
            agree=agree,
            phase=phase,
            comment=comment,
            updated_at_ms=int(time.time() * 1000),
        )
        self._append(self._labels_path, json.dumps({"kind": "label", **asdict(label)}, sort_keys=True))
        return label

    def remove_label(self, call_id: str) -> None:
        """Soft delete: a tombstone supersedes the label's history."""
        self._append(
            self._labels_path,
            json.dumps(
                {"kind": "label", "call_id": call_id, "deleted": True, "updated_at_ms": int(time.time() * 1000)},
                sort_keys=True,
            ),
        )

    def latest_label(self, call_id: str) -> Label | None:
        for line in reversed(self._read(self._labels_path)):
            if line.get("kind") != "label" or line.get("call_id") != call_id:
                continue
            return None if line.get("deleted") else self._label_from_line(line)
        return None

    def latest_labels_map(self) -> dict[str, Label]:
        """call_id -> newest non-deleted label (a tombstone removes)."""
        result: dict[str, Label] = {}
        for line in self._read(self._labels_path):
            if line.get("kind") != "label":
                continue
            call_id = str(line["call_id"])
            if line.get("deleted"):
                result.pop(call_id, None)
            else:
                result[call_id] = self._label_from_line(line)
        return result

    def label_history(self, call_id: str) -> list[Label]:
        return [
            self._label_from_line(line)
            for line in self._read(self._labels_path)
            if line.get("kind") == "label" and line.get("call_id") == call_id and not line.get("deleted")
        ]

    # ---- associations ----

    def add_association(self, a: str, b: str) -> Association:
        first, second = sorted([a, b])
        association = Association(a=first, b=second, created_at_ms=int(time.time() * 1000))
        payload = json.dumps({"kind": "association", **asdict(association)}, sort_keys=True)
        self._append(self._associations_path, payload)
        return association

    def remove_association(self, a: str, b: str) -> None:
        first, second = sorted([a, b])
        self._append(
            self._associations_path,
            json.dumps(
                {
                    "kind": "association",
                    "a": first,
                    "b": second,
                    "deleted": True,
                    "created_at_ms": int(time.time() * 1000),
                },
                sort_keys=True,
            ),
        )

    def associations(self) -> list[Association]:
        active: dict[tuple[str, str], Association] = {}
        for line in self._read(self._associations_path):
            if line.get("kind") != "association":
                continue
            key = (str(line["a"]), str(line["b"]))
            if line.get("deleted"):
                active.pop(key, None)
            else:
                active[key] = self._association_from_line(line)
        return list(active.values())

    # ---- run verdicts ----

    def add_run_verdict(self, run_id: str, phase: int, comment: str) -> RunVerdict:
        verdict = RunVerdict(run_id=run_id, phase=phase, comment=comment, updated_at_ms=int(time.time() * 1000))
        self._append(self._labels_path, json.dumps({"kind": "run_verdict", **asdict(verdict)}, sort_keys=True))
        return verdict

    def remove_run_verdict(self, run_id: str) -> None:
        """Soft delete: a tombstone supersedes the run's verdict history."""
        self._append(
            self._labels_path,
            json.dumps(
                {"kind": "run_verdict", "run_id": run_id, "deleted": True, "updated_at_ms": int(time.time() * 1000)},
                sort_keys=True,
            ),
        )

    def latest_run_verdict(self, run_id: str) -> RunVerdict | None:
        for line in reversed(self._read(self._labels_path)):
            if line.get("kind") != "run_verdict" or line.get("run_id") != run_id:
                continue
            return None if line.get("deleted") else self._run_verdict_from_line(line)
        return None

    def latest_run_verdicts(self) -> dict[str, RunVerdict]:
        """run_id -> newest non-deleted verdict (a tombstone removes)."""
        result: dict[str, RunVerdict] = {}
        for line in self._read(self._labels_path):
            if line.get("kind") != "run_verdict":
                continue
            run_id = str(line["run_id"])
            if line.get("deleted"):
                result.pop(run_id, None)
            else:
                result[run_id] = self._run_verdict_from_line(line)
        return result

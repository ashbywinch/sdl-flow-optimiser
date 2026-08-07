"""Label and association persistence — committed JSON evidence files.

The ground truth stays the source of truth; labels are an overlay recording
the user's adjudication (agree / disagree-with-phase + comment). Applying
the overlay to the ground truth is a findings-stage operation
(--apply-labels). JSON payloads are untyped by nature; Any is the honest
annotation.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent.parent / "findings"
LABELS_PATH = HERE / "s1_labels.json"
ASSOCIATIONS_PATH = HERE / "s1_associations.json"


def _load(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def load_labels(path: Path = LABELS_PATH) -> dict[str, Any]:
    return _load(path)


def save_label(call_id: str, agree: bool, phase: int | None, comment: str, path: Path = LABELS_PATH) -> dict[str, Any]:
    """Record one adjudication. Disagree without a phase keeps the label
    unresolved (the comment may carry the correction)."""
    labels = load_labels(path)
    labels[call_id] = {
        "agree": agree,
        "phase": phase,
        "comment": comment,
        "updated_at_ms": int(time.time() * 1000),
    }
    _save(path, labels)
    return labels[call_id]


def load_associations(path: Path = ASSOCIATIONS_PATH) -> dict[str, Any]:
    return _load(path)


def save_association(a: str, b: str, path: Path = ASSOCIATIONS_PATH) -> dict[str, Any]:
    """Associate two sessions as the same piece of work (plan session +
    execute session etc.). The pair is stored in sorted order so the
    association is order-independent."""
    associations = load_associations(path)
    first, second = sorted([a, b])
    key = json.dumps([first, second])
    associations[key] = {"a": first, "b": second, "created_at_ms": int(time.time() * 1000)}
    _save(path, associations)
    return associations[key]


def delete_label(call_id: str, path: Path = LABELS_PATH) -> None:
    """Undo an adjudication — one write path for the label store."""
    labels = load_labels(path)
    if call_id in labels:
        del labels[call_id]
        _save(path, labels)


def remove_association(a: str, b: str, path: Path = ASSOCIATIONS_PATH) -> None:
    """Remove a session pair — one write path for the association store."""
    associations = load_associations(path)
    key = json.dumps(sorted([a, b]))
    if key in associations:
        del associations[key]
        _save(path, associations)

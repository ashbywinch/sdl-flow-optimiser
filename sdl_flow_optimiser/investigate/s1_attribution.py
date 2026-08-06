"""S1 attribution spike — does rule-based phase classification agree with hand labels?

A repeatable experiment (TECHSPEC: investigate is a first-class stage).
Extracts a stratified sample of tool executions from 5 sessions spanning the
phase spectrum, classifies each with sdl_flow_optimiser.classifier, and
compares against hand labels in s1_ground_truth.json (analyst labels — Ashby
to validate).

    python -m sdl_flow_optimiser.investigate.s1_attribution --dump
    python -m sdl_flow_optimiser.investigate.s1_attribution
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from sdl_flow_optimiser.classifier import PHASE_NAMES, classify_execution

STORE = Path.home() / ".omp" / "agent" / "sessions"
HERE = Path(__file__).parent
GROUND_TRUTH_PATH = HERE / "s1_ground_truth.json"
DUMP_PATH = HERE / "s1_dump.jsonl"
PER_SESSION = 60  # sampled executions per session

# (project_dir_prefix, file_timestamp_prefix, label)
SAMPLE: list[tuple[str, str, str]] = [
    ("home-omp-config", "2026-08-01T07-31", "Create shell repo best practices skill"),
    ("home-houses", "2026-08-01T05-43", "Handle branch divergence from main"),
    ("home-feed-generator", "2026-08-01T11-36", "Fix lint errors and verify report"),
    ("home-family-history-album", "2026-08-02T19-34", "Begin data acquisition planning phase"),
    # NOTE: sessions must be frozen (not currently being written) — a live
    # transcript shifts the stratified sample between runs.
    ("home-feed-generator", "2026-08-04T04-43", "Fix PR creation and deploy pipeline"),
]


def find_files() -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    for proj, stamp, label in SAMPLE:
        matches: list[Path] = []
        for d in STORE.iterdir():
            if not d.is_dir() or proj not in d.name:
                continue
            matches.extend(p for p in d.glob("*.jsonl") if stamp in p.name)
        if not matches:
            raise FileNotFoundError(f"no session file for {proj} {stamp}")
        found.append((sorted(matches)[0], label))
    return found


def extract_executions(path: Path) -> list[dict[str, str]]:
    """Tool executions with the intent string and preceding user message."""
    execs: list[dict[str, str]] = []
    last_user = ""
    with open(path, errors="replace") as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if o.get("type") == "message":
                message = o.get("message", {})
                if message.get("role") == "user":
                    texts = [
                        c.get("text", "")
                        for c in message.get("content", [])
                        if isinstance(c, dict) and c.get("type") == "text"
                    ]
                    if texts:
                        last_user = texts[0]
            elif o.get("type") == "custom" and o.get("customType") == "tool_execution_start":
                data = o.get("data", {})
                args = data.get("args", {})
                execs.append(
                    {
                        "tool": data.get("toolName", ""),
                        "intent": data.get("intent", ""),
                        "args": json.dumps(args, default=str)[:220],
                        "call_id": data.get("toolCallId", ""),
                        "prev_user": last_user[:200],
                    }
                )
    return execs


def sample_execs(execs: list[dict[str, str]]) -> list[dict[str, str]]:
    """Stratified sample: evenly spaced indices across the session."""
    n = len(execs)
    if n <= PER_SESSION:
        return list(execs)
    indices = sorted({round(i * (n - 1) / (PER_SESSION - 1)) for i in range(PER_SESSION)})
    return [execs[i] for i in indices]


def load_ground_truth() -> dict[str, int]:
    return {k: int(v) for k, v in json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8")).items()}


def dump() -> None:
    rows: list[dict[str, str]] = []
    for path, label in find_files():
        for ex in sample_execs(extract_executions(path)):
            rows.append({"label": label, "session": path.name, **ex})
    DUMP_PATH.write_text("\n".join(json.dumps(r, default=str) for r in rows) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} executions to {DUMP_PATH}")


def evaluate() -> int:
    ground_truth = load_ground_truth()
    if not ground_truth:
        print("ground truth is empty — run --dump, label, re-run.")
        return 1
    correct = 0
    total = 0
    by_phase: dict[int, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    for path, _label in find_files():
        for ex in sample_execs(extract_executions(path)):
            truth = ground_truth.get(ex["call_id"])
            if truth is None:
                continue
            pred, _rule = classify_execution(ex["tool"], ex["intent"], ex["args"])
            total += 1
            if pred == truth:
                correct += 1
                by_phase[truth]["tp"] += 1
            else:
                by_phase[truth]["fn"] += 1
                by_phase[pred]["fp"] += 1
    print(f"accuracy: {correct}/{total} = {correct / total:.2%}")
    print(f"{'phase':<12}{'prec':>7}{'recall':>8}{'n':>5}")
    for phase in sorted(by_phase):
        counts = by_phase[phase]
        prec = counts["tp"] / (counts["tp"] + counts["fp"]) if counts["tp"] + counts["fp"] else 0.0
        rec = counts["tp"] / (counts["tp"] + counts["fn"]) if counts["tp"] + counts["fn"] else 0.0
        print(f"{PHASE_NAMES[phase]:<12}{prec:>7.2%}{rec:>8.2%}{counts['tp'] + counts['fn']:>5}")
    return 0


if __name__ == "__main__":
    sys.exit(dump() if "--dump" in sys.argv else evaluate())

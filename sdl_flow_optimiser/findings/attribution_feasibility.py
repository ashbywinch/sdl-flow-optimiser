"""Finding S1 — attribution feasibility: does phase attribution agree with hand labels?

A repeatable experiment (the findings stage's core). Extracts a stratified
sample of tool executions from 5 frozen sessions spanning the phase spectrum,
attributes each with sdl_flow_optimiser.phase_attribution, and compares
against hand labels in s1_ground_truth.json (analyst labels — Ashby to
validate). Sessions in the sample MUST be frozen: a live transcript shifts
the stratified sample between runs.

    python -m sdl_flow_optimiser.findings.attribution_feasibility --dump
    python -m sdl_flow_optimiser.findings.attribution_feasibility [--errors]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from sdl_flow_optimiser.phase_attribution import PHASE_NAMES, assign_phase

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


def evaluate(show_errors: bool) -> int:
    ground_truth = load_ground_truth()
    if not ground_truth:
        print("ground truth is empty — run --dump, label, re-run.")
        return 1
    correct = 0
    total = 0
    by_phase: dict[int, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    confusion: dict[tuple[int, int], int] = defaultdict(int)
    errors: list[tuple[str, str, int, int, float]] = []
    for path, _label in find_files():
        execs = sample_execs(extract_executions(path))
        for pos, ex in enumerate(execs):
            truth = ground_truth.get(ex["call_id"])
            if truth is None:
                continue
            position_ratio = pos / max(len(execs) - 1, 1)
            pred = assign_phase(ex["tool"], ex["intent"], ex["args"], position_ratio)
            total += 1
            confusion[(truth, pred.phase_id)] += 1
            if pred.phase_id == truth:
                correct += 1
                by_phase[truth]["tp"] += 1
            else:
                by_phase[truth]["fn"] += 1
                by_phase[pred.phase_id]["fp"] += 1
                errors.append((ex["tool"], ex["intent"], truth, pred.phase_id, pred.confidence))
    print(f"accuracy: {correct}/{total} = {correct / total:.2%}")
    print(f"{'phase':<12}{'prec':>7}{'recall':>8}{'n':>5}")
    for phase in sorted(by_phase):
        counts = by_phase[phase]
        prec = counts["tp"] / (counts["tp"] + counts["fp"]) if counts["tp"] + counts["fp"] else 0.0
        rec = counts["tp"] / (counts["tp"] + counts["fn"]) if counts["tp"] + counts["fn"] else 0.0
        print(f"{PHASE_NAMES[phase]:<12}{prec:>7.2%}{rec:>8.2%}{counts['tp'] + counts['fn']:>5}")
    preds = sorted({p for _, p in confusion})
    truths = sorted({t for t, _ in confusion})
    print("confusion (truth → predicted):")
    print(f"{'truth':<12}" + "".join(f"{PHASE_NAMES[p]:>11}" for p in preds))
    for t in truths:
        row = "".join(f"{confusion.get((t, p), 0):>11}" for p in preds)
        print(f"{PHASE_NAMES[t]:<12}{row}")
    if show_errors:
        print("\nerrors (tool | intent | truth → pred | conf):")
        for tool, intent, truth, pred, conf in sorted(errors, key=lambda e: e[4])[:60]:
            print(f"  {tool:<10} {intent[:45]:<45} {PHASE_NAMES[truth]} → {PHASE_NAMES[pred]} {conf:.2f}")
    return 0


# Short phase codes for narrow screens — the confirmation list is read on a
# phone; full names and tables are unreadable there.
_SHORT = {1: "prd", 2: "tech", 3: "flow", 4: "brk", 5: "plan", 6: "exec", 7: "pr", 8: "ux"}


def confirm() -> int:
    """Write the phone-first confirmation list (analysis/findings/s1-confirm.md).

    One sample per line, numbered so corrections can be replied as "12, 34
    wrong"; disagreements first (lowest confidence first), then agreed
    low-confidence predictions. Lines are width-constrained for a phone.
    """
    ground_truth = load_ground_truth()
    rows: list[tuple[str, str, int, int, float]] = []  # tool, intent, truth, pred, conf
    for path, _label in find_files():
        execs = sample_execs(extract_executions(path))
        for pos, ex in enumerate(execs):
            truth = ground_truth.get(ex["call_id"])
            if truth is None:
                continue
            position_ratio = pos / max(len(execs) - 1, 1)
            pred = assign_phase(ex["tool"], ex["intent"], ex["args"], position_ratio)
            rows.append((ex["tool"], ex["intent"], truth, pred.phase_id, pred.confidence))
    disagreements = sorted([r for r in rows if r[2] != r[3]], key=lambda r: r[4])
    low_conf_agreed = sorted([r for r in rows if r[2] == r[3] and r[4] < 0.5], key=lambda r: r[4])[:40]

    def line(n: int, tool: str, intent: str, truth: int, pred: int, conf: float) -> str:
        arrow = "=" if truth == pred else "≠"
        intent_txt = (intent or "").replace("|", "/")[:24]
        return f'{n:3d}. {_SHORT[truth]}{arrow}{_SHORT[pred]} {tool[:8]:<8} {conf:.2f} "{intent_txt}"'

    out = [
        "# S1 confirmation — reply with the numbers of any WRONG labels (e.g. '12 34').",
        "# Lines: my label = classifier label, confidence, tool, intent.",
        "",
        f"## Disagreements ({len(disagreements)}) — adjudicate these",
    ]
    out += [line(i, *r) for i, r in enumerate(disagreements, 1)]
    out += ["", f"## Agreed but low confidence ({len(low_conf_agreed)}) — spot check"]
    out += [line(i, *r) for i, r in enumerate(low_conf_agreed, len(disagreements) + 1)]
    path = Path(__file__).resolve().parents[2] / "analysis" / "findings" / "s1-confirm.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {len(disagreements)} disagreements + {len(low_conf_agreed)} low-confidence to {path}")
    return 0


if __name__ == "__main__":
    if "--dump" in sys.argv:
        dump()
    elif "--confirm" in sys.argv:
        sys.exit(confirm())
    else:
        sys.exit(evaluate("--errors" in sys.argv))

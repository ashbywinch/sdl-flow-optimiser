"""Finding S1 — attribution feasibility: does phase attribution agree with hand labels?

A repeatable experiment (the findings stage's core). Extracts a stratified
sample of tool executions from 4 frozen sessions spanning the phase spectrum,
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
from collections import Counter, defaultdict
from pathlib import Path

from sdl_flow_optimiser.findings.labels import Labels
from sdl_flow_optimiser.findings.transcript import compute_runs, extract_transcript
from sdl_flow_optimiser.phase_attribution import (
    PHASE_NAMES,
    classify_with_context,
)

STORE = Path.home() / ".omp" / "agent" / "sessions"
HERE = Path(__file__).parent
GROUND_TRUTH_PATH = HERE / "s1_ground_truth.json"
DUMP_PATH = HERE / "s1_dump.jsonl"
PER_SESSION = 60  # sampled executions per session

# (project_dir_prefix, file_timestamp_prefix, label)
# SAMPLE must be frozen sessions doing DEVELOPMENT work. Chores (git
# maintenance, ops) are not SDLC phases and are excluded: the houses
# branch-divergence session (bash-heavy, zero file edits) was such a chore —
# a candidate chore signal is "no edit/write tool in the session".
SAMPLE: list[tuple[str, str, str]] = [
    ("home-omp-config", "2026-08-01T07-31", "Create shell repo best practices skill"),
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


# Short repo display names for narrow screens.
_REPO_TAGS = {
    "home-omp-config": "ompcfg",
    "home-houses": "houses",
    "home-feed-generator": "feed",
    "home-family-history-album": "fam",
}


def session_openings() -> list[dict[str, str]]:
    """Recognition anchor per sample session: repo, auto-title, the opening
    user message, and the first-20 tool mix. Auto-titles are unreliable
    (they reflect only the opening); the user's own first words identify the
    work. The tool mix also flags delegated phases (scouts/jobs run in
    subagents — the parent stream only shows the coordination calls)."""
    openings: list[dict[str, str]] = []
    for path, label in find_files():
        first_user = ""
        tools: list[str] = []
        first_user_seen = False
        with open(path, errors="replace") as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if o.get("type") == "message":
                    m = o.get("message", {})
                    if m.get("role") == "user" and not first_user:
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
                            first_user = texts[0]
                elif o.get("type") == "custom" and o.get("customType") == "tool_execution_start" and len(tools) < 20:
                    tools.append(o.get("data", {}).get("toolName", ""))
                if first_user and len(tools) >= 20:
                    break
        hist = " ".join(f"{t}×{c}" for t, c in Counter(tools).most_common(4))
        proj = next(p for p in _REPO_TAGS if p in path.parent.name)
        openings.append(
            {
                "repo": _REPO_TAGS[proj],
                "label": label,
                "user": first_user[:96],
                "hist": hist or "(no tool calls)",
            }
        )
    return openings


def apply_labels(labels_path: Path | None = None, ground_truth_path: Path | None = None) -> int:
    """Fold user adjudication into the ground truth.

    Run verdicts (the primary path): each verdict's phase applies to every
    call in that run. Per-call labels (legacy path): a disagreement with a
    corrected phase updates that call. Reads the append-only stores (latest
    non-deleted records). Idempotent — re-running changes nothing."""
    labels_path = labels_path or (HERE / "s1_labels.jsonl")
    ground_truth_path = ground_truth_path or GROUND_TRUTH_PATH
    truth = json.loads(ground_truth_path.read_text(encoding="utf-8"))
    stores = Labels(labels_path)
    applied = 0

    def set_phase(call_id: str, phase: int) -> None:
        nonlocal applied
        if truth.get(call_id) != phase:
            truth[call_id] = phase
            applied += 1

    for path, _label in find_files():
        items = extract_transcript(path)
        for run in compute_runs(items, path.name):
            verdict = stores.latest_run_verdict(run.run_id)
            if verdict is not None and verdict.phase in PHASE_NAMES:
                for call_id in run.call_ids:
                    set_phase(call_id, verdict.phase)
    for call_id, label in stores.latest_labels_map().items():
        if not label.agree and label.phase is not None and label.phase in PHASE_NAMES:
            set_phase(call_id, label.phase)
    ground_truth_path.write_text(json.dumps(truth) + "\n", encoding="utf-8")
    print(f"applied {applied} corrections to ground truth")
    return 0


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
    delegation_n = 0
    by_phase: dict[int, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    confusion: dict[tuple[int, int], int] = defaultdict(int)
    errors: list[tuple[str, str, int, int, float]] = []
    for path, _label in find_files():
        execs = sample_execs(extract_executions(path))
        for ex, (pred, delegation) in zip(execs, classify_with_context(execs), strict=True):
            truth = ground_truth.get(ex["call_id"])
            if truth is None:
                continue
            if delegation:
                delegation_n += 1
                continue  # not phase-bearing; reported separately
            total += 1
            confusion[(truth, pred.phase_id)] += 1
            if pred.phase_id == truth:
                correct += 1
                by_phase[truth]["tp"] += 1
            else:
                by_phase[truth]["fn"] += 1
                by_phase[pred.phase_id]["fp"] += 1
                errors.append((ex["tool"], ex["intent"], truth, pred.phase_id, pred.confidence))
    if total == 0:
        print("no sampled executions matched the ground truth — stale ground truth for this dump?")
        return 1
    print(f"accuracy: {correct}/{total} = {correct / total:.2%} (delegation events excluded: {delegation_n})")
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


def confirm(output_path: Path | None = None) -> int:
    """Write the phone-first confirmation list (default: analysis/findings/s1-confirm.md).

    One sample per line, numbered so corrections can be replied as "12, 34
    wrong"; disagreements first (lowest confidence first), then agreed
    low-confidence predictions. Lines are width-constrained for a phone.
    output_path lets tests regenerate elsewhere and diff against the
    committed artifact instead of rewriting it.
    """
    ground_truth = load_ground_truth()
    openings = session_openings()
    tags = {o["label"]: f"S{i + 1}" for i, o in enumerate(openings)}
    rows: list[tuple[str, str, int, int, float, bool, str]] = []  # + session tag
    for path, label in find_files():
        execs = sample_execs(extract_executions(path))
        for ex, (pred, delegation) in zip(execs, classify_with_context(execs), strict=True):
            truth = ground_truth.get(ex["call_id"])
            if truth is None:
                continue
            rows.append((ex["tool"], ex["intent"], truth, pred.phase_id, pred.confidence, delegation, tags[label]))
    disagreements = sorted([r for r in rows if not r[5] and r[2] != r[3]], key=lambda r: r[4])
    low_conf_agreed = sorted([r for r in rows if not r[5] and r[2] == r[3] and r[4] < 0.5], key=lambda r: r[4])[:40]
    delegations = sorted([r for r in rows if r[5]], key=lambda r: r[4])

    def line(n: int, row: tuple[str, str, int, int, float, bool, str]) -> str:
        tool, intent, truth, pred, conf, _del, tag = row
        arrow = "=" if truth == pred else "≠"
        intent_txt = (intent or "").replace("|", "/")[:18]
        return f'{n:3d}. [{tag}] {_SHORT[truth]}{arrow}{_SHORT[pred]} {tool[:7]:<7} {conf:.2f} "{intent_txt}"'

    out = [
        "# S1 confirmation — reply with the numbers of any WRONG labels (e.g. '12 34').",
        "# Lines: [session] my label = classifier label, confidence, tool, intent.",
        "# Delegation events (subtask coordination) inherit the parent phase.",
        "",
        "## Sessions — repo · title · opening · first-20 tools",
    ]
    for o in openings:
        out.append(f"  {tags[o['label']]:<3} {o['repo']:<7} {o['label'][:38]}")
        out.append(f"      open: {o['user'][:43]}")
        out.append(f"      tools: {o['hist']}")
    out += ["", f"## Disagreements ({len(disagreements)}) — adjudicate these"]
    out += [line(i, r) for i, r in enumerate(disagreements, 1)]
    out += ["", f"## Agreed but low confidence ({len(low_conf_agreed)}) — spot check"]
    out += [line(i, r) for i, r in enumerate(low_conf_agreed, len(disagreements) + 1)]
    out += ["", f"## Delegation ({len(delegations)}) — subtask coordination, context-inherited"]
    out += [line(i, r) for i, r in enumerate(delegations, len(disagreements) + len(low_conf_agreed) + 1)]
    path = output_path or (Path(__file__).resolve().parents[2] / "analysis" / "findings" / "s1-confirm.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {len(disagreements)} disagreements + {len(low_conf_agreed)} low-confidence to {path}")
    return 0


if __name__ == "__main__":
    if "--dump" in sys.argv:
        dump()
    elif "--confirm" in sys.argv:
        sys.exit(confirm())
    elif "--apply-labels" in sys.argv:
        sys.exit(apply_labels())
    else:
        sys.exit(evaluate("--errors" in sys.argv))

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
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sdl_flow_optimiser.findings.labels import Labels
from sdl_flow_optimiser.findings.transcript import PREAMBLE_MAX, Transcript
from sdl_flow_optimiser.phase_attribution import (
    PHASE_NAMES,
    Execution,
    classify_with_context,
)

STORE = Path.home() / ".omp" / "agent" / "sessions"
HERE = Path(__file__).parent
GROUND_TRUTH_PATH = HERE / "s1_ground_truth.json"
DUMP_PATH = HERE / "s1_dump.jsonl"
PER_SESSION = 60  # sampled executions per session


@dataclass(frozen=True)
class SampleFile:
    """One frozen session in the sample: the file and its human label."""

    path: Path
    label: str


@dataclass(frozen=True)
class Opening:
    """Recognition anchor for one sample session: repo tag, human label,
    the user's opening words, and the first-20 tool mix."""

    repo: str
    label: str
    user: str
    hist: str


@dataclass(frozen=True)
class DumpRow(Execution):
    """One sampled execution in the committed dump: an Execution plus its
    sample label and session file name."""

    label: str = ""
    session: str = ""


@dataclass(frozen=True)
class ReportRow:
    """One confirmation line: tool, intent, ground truth, prediction,
    confidence, delegation flag, and session tag."""

    tool: str
    intent: str
    truth: int
    pred: int
    confidence: float
    delegation: bool
    tag: str


@dataclass(frozen=True)
class RowGroups:
    """Confirmation rows partitioned by adjudication need."""

    disagreements: list[ReportRow]
    low_conf_agreed: list[ReportRow]
    delegations: list[ReportRow]


@dataclass(frozen=True)
class PredictionError:
    """One misattribution worth surfacing: the truth vs the prediction."""

    tool: str
    intent: str
    truth: int
    pred: int
    confidence: float


@dataclass(frozen=True)
class Evaluation:
    """The S1 experiment's numbers: agreement, per-phase precision/recall,
    the confusion matrix, and the lowest-confidence errors."""

    correct: int
    total: int
    delegation_n: int
    by_phase: dict[int, dict[str, int]]
    confusion: dict[tuple[int, int], int]
    errors: list[PredictionError]


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


def find_files(store: Path = STORE) -> list[SampleFile]:
    found: list[SampleFile] = []
    for proj, stamp, label in SAMPLE:
        matches: list[Path] = []
        for d in store.iterdir():
            if not d.is_dir() or proj not in d.name:
                continue
            matches.extend(p for p in d.glob("*.jsonl") if stamp in p.name)
        if not matches:
            raise FileNotFoundError(f"no session file for {proj} {stamp}")
        found.append(SampleFile(path=sorted(matches)[0], label=label))
    return found


def _texts_of(m: Any) -> list[str]:
    """The text blocks of a message (raw JSON — the boundary)."""
    return [c.get("text", "") for c in m.get("content", []) if isinstance(c, dict) and c.get("type") == "text"]


def _execution_from(data: Any, last_user: str) -> Execution:
    """One tool execution captured by the harness (raw JSON — the boundary)."""
    args = data.get("args", {})
    return Execution(
        call_id=data.get("toolCallId", ""),
        tool=data.get("toolName", ""),
        intent=data.get("intent", ""),
        args=json.dumps(args, default=str)[:220],
        prev_user=last_user[:200],
    )


def extract_executions(path: Path) -> list[Execution]:
    """Tool executions with the intent string and preceding user message."""
    execs: list[Execution] = []
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
                    texts = _texts_of(message)
                    if texts:
                        last_user = texts[0]
            elif o.get("type") == "custom" and o.get("customType") == "tool_execution_start":
                execs.append(_execution_from(o.get("data", {}), last_user))
    return execs


def sample_execs[T](execs: list[T]) -> list[T]:
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


def _first_user_text(path: Path) -> str:
    """The first real user message: the opening, skipping a huge
    harness-injected preamble."""
    first_user = ""
    first_user_seen = False
    with open(path, errors="replace") as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if o.get("type") == "message":
                m = o.get("message", {})
                texts = _texts_of(m)
                if texts and m.get("role") == "user" and not first_user:
                    if not first_user_seen:
                        first_user_seen = True
                        if len(texts[0]) > PREAMBLE_MAX:
                            continue  # harness preamble, not the user's voice
                    first_user = texts[0]
    return first_user


def _first_tools(path: Path) -> list[str]:
    """The first-20 tool names of a session file."""
    tools: list[str] = []
    with open(path, errors="replace") as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if o.get("type") == "custom" and o.get("customType") == "tool_execution_start" and len(tools) < 20:
                tools.append(o.get("data", {}).get("toolName", ""))
            if len(tools) >= 20:
                break
    return tools


def session_openings(store: Path = STORE) -> list[Opening]:
    """Recognition anchor per sample session: repo, auto-title, the opening
    user message, and the first-20 tool mix. Auto-titles are unreliable
    (they reflect only the opening); the user's own first words identify the
    work. The tool mix also flags delegated phases (scouts/jobs run in
    subagents — the parent stream only shows the coordination calls)."""
    openings: list[Opening] = []
    for sample in find_files(store):
        path = sample.path
        first_user = _first_user_text(path)
        tools = _first_tools(path)
        hist = " ".join(f"{t}×{c}" for t, c in Counter(tools).most_common(4))
        proj = next(p for p in _REPO_TAGS if p in path.parent.name)
        openings.append(
            Opening(
                repo=_REPO_TAGS[proj],
                label=sample.label,
                user=first_user[:96],
                hist=hist or "(no tool calls)",
            )
        )
    return openings


def _apply_verdicts(truth: dict[str, int], stores: Labels, store: Path = STORE) -> int:
    """Run verdicts (the primary path): each verdict's phase applies to
    every call in that run. Idempotent — re-applying changes nothing.
    Without the session store there are no runs to adjudicate — a no-op,
    so apply_labels works on the label stores alone."""
    if not store.exists():
        return 0
    applied = 0
    for sample in find_files(store):
        transcript = Transcript.from_session_file(sample.path)
        for run in transcript.runs():
            verdict = stores.latest_run_verdict(run.run_id)
            if verdict is not None and verdict.phase in PHASE_NAMES:
                for call_id in run.call_ids:
                    if truth.get(call_id) != verdict.phase:
                        truth[call_id] = verdict.phase
                        applied += 1
    return applied


def _apply_label_corrections(truth: dict[str, int], stores: Labels) -> int:
    """Per-call labels (legacy path): a disagreement with a corrected
    phase updates that call."""
    applied = 0
    for call_id, label in stores.latest_labels_map().items():
        if (
            not label.agree
            and label.phase is not None
            and label.phase in PHASE_NAMES
            and truth.get(call_id) != label.phase
        ):
            truth[call_id] = label.phase
            applied += 1
    return applied


def apply_labels(labels_path: Path | None = None, ground_truth_path: Path | None = None, store: Path = STORE) -> int:
    """Fold user adjudication into the ground truth.

    Reads the append-only stores (latest non-deleted records). Idempotent —
    re-running changes nothing.
    """
    labels_path = labels_path or (HERE / "s1_labels.jsonl")
    ground_truth_path = ground_truth_path or GROUND_TRUTH_PATH
    truth = json.loads(ground_truth_path.read_text(encoding="utf-8"))
    stores = Labels(labels_path)
    applied = _apply_verdicts(truth, stores, store) + _apply_label_corrections(truth, stores)
    ground_truth_path.write_text(json.dumps(truth) + "\n", encoding="utf-8")
    print(f"applied {applied} corrections to ground truth")
    return 0


def dump(store: Path = STORE) -> None:
    rows: list[DumpRow] = []
    for sample in find_files(store):
        for ex in sample_execs(extract_executions(sample.path)):
            rows.append(
                DumpRow(
                    label=sample.label,
                    session=sample.path.name,
                    call_id=ex.call_id,
                    tool=ex.tool,
                    intent=ex.intent,
                    args=ex.args,
                    prev_user=ex.prev_user,
                )
            )
    DUMP_PATH.write_text("\n".join(json.dumps(asdict(r), default=str) for r in rows) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} executions to {DUMP_PATH}")


def dump_rows() -> list[DumpRow]:
    """The committed dump as typed records — the file is evidence, so reads
    tolerate schema drift without crashing."""
    rows: list[DumpRow] = []
    for line in DUMP_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(DumpRow(**json.loads(line)))
        except json.JSONDecodeError, TypeError:
            continue
    return rows


def _evaluate_samples(ground_truth: dict[str, int], store: Path = STORE) -> Evaluation:
    """Run the classifier over the sampled executions and tally agreement.
    Delegation events are counted separately — they are not phase-bearing."""
    correct = 0
    total = 0
    delegation_n = 0
    by_phase: dict[int, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    confusion: dict[tuple[int, int], int] = defaultdict(int)
    errors: list[PredictionError] = []
    for sample in find_files(store):
        execs = sample_execs(extract_executions(sample.path))
        for ex, classified in zip(execs, classify_with_context(execs), strict=True):
            truth = ground_truth.get(ex.call_id)
            if truth is None:
                continue
            pred = classified.prediction
            if classified.delegation:
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
                errors.append(
                    PredictionError(
                        tool=ex.tool, intent=ex.intent, truth=truth, pred=pred.phase_id, confidence=pred.confidence
                    )
                )
    return Evaluation(
        correct=correct,
        total=total,
        delegation_n=delegation_n,
        by_phase=dict(by_phase),
        confusion=dict(confusion),
        errors=errors,
    )


def _print_confusion(ev: Evaluation) -> None:
    preds = sorted({p for _, p in ev.confusion})
    truths = sorted({t for t, _ in ev.confusion})
    print("confusion (truth → predicted):")
    print(f"{'truth':<12}" + "".join(f"{PHASE_NAMES[p]:>11}" for p in preds))
    for t in truths:
        row = "".join(f"{ev.confusion.get((t, p), 0):>11}" for p in preds)
        print(f"{PHASE_NAMES[t]:<12}{row}")


def _print_evaluation(ev: Evaluation, show_errors: bool) -> None:
    accuracy = f"{ev.correct}/{ev.total} = {ev.correct / ev.total:.2%}"
    print(f"accuracy: {accuracy} (delegation events excluded: {ev.delegation_n})")
    print(f"{'phase':<12}{'prec':>7}{'recall':>8}{'n':>5}")
    for phase in sorted(ev.by_phase):
        counts = ev.by_phase[phase]
        prec = counts["tp"] / (counts["tp"] + counts["fp"]) if counts["tp"] + counts["fp"] else 0.0
        rec = counts["tp"] / (counts["tp"] + counts["fn"]) if counts["tp"] + counts["fn"] else 0.0
        print(f"{PHASE_NAMES[phase]:<12}{prec:>7.2%}{rec:>8.2%}{counts['tp'] + counts['fn']:>5}")
    _print_confusion(ev)
    if show_errors and ev.errors:
        print("\nerrors (tool | intent | truth → pred | conf):")
        for err in sorted(ev.errors, key=lambda e: e.confidence)[:60]:
            line = f"  {err.tool:<10} {err.intent[:45]:<45} {PHASE_NAMES[err.truth]} → {PHASE_NAMES[err.pred]}"
            print(f"{line} {err.confidence:.2f}")


def evaluate(show_errors: bool, store: Path = STORE) -> int:
    ground_truth = load_ground_truth()
    if not ground_truth:
        print("ground truth is empty — run --dump, label, re-run.")
        return 1
    ev = _evaluate_samples(ground_truth, store)
    if ev.total == 0:
        print("no sampled executions matched the ground truth — stale ground truth for this dump?")
        return 1
    _print_evaluation(ev, show_errors)
    return 0


# Short phase codes for narrow screens — the confirmation list is read on a
# phone; full names and tables are unreadable there.
_SHORT = {1: "prd", 2: "tech", 3: "flow", 4: "brk", 5: "plan", 6: "exec", 7: "pr", 8: "ux"}


def _report_rows(store: Path = STORE) -> list[ReportRow]:
    """One ReportRow per ground-truthed sampled execution, session-tagged."""
    ground_truth = load_ground_truth()
    tags = {o.label: f"S{i + 1}" for i, o in enumerate(session_openings(store))}
    rows: list[ReportRow] = []
    for sample in find_files(store):
        execs = sample_execs(extract_executions(sample.path))
        for ex, classified in zip(execs, classify_with_context(execs), strict=True):
            truth = ground_truth.get(ex.call_id)
            if truth is None:
                continue
            pred = classified.prediction
            rows.append(
                ReportRow(
                    tool=ex.tool,
                    intent=ex.intent,
                    truth=truth,
                    pred=pred.phase_id,
                    confidence=pred.confidence,
                    delegation=classified.delegation,
                    tag=tags[sample.label],
                )
            )
    return rows


def _group_rows(rows: list[ReportRow]) -> RowGroups:
    disagreements = sorted([r for r in rows if not r.delegation and r.truth != r.pred], key=lambda r: r.confidence)
    low_conf_agreed = sorted(
        [r for r in rows if not r.delegation and r.truth == r.pred and r.confidence < 0.5], key=lambda r: r.confidence
    )[:40]
    delegations = sorted([r for r in rows if r.delegation], key=lambda r: r.confidence)
    return RowGroups(
        disagreements=disagreements,
        low_conf_agreed=low_conf_agreed,
        delegations=delegations,
    )


def _render_line(n: int, row: ReportRow) -> str:
    arrow = "=" if row.truth == row.pred else "≠"
    intent_txt = (row.intent or "").replace("|", "/")[:18]
    return (
        f"{n:3d}. [{row.tag}] {_SHORT[row.truth]}{arrow}{_SHORT[row.pred]} "
        f'{row.tool[:7]:<7} {row.confidence:.2f} "{intent_txt}"'
    )


def confirm(output_path: Path | None = None, store: Path = STORE) -> int:
    """Write the phone-first confirmation list (default: analysis/findings/s1-confirm.md).

    One sample per line, numbered so corrections can be replied as "12, 34
    wrong"; disagreements first (lowest confidence first), then agreed
    low-confidence predictions. Lines are width-constrained for a phone.
    output_path lets tests regenerate elsewhere and diff against the
    committed artifact instead of rewriting it.
    """
    rows = _report_rows(store)
    groups = _group_rows(rows)
    openings = session_openings(store)
    tags = {o.label: f"S{i + 1}" for i, o in enumerate(openings)}
    out = [
        "# S1 confirmation — reply with the numbers of any WRONG labels (e.g. '12 34').",
        "# Lines: [session] my label = classifier label, confidence, tool, intent.",
        "# Delegation events (subtask coordination) inherit the parent phase.",
        "",
        "## Sessions — repo · title · opening · first-20 tools",
    ]
    for o in openings:
        out.append(f"  {tags[o.label]:<3} {o.repo:<7} {o.label[:38]}")
        out.append(f"      open: {o.user[:43]}")
        out.append(f"      tools: {o.hist}")
    out += ["", f"## Disagreements ({len(groups.disagreements)}) — adjudicate these"]
    out += [_render_line(i, r) for i, r in enumerate(groups.disagreements, 1)]
    out += ["", f"## Agreed but low confidence ({len(groups.low_conf_agreed)}) — spot check"]
    out += [_render_line(i, r) for i, r in enumerate(groups.low_conf_agreed, len(groups.disagreements) + 1)]
    out += ["", f"## Delegation ({len(groups.delegations)}) — subtask coordination, context-inherited"]
    out += [
        _render_line(i, r)
        for i, r in enumerate(groups.delegations, len(groups.disagreements) + len(groups.low_conf_agreed) + 1)
    ]
    path = output_path or (Path(__file__).resolve().parents[2] / "analysis" / "findings" / "s1-confirm.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {len(groups.disagreements)} disagreements + {len(groups.low_conf_agreed)} low-confidence to {path}")
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

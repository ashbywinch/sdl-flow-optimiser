"""Finding S1 data integrity: the phase dump and ground truth agree, values
are valid.

Guards the committed evidence: if the dump or ground truth drift
(regenerated against a different segmentation, hand-edited, corrupted), the
S1 finding's numbers become unreproducible — this test fails instead.
"""

import json
from pathlib import Path

from sdl_flow_optimiser.findings.attribution_feasibility import apply_labels, confirm, dump_rows, session_openings
from sdl_flow_optimiser.findings.labels import Labels
from sdl_flow_optimiser.findings.transcript import Transcript

HERE = Path(__file__).resolve().parent.parent / "sdl_flow_optimiser" / "findings"


def _load():
    dump = dump_rows()
    truth = json.loads((HERE / "s1_ground_truth.json").read_text(encoding="utf-8"))
    return dump, truth


def test_dump_has_phases_from_all_four_sessions():
    dump, _ = _load()
    sessions = {row.session for row in dump}
    assert len(sessions) == 4
    assert all(row.calls for row in dump)  # every phase carries the evidence that produced it
    assert all(row.user for row in dump)  # every phase is anchored to the human's words


def test_ground_truth_keys_are_real_phase_ids():
    """Every ground-truth key is a phase in the dump; the unlabeled phases
    (no seed yet) are simply absent — the confirm flow labels them."""
    dump, truth = _load()
    assert set(truth) <= {row.phase_id for row in dump}


def test_ground_truth_values_are_valid_phases():
    _, truth = _load()
    assert set(truth.values()) <= set(range(1, 9))


def test_confirm_lines_fit_a_phone_screen():
    """The confirmation list is read on a phone: every content line must fit
    a narrow terminal. The width is the contract, not a preference."""
    path = HERE.parent.parent / "analysis" / "findings" / "s1-confirm.md"
    assert path.exists(), "run `python -m sdl_flow_optimiser.findings.attribution_feasibility --confirm` first"
    long = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        if len(line) > 55:
            long.append(f"{len(line)}: {line}")
    assert not long, f"lines exceed phone width:\n{chr(10).join(long[:5])}"


def test_confirm_is_numbered_and_replyable():
    path = HERE.parent.parent / "analysis" / "findings" / "s1-confirm.md"
    numbered = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()[:1].isdigit()]
    assert numbered, "confirm list has no numbered phases"
    assert numbered[0].startswith("  1."), "numbering must start at 1 so corrections can reference it"


def test_confirm_output_matches_committed(fake_store):
    """Regenerating the confirmation list over the fake store must exactly
    reproduce the committed artifact's rows — the phases the fake encodes
    ARE the committed dump, so the adjudication rows are byte-identical
    (derived data is regenerated, never hand-edited)."""
    out = Path("/confirm.md")
    assert confirm(out, store=fake_store) == 0
    committed = HERE.parent.parent / "analysis" / "findings" / "s1-confirm.md"

    def rows_section(text: str) -> str:
        return text[text.index("## Unlabeled") :]

    assert rows_section(out.read_text(encoding="utf-8")) == rows_section(committed.read_text(encoding="utf-8"))


def test_confirm_is_deterministic(fake_store):
    """Derived data is regenerated, never hand-edited: regenerating twice
    over the same store produces byte-identical output."""
    first = Path("/a.md")
    second = Path("/b.md")
    assert confirm(first, store=fake_store) == 0
    assert confirm(second, store=fake_store) == 0
    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")


def test_session_openings_are_recognizable(fake_store):
    """Every sample session gets a repo, an opening user message, and a tool
    mix — the recognition anchor for adjudicating samples on a phone."""
    openings = session_openings(fake_store)
    assert len(openings) == 4
    for o in openings:
        assert o.repo
        assert o.user, f"{o.label} has no opening user message"
        assert o.hist, f"{o.label} has no tool mix"


def test_apply_labels_folds_verdicts_into_ground_truth(fake_store):
    """A phase verdict folds into the ground truth; re-running is
    idempotent; an agreement (same phase) changes nothing."""
    from sdl_flow_optimiser.findings.attribution_feasibility import find_files

    first_session = find_files(fake_store)[0].path
    runs = Transcript.from_session_file(first_session).runs()
    assert runs
    phase_id = runs[0].run_id
    gt_path = Path("/gt.json")
    labels_path = Path("/labels.jsonl")
    gt_path.write_text(json.dumps({"other": 6}) + "\n", encoding="utf-8")
    stores = Labels(labels_path=labels_path)
    stores.add_run_verdict(phase_id, 3, "flow work")
    apply_labels(labels_path, gt_path, store=fake_store)
    truth = json.loads(gt_path.read_text(encoding="utf-8"))
    assert truth["other"] == 6  # untouched phases survive
    assert truth[phase_id] == 3
    # idempotent
    apply_labels(labels_path, gt_path, store=fake_store)
    assert json.loads(gt_path.read_text(encoding="utf-8"))[phase_id] == 3


def test_delegation_inherits_parent_phase():
    """A task spawn between execute events takes execute; a scout check in a
    prd research run takes prd — the event's own signature is irrelevant."""
    from sdl_flow_optimiser.phase_attribution import Execution, classify_with_context

    def execs(*rows):
        return [Execution(call_id=r[3], tool=r[0], intent=r[1], args=r[2]) for r in rows]

    preds = classify_with_context(
        execs(
            ("read", "read example skill format", "{}", "a"),
            ("task", "", "{}", "b"),  # delegation
            ("edit", "Fix the import", "{}", "c"),
        )
    )
    assert preds[1].delegation is True  # marked delegation
    assert preds[1].prediction.rule == "delegation-context"
    # the surrounding research run ("read example skill format" at session
    # start) is prd — the task inherits it, not execute
    assert preds[1].prediction.phase_id == 1

    preds2 = classify_with_context(
        execs(
            ("read", "read example skill format", "{}", "a"),
            ("hub", "check scout jobs status", "{}", "b"),
            ("read", "read houses Makefile", "{}", "c"),
        )
    )
    assert preds2[1].delegation is True
    assert preds2[1].prediction.phase_id == 1  # research run at session start is prd

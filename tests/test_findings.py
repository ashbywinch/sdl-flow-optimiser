"""Finding S1 data integrity: ground truth matches the dump, values are valid.

Guards the committed evidence: if the dump or ground truth drift (regenerated
against a different sample, hand-edited, corrupted), the S1 finding's numbers
become unreproducible — this test fails instead.
"""

import json
from pathlib import Path

import pytest

from sdl_flow_optimiser.findings.attribution_feasibility import (
    PER_SESSION,
    apply_labels,
    confirm,
    find_files,
    sample_execs,
    session_openings,
)
from sdl_flow_optimiser.phase_attribution import classify_with_context

HERE = Path(__file__).resolve().parent.parent / "sdl_flow_optimiser" / "findings"


def _store_present() -> bool:
    """True when the omp session store is present; a fresh clone/CI without
    it must skip the store-guarded tests, not crash at collection."""
    try:
        return len(find_files()) == 4
    except FileNotFoundError:
        return False


STORE_PRESENT = _store_present()  # fresh clone / CI: store absent — skip, don't crash collection


def _load():
    dump = [json.loads(line) for line in (HERE / "s1_dump.jsonl").read_text(encoding="utf-8").splitlines()]
    truth = json.loads((HERE / "s1_ground_truth.json").read_text(encoding="utf-8"))
    return dump, truth


def test_dump_has_four_sessions_of_per_session_samples():
    dump, _ = _load()
    sessions = {row["session"] for row in dump}
    assert len(sessions) == 4
    assert len(dump) == 4 * PER_SESSION


def test_ground_truth_keys_match_dump_call_ids_exactly():
    dump, truth = _load()
    assert set(truth) == {row["call_id"] for row in dump}


def test_ground_truth_values_are_valid_phases():
    _, truth = _load()
    assert set(truth.values()) <= set(range(1, 9))


def test_stratified_sample_is_deterministic_and_covers_ends():
    fake = [{"call_id": f"c{i}"} for i in range(1000)]
    first = sample_execs(fake)
    second = sample_execs(fake)
    assert [e["call_id"] for e in first] == [e["call_id"] for e in second]
    assert first[0]["call_id"] == "c0"  # start of session always sampled
    assert first[-1]["call_id"] == "c999"  # end always sampled
    assert len(first) == PER_SESSION


def test_sample_caps_at_per_session_for_small_sessions():
    small = [{"call_id": f"c{i}"} for i in range(10)]
    assert len(sample_execs(small)) == 10


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
    assert numbered, "confirm list has no numbered samples"
    assert numbered[0].startswith("  1."), "numbering must start at 1 so corrections can reference it"


@pytest.mark.skipif(not STORE_PRESENT, reason="omp session store not available")
def test_confirm_output_matches_committed(tmp_path):
    """Regenerating the confirmation list must exactly reproduce the
    committed artifact — drift fails the test instead of silently rewriting
    the repo tree (derived data is regenerated, never hand-edited)."""
    out = tmp_path / "confirm.md"
    assert confirm(out) == 0
    committed = HERE.parent.parent / "analysis" / "findings" / "s1-confirm.md"
    assert out.read_text(encoding="utf-8") == committed.read_text(encoding="utf-8")


@pytest.mark.skipif(not STORE_PRESENT, reason="omp session store not available")
def test_session_openings_are_recognizable():
    """Every sample session gets a repo, an opening user message, and a tool
    mix — the recognition anchor for adjudicating samples on a phone."""
    openings = session_openings()
    assert len(openings) == 4
    for o in openings:
        assert o.repo
        assert o.user, f"{o.label} has no opening user message"
        assert o.hist, f"{o.label} has no tool mix"


def test_apply_labels_folds_disagreements_into_ground_truth(tmp_path):
    from sdl_flow_optimiser.findings.labels import Labels

    gt_path = tmp_path / "gt.json"
    labels_path = tmp_path / "labels.jsonl"
    gt_path.write_text(json.dumps({"a": 6, "b": 6}) + "\n", encoding="utf-8")
    stores = Labels(labels_path=labels_path)
    stores.add_label("a", True, None, "")  # agreement: no change
    stores.add_label("b", False, 1, "research")  # correction
    stores.add_label("c", False, None, "unresolved")  # no phase: no change
    apply_labels(labels_path, gt_path)
    truth = json.loads(gt_path.read_text(encoding="utf-8"))
    assert truth["a"] == 6
    assert truth["b"] == 1
    assert "c" not in truth  # comment-only disagreement adds nothing
    # idempotent
    apply_labels(labels_path, gt_path)
    assert json.loads(gt_path.read_text(encoding="utf-8"))["b"] == 1


def test_delegation_inherits_parent_phase():
    """A task spawn between execute events takes execute; a scout check in a
    prd research run takes prd — the event's own signature is irrelevant."""
    from sdl_flow_optimiser.phase_attribution import Execution

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

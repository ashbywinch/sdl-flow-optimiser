"""Finding S1 data integrity: ground truth matches the dump, values are valid.

Guards the committed evidence: if the dump or ground truth drift (regenerated
against a different sample, hand-edited, corrupted), the S1 finding's numbers
become unreproducible — this test fails instead.
"""

import json
from pathlib import Path

import pytest

from sdl_flow_optimiser.findings.attribution_feasibility import PER_SESSION, confirm, find_files, sample_execs

HERE = Path(__file__).resolve().parent.parent / "sdl_flow_optimiser" / "findings"

STORE_PRESENT = len(find_files()) == 5  # the omp session store lives on this machine


def _load():
    dump = [json.loads(line) for line in (HERE / "s1_dump.jsonl").read_text(encoding="utf-8").splitlines()]
    truth = json.loads((HERE / "s1_ground_truth.json").read_text(encoding="utf-8"))
    return dump, truth


def test_dump_has_five_sessions_of_per_session_samples():
    dump, _ = _load()
    sessions = {row["session"] for row in dump}
    assert len(sessions) == 5
    assert len(dump) == 5 * PER_SESSION


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
def test_confirm_generates_on_demand():
    path = HERE.parent.parent / "analysis" / "findings" / "s1-confirm.md"
    before = path.read_text(encoding="utf-8") if path.exists() else ""
    assert confirm() == 0
    after = path.read_text(encoding="utf-8")
    assert after == before or "# S1 confirmation" in after
    assert "## Disagreements" in after

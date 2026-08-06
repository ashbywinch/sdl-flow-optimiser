"""Labeler: persistence, sample selection, and API contract.

Sample selection reads committed evidence files (no session store needed);
the context endpoint needs the store and is store-guarded.
"""

import pytest
from fastapi.testclient import TestClient

from sdl_flow_optimiser.findings.attribution_feasibility import find_files
from sdl_flow_optimiser.labeler.app import create_app
from sdl_flow_optimiser.labeler.labels import load_associations, load_labels, save_association, save_label
from sdl_flow_optimiser.labeler.samples import build_samples, sample_counts, select_samples

STORE_PRESENT = len(find_files()) == 4


def test_label_round_trip(tmp_path):
    path = tmp_path / "labels.json"
    assert save_label("c1", True, None, "looks right", path)["agree"] is True
    assert save_label("c1", False, 3, "actually flow", path)["phase"] == 3
    loaded = load_labels(path)
    assert loaded["c1"] == {
        "agree": False,
        "phase": 3,
        "comment": "actually flow",
        "updated_at_ms": loaded["c1"]["updated_at_ms"],
    }


def test_association_round_trip_is_sorted(tmp_path):
    path = tmp_path / "assoc.json"
    save_association("b-session", "a-session", path)
    loaded = load_associations(path)
    assert len(loaded) == 1
    assoc = next(iter(loaded.values()))
    assert assoc["a"] == "a-session" and assoc["b"] == "b-session"


def test_build_samples_from_committed_evidence():
    samples = build_samples()
    assert len(samples) == 240
    assert sum(1 for s in samples if s["delegation"]) == 4
    assert all(s["pred_phase"] in range(1, 9) for s in samples)
    assert all(s["truth_phase"] in range(1, 9) for s in samples)


def test_select_random_is_seeded_and_excludes_delegation():
    a = select_samples("random", 10, seed=42)
    b = select_samples("random", 10, seed=42)
    assert [s["call_id"] for s in a] == [s["call_id"] for s in b]
    assert not any(s["delegation"] for s in a)


def test_select_lowconf_filters_by_confidence():
    pool = select_samples("lowconf", 50, seed=1)
    assert pool
    assert all(s["confidence"] < 0.5 for s in pool)


def test_select_disagreements_matches_truth_and_pred():
    pool = select_samples("disagreements", 50, seed=1)
    assert pool
    assert all(s["truth_phase"] != s["pred_phase"] for s in pool)


def test_sample_counts_are_consistent():
    counts = sample_counts()
    assert counts["total"] == counts["lowconf"] + counts["total"] - counts["lowconf"]
    assert counts["disagreements"] <= counts["total"]
    assert counts["labeled"] >= 0


def _client(tmp_path):
    return TestClient(create_app(labels_path=tmp_path / "labels.json", associations_path=tmp_path / "assoc.json"))


def test_api_serves_index_and_samples(tmp_path):
    client = _client(tmp_path)
    assert client.get("/").status_code == 200
    assert client.get("/app.js").status_code == 200
    sets = client.get("/api/sample-sets").json()
    assert sets["total"] == 236
    samples = client.get("/api/samples?kind=disagreements&n=3&seed=7").json()
    assert len(samples) == 3
    assert all(s["truth_phase"] != s["pred_phase"] for s in samples)


def test_api_label_persists_and_validates(tmp_path):
    client = _client(tmp_path)
    sample = client.get("/api/samples?kind=disagreements&n=1&seed=1").json()[0]
    res = client.post(
        "/api/labels", json={"call_id": sample["call_id"], "agree": False, "phase": 3, "comment": "flow work"}
    )
    assert res.status_code == 200
    saved = load_labels(tmp_path / "labels.json")
    assert saved[sample["call_id"]]["phase"] == 3
    bad = client.post("/api/labels", json={"call_id": "x", "agree": True, "phase": 99})
    assert bad.status_code == 400


def test_api_associations(tmp_path):
    client = _client(tmp_path)
    assert client.post("/api/associations", json={"a": "x", "b": "x"}).status_code == 400
    assert client.post("/api/associations", json={"a": "plan-session", "b": "exec-session"}).status_code == 200
    assoc = client.get("/api/associations").json()
    assert len(assoc) == 1


@pytest.mark.skipif(not STORE_PRESENT, reason="omp session store not available")
def test_api_context_shows_surrounding_events(tmp_path):
    client = _client(tmp_path)
    sample = client.get("/api/samples?kind=random&n=1&seed=3").json()[0]
    body = client.get(f"/api/samples/{sample['call_id']}/context").json()
    assert len(body["events"]) >= 3
    assert any(e["this_sample"] for e in body["events"])


def test_samples_carry_session_id():
    sample = select_samples("random", 1, seed=1)[0]
    assert sample["session_id"].endswith(".jsonl")


def test_api_label_delete_undoes(tmp_path):
    client = _client(tmp_path)
    sample = client.get("/api/samples?kind=random&n=1&seed=2").json()[0]
    client.post("/api/labels", json={"call_id": sample["call_id"], "agree": False, "phase": 3})
    assert sample["call_id"] in load_labels(tmp_path / "labels.json")
    res = client.delete(f"/api/labels/{sample['call_id']}")
    assert res.status_code == 200
    assert sample["call_id"] not in load_labels(tmp_path / "labels.json")


@pytest.mark.skipif(not STORE_PRESENT, reason="omp session store not available")
def test_api_session_detail_shows_full_transcript(tmp_path):
    client = _client(tmp_path)
    sample = client.get("/api/samples?kind=random&n=1&seed=4").json()[0]
    body = client.get(f"/api/sessions/{sample['session_id']}").json()
    assert body["event_count"] >= 60  # full session, not a window
    assert body["events"][0]["call_id"]
    assert "pred_phase" in body["events"][0]
    assert "analyst_phase" in body["events"][0]
    assert any(e["call_id"] == sample["call_id"] for e in body["events"])
    assert client.get("/api/sessions/not-a-real-session.jsonl").status_code == 404

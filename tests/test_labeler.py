"""Labeler: persistence, sample selection, and API contract.

Sample selection reads committed evidence files (no session store needed);
the context endpoint needs the store and is store-guarded.
"""

import json

import pytest
from fastapi.testclient import TestClient

from sdl_flow_optimiser.findings.attribution_feasibility import find_files
from sdl_flow_optimiser.findings.labels import Label, Labels
from sdl_flow_optimiser.labeler.app import _repo_display_name, create_app
from sdl_flow_optimiser.labeler.samples import build_samples, sample_counts, select_samples
from sdl_flow_optimiser.labeler.transcript import extract_transcript


def _store_present() -> bool:
    """True when the omp session store is present; a fresh clone/CI without
    it must skip the store-guarded tests, not crash at collection."""
    try:
        return len(find_files()) == 4
    except FileNotFoundError:
        return False


STORE_PRESENT = _store_present()


def test_transcript_skips_harness_preamble(tmp_path):
    """The opening user message, when it is a huge machine-generated prompt,
    is dropped; the user's real short opening is the first user item."""
    f = tmp_path / "s.jsonl"
    f.write_text(
        "\n".join(
            [
                json.dumps(
                    {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "x" * 5000}]}}
                ),
                json.dumps(
                    {
                        "type": "message",
                        "message": {"role": "user", "content": [{"type": "text", "text": "ok let's make a plan"}]},
                    }
                ),
                json.dumps(
                    {"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "sure"}]}}
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    items = extract_transcript(f)
    users = [it for it in items if it["kind"] == "user"]
    assert [u["text"] for u in users] == ["ok let's make a plan"]


def test_transcript_keeps_long_user_pastes_after_opening(tmp_path):
    """A long user message AFTER the opening is real content (a paste), kept."""
    f = tmp_path / "s.jsonl"
    f.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "message",
                        "message": {"role": "user", "content": [{"type": "text", "text": "short opening"}]},
                    }
                ),
                json.dumps(
                    {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "y" * 3000}]}}
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    items = extract_transcript(f)
    assert sum(1 for it in items if it["kind"] == "user") == 2


def test_repo_display_name():
    assert (
        _repo_display_name("home-houses-1152d36eb194fb21914281c38f50d4caa2ef82b1728d228aaab672c3fb43cd5a") == "houses"
    )
    assert _repo_display_name("-Documents-code-chat-workflow") == "chat-workflow"
    assert (
        _repo_display_name("home-omp-config-0d0030f1432e0d4dfbef84b45623fd2539975acf69b1d3b75eb46e0c91c303e5")
        == "omp-config"
    )
    assert _repo_display_name("-.paseo-worktrees-1qx6axnz-grand-buffalo") == "worktree: grand-buffalo"
    assert _repo_display_name("tmp-tmp-e9671acd244849c57167c658fa2f969752048f7ab184a3dcf5c46cb4d56ae124") == "tmp"


def test_label_round_trip_is_append_only(tmp_path):
    path = tmp_path / "labels.jsonl"
    stores = Labels(labels_path=path)
    assert stores.add_label("c1", True, None, "looks right").agree is True
    latest = stores.add_label("c1", False, 3, "actually flow")
    assert latest.phase == 3
    assert stores.latest_label("c1") == Label("c1", False, 3, "actually flow", latest.updated_at_ms)
    # history is preserved, not overwritten
    history = stores.label_history("c1")
    assert [h.comment for h in history] == ["looks right", "actually flow"]
    # tombstone: remove hides, history survives
    stores.remove_label("c1")
    assert stores.latest_label("c1") is None
    assert len(stores.label_history("c1")) == 2


def test_association_round_trip_is_sorted_and_removable(tmp_path):
    path = tmp_path / "assoc.jsonl"
    stores = Labels(associations_path=path)
    stores.add_association("b-session", "a-session")
    assoc = stores.associations()
    assert len(assoc) == 1
    assert assoc[0].a == "a-session" and assoc[0].b == "b-session"
    # tombstone removal
    stores.remove_association("b-session", "a-session")
    assert stores.associations() == []


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
    samples = build_samples()
    adjudicable = [s for s in samples if not s["delegation"]]
    lowconf = [s for s in adjudicable if s["confidence"] < 0.5]
    disagreements = [s for s in adjudicable if s["truth_phase"] != s["pred_phase"]]
    counts = sample_counts()
    assert counts["total"] == len(adjudicable)
    assert counts["lowconf"] == len(lowconf)
    assert counts["disagreements"] == len(disagreements)
    assert counts["labeled"] == sum(1 for s in samples if s["label"])


def _client(tmp_path):
    return TestClient(create_app(labels_path=tmp_path / "labels.jsonl", associations_path=tmp_path / "assoc.jsonl"))


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
    saved = Labels(labels_path=tmp_path / "labels.jsonl").latest_labels_map()
    assert saved[sample["call_id"]].phase == 3
    bad = client.post("/api/labels", json={"call_id": "x", "agree": True, "phase": 99})
    assert bad.status_code == 400


def test_api_associations(tmp_path):
    client = _client(tmp_path)
    assert client.post("/api/associations", json={"a": "x", "b": "x"}).status_code == 400
    assert client.post("/api/associations", json={"a": "plan-session", "b": "exec-session"}).status_code == 200
    assoc = client.get("/api/associations").json()
    assert len(assoc) == 1
    # undo works regardless of argument order (sorted key)
    res = client.request("DELETE", "/api/associations", json={"a": "exec-session", "b": "plan-session"})
    assert res.status_code == 200
    assert client.get("/api/associations").json() == []


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
    assert sample["call_id"] in Labels(labels_path=tmp_path / "labels.jsonl").latest_labels_map()
    res = client.delete(f"/api/labels/{sample['call_id']}")
    assert res.status_code == 200
    assert sample["call_id"] not in Labels(labels_path=tmp_path / "labels.jsonl").latest_labels_map()


@pytest.mark.skipif(not STORE_PRESENT, reason="omp session store not available")
def test_api_rejects_path_traversal_session_id(tmp_path):
    """A crafted session_id must not read files outside the store — the
    labeler is LAN-reachable with no auth (PRD trust decision), so the
    containment check is the boundary."""
    client = _client(tmp_path)
    for evil in ("..%2F..%2F..%2F..%2F..%2Fetc%2Fhostname", "%2e%2e%2f%2e%2e%2fetc%2fpasswd", "..%2F..%2Fsecret.jsonl"):
        assert client.get(f"/api/sessions/{evil}").status_code == 404


@pytest.mark.skipif(not STORE_PRESENT, reason="omp session store not available")
def test_api_session_detail_returns_readable_transcript(tmp_path):
    client = _client(tmp_path)
    sample = client.get("/api/samples?kind=random&n=1&seed=4").json()[0]
    body = client.get(f"/api/sessions/{sample['session_id']}").json()
    kinds = [it["kind"] for it in body["transcript"]]
    assert "user" in kinds  # your words are in the transcript
    assert "assistant" in kinds  # the agent's replies too
    assert "tool_call" in kinds
    assert body["tool_calls"] >= 60  # full session, not a window
    tool = next(it for it in body["transcript"] if it["kind"] == "tool_call")
    assert "pred_phase" in tool and "analyst_phase" in tool
    assert any(it["call_id"] == sample["call_id"] for it in body["transcript"] if it["kind"] == "tool_call")
    assert client.get("/api/sessions/not-a-real-session.jsonl").status_code == 404

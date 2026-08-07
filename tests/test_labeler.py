"""Labeler: persistence, phase selection, and API contract.

Phase selection reads committed evidence files (no session store needed);
the context endpoint needs the store and is store-faked via the fake_store
fixture (tests must run identically everywhere — see testing-standards).
"""

import json
from urllib.parse import quote

from fastapi.testclient import TestClient

from sdl_flow_optimiser.findings.labels import Labels
from sdl_flow_optimiser.findings.transcript import Transcript
from sdl_flow_optimiser.labeler.app import _repo_display_name, create_app
from sdl_flow_optimiser.labeler.samples import build_samples, sample_counts, select_samples


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
    items = Transcript.from_session_file(f).items
    users = [it for it in items if it.kind == "user"]
    assert [u.text for u in users] == ["ok let's make a plan"]


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
    items = Transcript.from_session_file(f).items
    assert sum(1 for it in items if it.kind == "user") == 2


def test_transcript_phases_are_user_delimited_and_merged(tmp_path):
    """A phase runs from one user message to the next — agent replies and
    tool results never split it; adjacent same-phase spans merge."""
    f = tmp_path / "s.jsonl"
    f.write_text(
        "\n".join(
            [
                json.dumps(
                    {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "fix it"}]}}
                ),
                json.dumps(
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {"type": "text", "text": "on it"},
                                {"type": "toolCall", "id": "c1", "name": "edit", "arguments": {}},
                            ],
                        },
                    }
                ),
                json.dumps({"type": "message", "message": {"role": "toolResult", "toolCallId": "c1"}}),
                json.dumps(
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {"type": "text", "text": "done"},
                                {"type": "toolCall", "id": "c2", "name": "edit", "arguments": {}},
                            ],
                        },
                    }
                ),
                json.dumps({"type": "message", "message": {"role": "toolResult", "toolCallId": "c2"}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    runs = Transcript.from_session_file(f).runs()
    # one user message, one phase — the assistant's replies did not split it
    assert len(runs) == 1
    assert runs[0].call_ids == ("c1", "c2")


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


def test_run_verdict_round_trip_is_append_only(tmp_path):
    path = tmp_path / "labels.jsonl"
    stores = Labels(labels_path=path)
    verdict = stores.add_run_verdict("sess#3", 6, "execute work")
    assert stores.latest_run_verdict("sess#3") == verdict
    stores.remove_run_verdict("sess#3")
    assert stores.latest_run_verdict("sess#3") is None
    assert len(stores.latest_run_verdicts()) == 0


def test_build_samples_from_committed_evidence():
    samples = build_samples()
    assert len(samples) == 48  # all phases of the four sample sessions
    assert all(s["pred_phase"] in range(1, 9) for s in samples)
    assert all(s["truth_phase"] is None or s["truth_phase"] in range(1, 9) for s in samples)
    assert sum(1 for s in samples if s["truth_phase"] is None) == 9  # the unlabeled phases


def test_select_random_is_seeded():
    a = select_samples("random", 10, seed=42)
    b = select_samples("random", 10, seed=42)
    assert [s["phase_id"] for s in a] == [s["phase_id"] for s in b]


def test_select_lowconf_filters_by_confidence():
    pool = select_samples("lowconf", 50, seed=1)
    assert all(s["confidence"] < 0.5 for s in pool)


def test_select_disagreements_matches_truth_and_pred():
    pool = select_samples("disagreements", 50, seed=1)
    assert pool
    assert all(s["truth_phase"] is not None and s["truth_phase"] != s["pred_phase"] for s in pool)


def test_sample_counts_are_consistent():
    samples = build_samples()
    counts = sample_counts()
    assert counts.total == len(samples)
    assert counts.labeled == sum(1 for s in samples if s["truth_phase"] is not None)
    assert counts.disagreements == sum(
        1 for s in samples if s["truth_phase"] is not None and s["truth_phase"] != s["pred_phase"]
    )


def _client(tmp_path, store_path=None):
    kwargs = {"store_path": store_path} if store_path else {}
    return TestClient(
        create_app(labels_path=tmp_path / "labels.jsonl", associations_path=tmp_path / "assoc.jsonl", **kwargs)
    )


def test_api_serves_index_and_samples(tmp_path):
    client = _client(tmp_path)
    assert client.get("/").status_code == 200
    assert client.get("/app.js").status_code == 200
    sets = client.get("/api/sample-sets").json()
    assert sets["total"] == 48
    samples = client.get("/api/samples?kind=disagreements&n=3&seed=7").json()
    assert len(samples) == 3
    assert all(s["truth_phase"] != s["pred_phase"] for s in samples)


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


def test_api_verdicts_fold_into_ground_truth(tmp_path, fake_store):
    from sdl_flow_optimiser.findings.attribution_feasibility import find_files

    client = _client(tmp_path, fake_store)
    first_session = find_files(fake_store)[0].path
    phase_id = Transcript.from_session_file(first_session).runs()[0].run_id
    encoded = quote(phase_id, safe="")  # run_ids carry a # — must be URL-encoded
    res = client.post(f"/api/runs/{encoded}/verdict", json={"phase": 5, "comment": "planning"})
    assert res.status_code == 200
    verdict = Labels(labels_path=tmp_path / "labels.jsonl").latest_run_verdict(phase_id)
    assert verdict is not None and verdict.phase == 5
    assert client.delete(f"/api/runs/{encoded}/verdict").status_code == 200
    assert Labels(labels_path=tmp_path / "labels.jsonl").latest_run_verdict(phase_id) is None


def test_api_context_shows_a_phase(fake_store, tmp_path):
    client = _client(tmp_path, fake_store)
    sample = client.get("/api/samples?kind=random&n=1&seed=3").json()[0]
    body = client.get(f"/api/samples/{quote(sample['phase_id'], safe='')}/context").json()
    assert body["user"]  # the human's opening words
    assert body["pred_phase"] == sample["pred_phase"]
    assert len(body["events"]) == sample["tools"]  # the phase's calls
    assert client.get("/api/samples/not-a-real-phase/context").status_code == 404


def test_samples_carry_session_id():
    sample = select_samples("random", 1, seed=1)[0]
    assert sample["session_id"].endswith(".jsonl")


def test_api_rejects_path_traversal_session_id(fake_store, tmp_path):
    """A crafted session_id must not read files outside the store — the
    labeler is LAN-reachable with no auth (PRD trust decision), so the
    containment check is the boundary."""
    client = _client(tmp_path, fake_store)
    for evil in ("..%2F..%2F..%2F..%2F..%2Fetc%2Fhostname", "%2e%2e%2f%2e%2e%2fetc%2fpasswd", "..%2F..%2Fsecret.jsonl"):
        assert client.get(f"/api/sessions/{evil}").status_code == 404


def test_api_session_detail_returns_readable_transcript(fake_store, tmp_path):
    client = _client(tmp_path, fake_store)
    sample = client.get("/api/samples?kind=random&n=1&seed=4").json()[0]
    body = client.get(f"/api/sessions/{sample['session_id']}").json()
    kinds = [it["kind"] for it in body["transcript"]]
    assert "user" in kinds  # your words are in the transcript
    assert "assistant" in kinds  # the agent's replies too
    assert "tool_call" in kinds
    assert body["tool_calls"] >= 60  # full session, not a window
    assert body["runs"] and body["runs"][0]["first_intent"]  # phases carry the human's words
    assert client.get("/api/sessions/not-a-real-session.jsonl").status_code == 404

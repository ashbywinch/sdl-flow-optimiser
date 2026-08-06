"""Phase attribution contract: rule ordering, tool signals, confidence, fallback."""

import pytest

from sdl_flow_optimiser.phase_attribution import PHASE_NAMES, PhasePrediction, assign_phase, is_delegation


def test_returns_prediction_object():
    p = assign_phase("edit", "Fix the import", '{"path": "app/views/cast.js"}')
    assert isinstance(p, PhasePrediction)
    assert p.phase_id == 6
    assert 0.0 <= p.confidence <= 1.0
    assert p.rule


@pytest.mark.parametrize(
    ("tool", "intent", "args", "phase"),
    [
        ("edit", "Fix the import", '{"path": "app/views/cast.js"}', 6),
        ("write", "Add a test", '{"path": "tests/test_x.py"}', 6),
        ("ast_edit", "Rename symbol", '{"path": "app/x.py"}', 6),
        ("lsp", "Find references", '{"path": "app/x.py"}', 6),
        ("eval", "Run a cell", '{"code": "x = 1"}', 6),
        ("debug", "Set breakpoint", "{}", 6),
        ("bash", "Run the test suite", '{"command": "make test"}', 6),
    ],
)
def test_execute_tools_map_to_execute(tool, intent, args, phase):
    assert assign_phase(tool, intent, args).phase_id == phase


def test_execute_tool_confidence_is_high():
    assert assign_phase("edit", "Fix the import", "{}").confidence >= 0.8


@pytest.mark.parametrize(
    ("intent", "args", "phase"),
    [
        ("Create pull request", '{"command": "gh pr create"}', 7),
        ("Push branch", '{"command": "git push"}', 7),
        ("Poll review completion", '{"command": "gh pr view 48"}', 7),
        ("Read latest review comment", "{}", 7),
        ("Fix review findings", '{"path": "app/x.py"}', 7),
        ("Merge the branch", '{"command": "git merge main"}', 7),
    ],
)
def test_pr_signals_map_to_pr_review(intent, args, phase):
    assert assign_phase("bash", intent, args).phase_id == phase


def test_flow_design_precedes_tech_design():
    # "import flow design" is phase 3, not "design" (phase 2)
    assert assign_phase("todo", "Starting import flow design", "{}").phase_id == 3


@pytest.mark.parametrize(
    ("intent", "args", "phase"),
    [
        ("Record alignment decision", '{"path": "docs/TECH-SPEC.md"}', 2),
        ("Research cheap embedding models", "{}", 2),
        ("Choose the database", '{"path": "docs/TECHSPEC.md"}', 2),
    ],
)
def test_tech_design_signals(intent, args, phase):
    assert assign_phase("edit", intent, args).phase_id == phase


@pytest.mark.parametrize(
    ("intent", "args", "phase"),
    [
        ("", '{"path": "docs/prd-phase2.md"}', 1),
        ("Resolve PRD scope gaps", "{}", 1),
        ("Record requirement in PRD", '{"path": "docs/PRD.md"}', 1),
    ],
)
def test_prd_signals(intent, args, phase):
    assert assign_phase("write", intent, args).phase_id == phase


def test_ask_maps_to_prd():
    assert assign_phase("ask", "Agree on typecheck policy", "{}").phase_id == 1


def test_dev_plan_via_todo():
    assert assign_phase("todo", "Track plan implementation", "{}").phase_id == 5
    assert assign_phase("edit", "", '{"path": "docs/PLAN.md"}').phase_id == 5


@pytest.mark.parametrize(
    ("tool", "intent", "args", "phase"),
    [
        ("browser", "Verifying tree after filter", "{}", 8),
        ("write", "Read page 4", '{"path": "xd://inspect_image"}', 8),
        ("browser", "Walk the login flow", "{}", 8),
    ],
)
def test_ux_loop_signals(tool, intent, args, phase):
    assert assign_phase(tool, intent, args).phase_id == phase


def test_breakdown_via_backlog():
    assert assign_phase("bash", "Groom the backlog", "{}").phase_id == 4


def test_research_keyword_maps_to_prd_without_position():
    p = assign_phase("read", "read example skill format", '{"path": "skills/x"}')
    assert p.phase_id == 1
    assert p.confidence < 0.8  # keyword signal is weaker than a direct rule


def test_research_at_session_start_raises_confidence():
    p = assign_phase("read", "read example skill format", "{}", position_ratio=0.05)
    assert p.phase_id == 1
    assert p.confidence >= 0.5


def test_research_mid_session_without_keyword_is_execute():
    p = assign_phase("read", "Read the TestCallback section", '{"path": "tests/test_auth.py"}', position_ratio=0.5)
    assert p.phase_id == 6
    assert p.confidence <= 0.5  # low confidence — flagged for confirmation


def test_unknown_tool_falls_back_to_execute():
    p = assign_phase("mystery_tool", "Do a thing", "{}")
    assert p.phase_id == 6
    assert p.confidence < 0.5


def test_matching_is_case_insensitive():
    assert assign_phase("bash", "CREATE PULL REQUEST", "{}").phase_id == 7
    assert assign_phase("read", "Read TECH-SPEC", "{}").phase_id == 2


def test_research_start_via_config_path_is_case_insensitive():
    # "Makefile" capital M in args must match the lowercase pattern
    p = assign_phase(
        "read", "read chat-workflow Makefile", '{"path": "/home/x/chat-workflow/Makefile"}', position_ratio=0.07
    )
    assert p.phase_id == 1
    assert p.confidence >= 0.5


def test_research_config_read_mid_session_stays_execute():
    p = assign_phase(
        "read", "read chat-workflow Makefile", '{"path": "/home/x/chat-workflow/Makefile"}', position_ratio=0.5
    )
    assert p.phase_id == 6


def test_design_research_via_env_signals():
    assert assign_phase("web_search", "check uv run env-file semantics", "{}").phase_id == 2
    assert assign_phase("read", "Read houses env example", '{"path": "/home/x/houses/.env.example"}').phase_id == 2


def test_env_signal_in_edit_is_execute_not_design():
    # edits touching .env.example are config work, not tech design
    assert assign_phase("edit", "updating env example publish section", '{"path": ".env.example"}').phase_id == 6


def test_survey_bash_at_session_start_is_prd():
    p = assign_phase("bash", "list skills rules profiles", "{}", position_ratio=0.02)
    assert p.phase_id == 1
    assert p.confidence >= 0.5


def test_survey_bash_mid_session_is_execute():
    assert assign_phase("bash", "List all failures", "{}", position_ratio=0.85).phase_id == 6


def test_prd_rule_precedes_embedding_keyword():
    # "PRD to gemini-embedding-001" is a PRD edit, not tech design
    assert assign_phase("edit", "Update PRD to gemini-embedding-001", "{}").phase_id == 1


def test_task_spawn_is_delegation():
    assert is_delegation("task", "")
    assert is_delegation("task", "Refactor the auth module")


def test_hub_scout_coordination_is_delegation():
    assert is_delegation("hub", "check scout jobs status")
    assert is_delegation("hub", "wait for remaining scouts")
    assert is_delegation("hub", "wait for one-shot scaffold test")


def test_hub_process_management_is_not_delegation():
    assert not is_delegation("hub", "Start frontend on 5173")
    assert not is_delegation("hub", "Stop stuck spike")
    assert not is_delegation("hub", "Follow spike log for stage 4")
    assert not is_delegation("hub", "Run device-flow login via hub")


def test_phase_names_cover_all_phases():
    assert set(PHASE_NAMES) == {1, 2, 3, 4, 5, 6, 7, 8}

"""Classifier contract: rule ordering, tool signals, fallback."""

from sdl_flow_optimiser.classifier import PHASE_NAMES, classify_execution


def test_execute_tools_map_to_execute():
    assert classify_execution("edit", "Fix the import", '{"path": "app/views/cast.js"}')[0] == 6
    assert classify_execution("bash", "Run the test suite", '{"command": "make test"}')[0] == 6


def test_pr_signals_map_to_pr_review():
    assert classify_execution("bash", "Create pull request", '{"command": "gh pr create"}')[0] == 7
    assert classify_execution("bash", "Push branch", '{"command": "git push"}')[0] == 7
    assert classify_execution("bash", "Poll review completion", '{"command": "gh pr view 48"}')[0] == 7


def test_flow_design_precedes_tech_design():
    # "import flow design" is phase 3, not "design" (phase 2)
    assert classify_execution("todo", "Starting import flow design", "{}")[0] == 3


def test_tech_design_via_path():
    assert classify_execution("edit", "Record alignment decision", '{"path": "docs/TECH-SPEC.md"}')[0] == 2
    assert classify_execution("web_search", "Research cheap embedding models", "{}")[0] == 2


def test_prd_signals():
    assert classify_execution("write", "", '{"path": "docs/prd-phase2.md"}')[0] == 1
    assert classify_execution("ask", "Resolve PRD scope gaps", "{}")[0] == 1
    assert classify_execution("ask", "Agree on typecheck policy", "{}")[0] == 1


def test_dev_plan_via_todo():
    assert classify_execution("todo", "Track plan implementation", "{}")[0] == 5


def test_ux_loop_via_browser():
    assert classify_execution("browser", "Verifying tree after filter", "{}")[0] == 8
    assert classify_execution("write", "Read page 4", '{"path": "xd://inspect_image"}')[0] == 8


def test_unknown_tool_falls_back_to_execute():
    assert classify_execution("mystery_tool", "Do a thing", "{}")[0] == 6


def test_phase_names_cover_all_phases():
    assert set(PHASE_NAMES) == {1, 2, 3, 4, 5, 6, 7, 8}

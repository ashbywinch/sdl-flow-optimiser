"""Rule-based phase classifier — the classify stage's core (S1 prototype).

Phases (PRD): 1 prd, 2 tech_design, 3 flow_design, 4 breakdown, 5 dev_plan,
6 execute, 7 pr_review, 8 ux_loop.

Ordered rules, first match wins; ambiguous activity falls back to execute.
The S1 investigation (sdl_flow_optimiser.investigate.s1_attribution) measures
per-phase agreement with hand labels — phase 1/3 planning activity is
expected to be weak here (research reads are indistinguishable from execution
reads by tool signature alone).
"""

from __future__ import annotations

import re

PHASE_NAMES: dict[int, str] = {
    1: "prd",
    2: "tech_design",
    3: "flow_design",
    4: "breakdown",
    5: "dev_plan",
    6: "execute",
    7: "pr_review",
    8: "ux_loop",
}

_EXECUTE_TOOLS: frozenset[str] = frozenset({"edit", "write", "ast_edit", "lsp", "eval", "debug"})

# Ordered: pr_review → flow_design → tech_design → breakdown → dev_plan →
# prd → ux_loop. flow_design must precede tech_design ("import flow design"
# is phase 3, not "design"); prd's "requirements" must not shadow interview
# docs, so interview patterns live in flow_design.
_RULES: list[tuple[int, re.Pattern[str]]] = [
    (
        7,
        re.compile(
            r"pr://|pr-workflow|pr-agent|review bot|gh pr|gh run|\bpr \d|pr body|pr state|"
            + r"review fix|review comment|review completion|round-\d+|bot run|merge|\bpush\b"
        ),
    ),
    (3, re.compile(r"flow design|interview|interviews/|transcript|narrator|worked example|walkthrough")),
    (2, re.compile(r"techspec|tech-spec|architecture|\bdesign\b|embedding|env-file|env\.example")),
    (4, re.compile(r"notion.*task|backlog|groom|ticket|epic.*breakdown")),
    (5, re.compile(r"docs/plan|plan\.md|dev plan|todo")),
    (1, re.compile(r"docs/prd|prd\.md|requirements|user-interviews|scope gaps")),
    (8, re.compile(r"ux review|usability|inspect_image|screenshot|browser")),
]


def classify_execution(tool: str, intent: str, args: str) -> tuple[int, str]:
    """Map one tool execution to a phase. Returns (phase_id, rule_label).

    `blob` combines tool name, intent, and args — all lowercase. Tool calls
    with no rule match and no strong tool signal fall back to execute.
    """
    blob = " ".join([tool, intent, args]).lower()
    for phase, pattern in _RULES:
        if pattern.search(blob):
            return phase, f"rule:{phase}"
    if tool in _EXECUTE_TOOLS:
        return 6, "execute-tool"
    if tool == "ask":
        return 1, "ask"
    if tool == "bash":
        return 6, "bash"
    return 6, "fallback"

"""Phase attribution — maps activity to the phase of development it belongs to.

Domain object: the `PhaseAssignment` (per-event evidence for phase runs; see
the model catalog). Phases (PRD): 1 prd, 2 tech_design, 3 flow_design,
4 breakdown, 5 dev_plan, 6 execute, 7 pr_review, 8 ux_loop.

Ordered rules, first match wins; ambiguous activity falls back to execute.
`confidence` encodes how sure the rule is — low-confidence predictions are
surfaced for human confirmation, never presented as fact (PRD constraint:
attribution is uncertain).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

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
_RESEARCH_TOOLS: frozenset[str] = frozenset({"read", "grep", "glob", "web_search"})

# Research reads in service of requirements work use surveying vocabulary or
# read config files of other repos; execution reads name a specific file or
# symbol. (S1: "read chat-workflow Makefile" at session start = prd; "Read
# /me endpoint response shape" mid-implementation = execute.)
_RESEARCH_KEYWORDS = re.compile(r"\b(example|locate|survey|landscape|how other|skills|rules|profiles)\b")
_SURVEY_KEYWORDS = re.compile(r"\b(list|locate|survey)\b")
_CONFIG_PATTERN = re.compile(r"\b(makefile|pyproject|\.github/workflows|agents\.md|editorconfig|gitignore|skill://)\b")

# Ordered: pr_review → flow_design → tech_design → breakdown → dev_plan →
# prd → ux_loop. flow_design precedes tech_design ("import flow design" is
# phase 3, not "design"); prd's "requirements" must not shadow interview
# docs, so interview patterns live in flow_design.
_RULES: list[tuple[int, re.Pattern[str], float]] = [
    (
        7,
        re.compile(
            r"pr://|pr-workflow|pr-agent|review bot|gh pr|gh run|\bpr \d|pr body|pr state|"
            + r"pull request|review fix|review finding|fix.*review|review comment|"
            + r"review completion|round-\d+|bot run|merge|\bpush\b"
        ),
        0.85,
    ),
    (3, re.compile(r"flow design|interview|interviews/|transcript|narrator|worked example|walkthrough"), 0.8),
    (1, re.compile(r"docs/prd|prd\.md|\bprd\b|requirements|user-interviews|scope gaps"), 0.85),
    (2, re.compile(r"techspec|tech-spec|architecture|\bdesign\b|embedding"), 0.75),
    (4, re.compile(r"notion.*task|backlog|groom|ticket|epic.*breakdown"), 0.85),
    (5, re.compile(r"docs/plan|plan\.md|dev plan|todo"), 0.85),
    (8, re.compile(r"ux review|usability|inspect_image|screenshot|browser"), 0.85),
]

# Design research (read/web_search only — env signals in rule 2 misfired on
# edits and greps whose search paths merely mention .env.example).
_DESIGN_KEYWORDS = re.compile(r"\b(embedding|tech-spec|architecture|design)\b|env-file|env\.example")


@dataclass(frozen=True)
class PhasePrediction:
    """One event's attributed phase, with how sure the rule was."""

    phase_id: int
    confidence: float
    rule: str


def assign_phase(tool: str, intent: str, args: str, position_ratio: float | None = None) -> PhasePrediction:
    """Attribute one tool execution to a phase.

    `blob` combines tool name, intent, and args — all lowercase. `position_ratio`
    (0.0–1.0 within the session) is optional context: research at the very start
    of a session is requirements work, not execution.
    """
    blob = " ".join([tool, intent, args]).lower()
    for phase, pattern, confidence in _RULES:
        if pattern.search(blob):
            return PhasePrediction(phase, confidence, f"rule:{phase}")
    intent_args = " ".join([intent, args]).lower()
    if tool in _RESEARCH_TOOLS:
        if (
            position_ratio is not None
            and position_ratio < 0.35
            and (_RESEARCH_KEYWORDS.search(intent) or _CONFIG_PATTERN.search(intent_args))
        ):
            return PhasePrediction(1, 0.6, "research-start")
        if tool in ("read", "web_search") and _DESIGN_KEYWORDS.search(intent_args):
            return PhasePrediction(2, 0.6, "design-research")
        if _RESEARCH_KEYWORDS.search(intent):
            return PhasePrediction(1, 0.5, "research-keyword")
        return PhasePrediction(6, 0.35, "fallback-research")
    if tool == "bash" and position_ratio is not None and position_ratio < 0.25 and _SURVEY_KEYWORDS.search(intent):
        return PhasePrediction(1, 0.55, "survey-start")
    if tool in _EXECUTE_TOOLS:
        return PhasePrediction(6, 0.9, "execute-tool")
    if tool == "ask":
        return PhasePrediction(1, 0.6, "ask")
    if tool == "bash":
        return PhasePrediction(6, 0.6, "bash")
    return PhasePrediction(6, 0.3, "fallback")

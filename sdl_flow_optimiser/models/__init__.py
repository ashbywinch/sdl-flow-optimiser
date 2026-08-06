"""Model catalog — every table maps 1:1 to a class (TECHSPEC decision).

Importing everything here gives Alembic autogenerate the full metadata.
"""

from sdl_flow_optimiser.models.base import JSON_VARIANT, Base
from sdl_flow_optimiser.models.derived import (
    PR,
    AnalysisRun,
    Bottleneck,
    CandidateLever,
    ClassifierEval,
    DocReference,
    Finding,
    IdleGap,
    Metric,
    PhaseAssignment,
    PhaseDefinition,
    PhaseSequence,
    Recommendation,
    WorkItem,
    WorkItemLink,
    WorkItemPhase,
)
from sdl_flow_optimiser.models.normalized import (
    AssistantCall,
    Event,
    IngestManifest,
    IngestRun,
    Project,
    Session,
    ToolExecution,
    UserMessage,
)

__all__ = [
    "JSON_VARIANT",
    "Base",
    "AnalysisRun",
    "AssistantCall",
    "Bottleneck",
    "CandidateLever",
    "ClassifierEval",
    "DocReference",
    "Event",
    "Finding",
    "IdleGap",
    "IngestManifest",
    "IngestRun",
    "Metric",
    "PR",
    "PhaseAssignment",
    "PhaseDefinition",
    "PhaseSequence",
    "Project",
    "Recommendation",
    "Session",
    "ToolExecution",
    "UserMessage",
    "WorkItem",
    "WorkItemLink",
    "WorkItemPhase",
]

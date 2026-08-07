"""Labeler — adjudicate phase attribution in a web tool (PRD: no metric
ships without measured confidence; the user marks the analyst's homework).

Backend: FastAPI. Persistence: committed JSON evidence files next to the
ground truth (s1_labels.json, s1_associations.json). No auth, local tool.
"""

from sdl_flow_optimiser.labeler.app import create_app

__all__ = ["create_app"]

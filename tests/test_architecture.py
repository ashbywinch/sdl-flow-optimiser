"""Enforce layer boundaries — models/core/stages/cli (TECHSPEC architecture)."""

from pathlib import Path
from typing import Any

from archunitpython.layers import project_layers

# archunitpython matches layer patterns against ABSOLUTE normalized file
# paths. Relative globs ("./x/*.py") compile to regexes anchored on "./"
# that match nothing — the check passes VACUOUSLY. Derive absolute patterns
# from the repo root (skill://archunitpython-glob-rules).
ROOT = str(Path(__file__).resolve().parents[1])  # repo root (tests/ -> 1 up)


def _format_violations(violations: list[Any]) -> str:
    lines = ["Layer violations found:"]
    for v in violations:
        dep = v.dependency
        lines.append(f"  {dep.source_label} → {dep.target_label}")
    return "\n".join(lines)


def test_layer_boundaries():
    """models standalone; core→models; classifier standalone; stages→models+core;
    investigate→classifier+core+models; cli→everything below.

    `*` crosses `/` in fnmatch, so `models/*.py` matches the whole tree
    under models/. The cli layer is the single root module file (plus
    __main__.py, which only imports cli).
    """
    la = project_layers()
    la = la.layer("models").defined_by(f"{ROOT}/sdl_flow_optimiser/models/*.py")
    la = la.layer("core").defined_by(f"{ROOT}/sdl_flow_optimiser/core/*.py")
    la = la.layer("stages").defined_by(f"{ROOT}/sdl_flow_optimiser/stages/*.py")
    la = la.layer("phase_attribution").defined_by(f"{ROOT}/sdl_flow_optimiser/phase_attribution.py")
    la = la.layer("findings").defined_by(f"{ROOT}/sdl_flow_optimiser/findings/*.py")
    la = la.layer("cli").defined_by(f"{ROOT}/sdl_flow_optimiser/cli.py")
    la = la.where_layer("models").may_only_depend_on_layers()
    la = la.where_layer("core").may_only_depend_on_layers("models")
    la = la.where_layer("stages").may_only_depend_on_layers("models", "core")
    la = la.where_layer("phase_attribution").may_only_depend_on_layers()
    la = la.where_layer("findings").may_only_depend_on_layers("phase_attribution", "core", "models")
    la = la.where_layer("cli").may_only_depend_on_layers("core", "models", "stages")
    violations = la.check()
    assert len(violations) == 0, _format_violations(violations)

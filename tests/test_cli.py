"""CLI: --version prints and exits 0; no args exits 0."""

import pytest

from sdl_flow_optimiser.cli import main


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "sdl-flow-optimiser" in out


def test_no_args_returns_zero():
    assert main([]) == 0

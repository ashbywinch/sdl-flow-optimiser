"""CLI entry point. Stage subcommands land per docs/PLAN.md phases."""

from __future__ import annotations

import argparse

from sdl_flow_optimiser import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sdl-flow-optimiser",
        description="Analyze omp session logs as a queuing system.",
    )
    _ = parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    _ = build_parser().parse_args(argv)
    return 0

"""Application settings, read from the environment only (never from files).

Real secrets live in the shell environment; .env is a dev convenience loaded
by `make run` via --env-file, where the real environment always wins.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DB_URL = "postgresql+psycopg://sdl:sdl@localhost:5432/sdl_flow_optimiser"


@dataclass(frozen=True)
class Settings:
    """Everything the pipeline needs to know at runtime."""

    db_url: str
    sessions_dir: Path

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            db_url=os.environ.get("SDL_DB_URL", DEFAULT_DB_URL),
            sessions_dir=Path(os.environ.get("SDL_SESSIONS_DIR", str(Path.home() / ".omp" / "agent" / "sessions"))),
        )

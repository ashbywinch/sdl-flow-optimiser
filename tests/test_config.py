"""Settings read from the environment only; real env wins over .env."""

from pathlib import Path

from sdl_flow_optimiser.core.config import DEFAULT_DB_URL, Settings


def test_defaults(monkeypatch):
    monkeypatch.delenv("SDL_DB_URL", raising=False)
    monkeypatch.delenv("SDL_SESSIONS_DIR", raising=False)
    settings = Settings.from_env()
    assert settings.db_url == DEFAULT_DB_URL
    assert settings.sessions_dir == Path.home() / ".omp" / "agent" / "sessions"


def test_env_override(monkeypatch):
    monkeypatch.setenv("SDL_DB_URL", "postgresql+psycopg://other:secret@db:5432/other")
    monkeypatch.setenv("SDL_SESSIONS_DIR", "/tmp/sessions")
    settings = Settings.from_env()
    assert settings.db_url == "postgresql+psycopg://other:secret@db:5432/other"
    assert settings.sessions_dir == Path("/tmp/sessions")

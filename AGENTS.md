# AGENTS.md

## Quick start

- `make setup` — venv, deps, pre-commit hooks, `.env` (copy of
  `.env.example`).
- `make run` — CLI; stage subcommands land per [docs/PLAN.md](docs/PLAN.md).
- `make db-up` — local Postgres via docker (needed from PLAN phase 1 on).
- `make test` — the only way tests run: lint + typecheck gate, then pytest.

## Testing rules

- Run tests via `make test`, never raw pytest — lint and typecheck gate.
- `make coverage` for the coverage report (XML consumed by CI).
- Tests mirror module paths; deterministic (SQLite in-memory, no network).

## Decision tree

- Product intent, scope, constraints → [docs/PRD.md](docs/PRD.md)
- Architecture, data model, tech choices → [docs/TECHSPEC.md](docs/TECHSPEC.md)
- Implementation phases and gates → [docs/PLAN.md](docs/PLAN.md)
- Code style and layering → [docs/coding-standards.md](docs/coding-standards.md)
- Test conventions → [docs/testing-standards.md](docs/testing-standards.md)
- Documentation quality → [docs/writing-documentation.md](docs/writing-documentation.md)
- Required doc set → [docs/documentation-structure.md](docs/documentation-structure.md)
- UX → [docs/ux-standards.md](docs/ux-standards.md)

## Tool selection

| Task | Tool |
|---|---|
| Parse session JSONL, normalize | stage `ingest` (Python stdlib + models) |
| DB access | SQLAlchemy models only — never raw SQL |
| Migrations | `make db-revision` / `make db-init` (Alembic) |
| Tests | `make test` (pytest) |
| Lint / format / types | `make lint` / `make format` / `make typecheck` |

## Git workflow

- Never commit to main; branch + PR, protected main.
- Atomic commits; reference issues (`Fixes #N`).

## Secrets

- Never put secrets in code, docs, logs, or `.env.example`.
- Real values live in the shell environment only; `.env` is a gitignored dev
  convenience loaded by `make run` via `--env-file` (real env wins).

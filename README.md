# sdl-flow-optimiser

Analyze omp session logs as a queuing system: surface the single
highest-impact process improvement, with evidence, and let you argue with it
in chat.

## Quick Start

```sh
make setup        # venv, deps, pre-commit hooks, .env
make db-up        # local Postgres (docker) — needed from phase 1 on
make run          # CLI (currently --version; stage subcommands per docs/PLAN.md)
make test         # lint + typecheck + tests
make coverage     # tests + coverage report
```

## Docs

| Doc | What it answers |
|---|---|
| [docs/PRD.md](docs/PRD.md) | Why — JTBD, personas, constraints, scope |
| [docs/TECHSPEC.md](docs/TECHSPEC.md) | How — architecture, data model, tech choices, spikes |
| [docs/PLAN.md](docs/PLAN.md) | In what order — phases, inputs/outputs, quality gates |
| [docs/coding-standards.md](docs/coding-standards.md) | How to write code here |
| [docs/testing-standards.md](docs/testing-standards.md) | How to write tests here |
| [docs/writing-documentation.md](docs/writing-documentation.md) | What good documentation is |
| [docs/documentation-structure.md](docs/documentation-structure.md) | Required doc set |
| [docs/ux-standards.md](docs/ux-standards.md) | UX standard |

## Notes

- All pipeline outputs persist to a local Postgres DB; artifacts are
  serialized views of the latest analysis run.
- The omp session store is read-only input; nothing leaves the machine.

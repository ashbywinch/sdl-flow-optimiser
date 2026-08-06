# Makefile for sdl-flow-optimiser
.PHONY: help setup run lint lint-github typecheck test coverage format clean \
	db-up db-down db-init db-revision web

PYTHON := .venv/bin/python
RUFF := .venv/bin/ruff
BASEDPYRIGHT := .venv/bin/basedpyright
PG_CONTAINER := sdl-flow-optimiser-pg

GREEN := \033[0;32m
NC := \033[0m

help:
	@echo "Available commands:"
	@echo "  ${GREEN}make setup${NC}        Create venv, install deps + pre-commit hooks, ensure .env exists"
	@echo "  ${GREEN}make run${NC}          Run the CLI (loads .env; real env wins)"
	@echo "  ${GREEN}make lint${NC}         Check code quality"
	@echo "  ${GREEN}make typecheck${NC}    Static type check (basedpyright)"
	@echo "  ${GREEN}make test${NC}         Run tests (lint + typecheck gate)"
	@echo "  ${GREEN}make coverage${NC}     Run tests with coverage report"
	@echo "  ${GREEN}make format${NC}       Auto-fix formatting issues"
	@echo "  ${GREEN}make clean${NC}        Remove .venv and generated files"
	@echo "  ${GREEN}make db-up${NC}        Start local Postgres (docker)"
	@echo "  ${GREEN}make db-down${NC}      Stop local Postgres (docker)"
	@echo "  ${GREEN}make db-init${NC}      Apply migrations to the DB"
	@echo "  ${GREEN}make db-revision${NC}  Autogenerate a migration (needs DB up)"
	@echo "  ${GREEN}make web${NC}          Run the labeler web app on http://<laptop-ip>:8010 (LAN, no auth)"

setup:
	@uv --version >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
	@uv sync
	@uv run pre-commit install
	@[ -f .env ] || cp .env.example .env

run: setup
	@uv run --env-file .env python -m sdl_flow_optimiser

lint: setup
	@$(RUFF) check sdl_flow_optimiser/ tests/

lint-github: setup   # CI only: findings surface as PR annotations
	@$(RUFF) check sdl_flow_optimiser/ tests/ --output-format=github

typecheck: setup     # gate on errorCount from --outputjson (basedpyright's --level is honored in CI)
	@$(BASEDPYRIGHT) --outputjson | $(PYTHON) -c "import json,sys; d=json.load(sys.stdin); sys.exit(1 if d['summary']['errorCount'] else 0)"

test: setup lint typecheck
	@$(PYTHON) -m pytest

coverage: setup
	@$(PYTHON) -m pytest --cov=sdl_flow_optimiser --cov-report=term-missing --cov-report=xml

format: setup
	@$(RUFF) check --fix sdl_flow_optimiser/ tests/
	@$(RUFF) format sdl_flow_optimiser/ tests/

clean:
	@rm -rf .venv htmlcov/
	@rm -f .coverage coverage.xml
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete

db-up:
	@docker inspect $(PG_CONTAINER) >/dev/null 2>&1 || docker run -d --name $(PG_CONTAINER) \
		-e POSTGRES_USER=sdl -e POSTGRES_PASSWORD=sdl -e POSTGRES_DB=sdl_flow_optimiser \
		-p 5432:5432 postgres:16
	@echo "Postgres running at postgresql+psycopg://sdl:sdl@localhost:5432/sdl_flow_optimiser"

db-down:
	@docker rm -f $(PG_CONTAINER) >/dev/null 2>&1 || true

db-init: setup
	@uv run --env-file .env alembic upgrade head

db-revision: setup
	@uv run --env-file .env alembic revision --autogenerate -m "$(m)"

web: setup
	@uv run --env-file .env uvicorn sdl_flow_optimiser.labeler.app:app --host 0.0.0.0 --port 8010

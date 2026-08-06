"""Pipeline stages — one module per stage, added per docs/PLAN.md phases.

Planned stages (TECHSPEC): ingest, classify, segment, analyze, recommend,
investigate, emit. Each stage reads/writes the DB only; only ingest touches
the session store. The stages layer may depend on models + core only —
enforced by tests/test_architecture.py.
"""

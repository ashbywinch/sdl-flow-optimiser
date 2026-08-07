"""Pipeline stages — one module per stage, added per docs/PLAN.md phases.

Planned stages (TECHSPEC): ingest, attribute, segment, analyze, recommend,
findings, emit. Each stage reads/writes the DB only; only ingest touches
the session store. Stage names follow the object model (a "findings" stage,
never an "investigate" stage). The stages layer may depend on models + core
only — enforced by tests/test_architecture.py.
"""

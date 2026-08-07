# PLAN — sdl-flow-optimiser

Phases ship in order; each phase's quality gate is the app behaving correctly
at that point. Phase inputs/outputs are the **software's** — what it consumes
and produces — never project-management artifacts.

## Phase 0 — Scaffold (done)

- Inputs: none (repo creation).
- Outputs: CLI `python -m sdl_flow_optimiser` (version), model catalog,
  toolchain, CI, docs.
- Operations: `make setup` / `make test` / `make coverage` / `make run`.
- Quality gate: `make setup && make lint && make typecheck && make test`
  green in a fresh clone; CI green on push; layer boundaries enforced by
  `tests/test_architecture.py`.

## Phase 1 — Ingestion

- Inputs: `~/.omp/agent/sessions/**/*.jsonl` (read-only), Postgres (via
  `make db-up`), `SDL_DB_URL`/`SDL_SESSIONS_DIR`.
- Outputs: `projects`, `sessions`, `events`, `assistant_calls`,
  `tool_executions`, `user_messages` rows; `ingest_runs` audit row with
  coverage %; `ingest_manifests` parse state.
- Operations: `make ingest` — parse JSONL, epoch-ms normalization, resolve
  the 3-event tool-execution join, upsert incrementally by sha256, report
  coverage.
- Quality gate: re-running `make ingest` is idempotent; the audit row
  reports files seen/parsed/skipped and never silently drops a parse
  failure; the 3-event join resolves for ≥ 99% of tool calls.

## Phase 2 — Classifier + S1 attribution investigation

- Inputs: normalized tables, hand-labeled sample of 3–5 sessions.
- Outputs: `phase_definitions` (8 phases + rule signatures),
  `phase_assignments` with confidence, `classifier_evals` (precision/recall
  per phase), `findings` answering S1 (which metrics are trustworthy), the
  user's adjudication (`s1_labels.json`).
- Operations: `make classify` (rule-based; embedding classifier pluggable
  later via pgvector), `make investigate` (label sample, measure agreement,
  write findings), and `make web` — the labeler app where the user marks
  random and low-confidence samples agree/disagree (with corrected phase +
  comment) against the surrounding transcript context; `--apply-labels`
  folds the adjudication into the ground truth.
- Quality gate: every metric's source attribution is validated by a
  resolved `finding` backed by user adjudication — no metric computes from
  an unvalidated attribution. Classifier agreement is measured, not
  assumed. Chore sessions (git/ops maintenance, no file modifications) are
  excluded from phase analysis.

## Phase 3 — Segmentation + S2/S3 investigations

- Inputs: normalized tables + phase assignments.
- Outputs: `work_items` (session-kind in v1), `work_item_phases` walks,
  `idle_gaps` with task-switch markup, `doc_references` and
  `work_item_links`, `prs` (if S2 proves feasible), `findings` for S2
  (PR attribution) and S3 (plan→execute doc-reference linkage).
- Operations: `make segment` + `make investigate`.
- Quality gate: work-item granularity decision recorded in a `finding`
  (session vs PR); idle gaps stored raw and never interpreted except
  task-switch; linkage red-herring rule (work-product docs only) filters
  skills/standards/config references.

## Phase 4 — Queuing metrics

- Inputs: derived tables.
- Outputs: `analysis_runs` (one per `make analyze`), `metrics` (Little's Law
  trio per project × time bucket), `phase_sequences` (SDLC-version
  frequencies), `bottlenecks` (constraint with time-share + queue evidence),
  the derived **event log** (case = work item, activity = phase, timestamp =
  phase-run start) as a standard CSV/XES export — the contract that lets
  external process-mining tools consume the data.
- Operations: `make analyze`; **spike S4** — prototype pm4py (or other
  log-analysis tools found later) over the event log: discovered
  directly-follows graph, dotted chart, performance spectrum. Adopt only
  what earns its weight; the numbers stay hand-rolled.
- Quality gate: only confidence-validated metrics are computed; every
  metric is per-project and per-bucket (no unbroken aggregates); the
  bottleneck is confirmed with evidence as **time-share** (which phase
  consumes the most active time — the solo developer's constraint) plus the
  review-queue wait; S4 produces a finding on whether the tooling is adopted.

## Phase 5 — Recommendation + emit + chat loop

- Inputs: metrics + bottleneck rows.
- Outputs: `recommendations` (top-1 + ranked `candidate_levers`, advisory),
  `analysis/latest/metrics.json`, `analysis/latest/report.md`.
- Operations: `make recommend` + `make emit`; the omp agent loads
  `analysis/latest/report.md` to argue the recommendation.
- Quality gate: the report shows the recommendation first, then evidence;
  nothing below the confidence threshold is emitted; an omp session can
  challenge the recommendation ("but what about this?") citing the evidence
  trail and the reasoning survives or revises under challenge.

## Phase 6 — Code review

- Inputs: the built codebase (stages, labeler, tests, docs).
- Outputs: reviewed, standards-compliant code; resolved review findings.
- Operations: branch + PR per the house git workflow; the review bot
  (pr-agent) reviews with the docs standards in context (PRD, TECHSPEC,
  coding/testing standards); fix findings until the review is clean.
- Quality gate: the review reports no standards violations; `make test`
  green; coverage ≥ 80%; nothing merged to main without a clean review.

## Phase 7 — UX review

- Inputs: the live verification tool (labeler).
- Outputs: UX findings and fixes; converged walkthroughs;
  `docs/ux-fixes-plan.md` updated.
- Operations: fake-user walks (phone viewport) + UX analysis per
  `skill://ux-process`; fixes land only with user agreement.
- Quality gate: the fake user completes the verification job — reads a
  session as the conversation it was, corrects a classification, groups
  sessions — without hitting the targeted problems; the PRD's verification
  requirements hold on re-walk.

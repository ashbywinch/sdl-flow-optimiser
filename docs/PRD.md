# PRD — sdl-flow-optimiser

Analyze omp session logs as a queuing system; surface the single highest-impact
process improvement, with evidence, and let the user interrogate it in chat.

## JTBD

- When I work with omp agents, I want to see how my process *actually* ran —
  the phase sequence, cycle time, WIP, and where the constraint is — so I act
  on the single highest-impact improvement instead of guessing.
- When I get a recommendation, I want to challenge it ("but what about this?")
  against a queuing-theory / modern-SDLC expert so the final decision is mine,
  informed — never a diktat.
- When my process changes, I want the same analysis to show how I'm improving
  over time (V2: dashboard, goal tracking).
- I want to see which SDLC "versions" actually occur — the different phase
  sequences in evidence, per project — because the sequence I *plan* and the
  sequence I *run* differ.

## Personas

- **Ashby** — solo engineer, omp power user, ~3 concurrent projects, ~118
  sessions / 3 weeks of log history at PRD time. Evidence-first: distrusts a
  recommendation without supporting numbers. Wants suggestions, not mandates —
  may achieve a goal his own way. Wants to interrogate the reasoning.

## Constraints

- **Local only.** Analysis reads `~/.omp/agent/sessions/` (118 sessions,
  ~385 MB, 14 projects, growing). Never uploads logs anywhere; nothing leaves
  the machine. Omp logs contain personal work product.
- **Data is omp's internal format.** JSONL event stream (`session`, `message`,
  `custom:tool_execution_start`, `toolResult`, `title_change`, `compaction`,
  `model_change`, `session_exit`). Format may change between omp versions —
  parser MUST degrade gracefully and report coverage, never silently drop.
  Compactions are parsed but excluded from analysis (user decision).
- **Storage: local Postgres.** One instance on the laptop, pgvector enabled.
  All pipeline outputs persist to the DB — the DB is the record of every
  decision the pipeline made, not just the normalized logs.
- **Attribution is uncertain.** Mapping events → project/phase/PR is heuristic;
  some events are phase-ambiguous (`read`/`grep`/`bash` occur in every phase).
  Never present a metric as fact without its confidence.
- **Per-project, time-evolving.** Work differs by project and changes over time
  (past and future). No aggregate metric without its per-project and per-time
  breakdown.
- **Solo, long-lived, boring.** Personal tool, run on a laptop, maintained by
  one person. Prefer boring, standard tooling (Makefile + Python + SQLAlchemy);
  no bespoke infra, no auth beyond local DB trust.
- **Cycle time matters more than speed.** Goal is shorter time-to-done and less
  wasted effort, not more output per hour.

## Scope

### V1 — analyzer + recommendation + chat-ready artifact

1. **Ingest** all sessions in the store; segment each session's event stream
   into work items (session = smallest unit; title changes mark intent shifts).
   All outputs persist to the DB, not just in-memory or artifacts.
2. **Classify** activity into the 8 phases below, with per-event confidence
   (rule-based; embedding classifier as pluggable secondary — pgvector).
3. **Investigate feasibility** (as part of the work, findings gated by S1):
   - **PR attribution**: can work items be attributed to PRs consistently
     (`pr://` reads, PR-creation events, git metadata)? If yes, work items
     upgrade from session-level to PR-level (more logically coherent).
   - **Plan→execute linkage**: planning sessions generate a doc, execution
     sessions reference it. Link via doc-reference, filtered to work-product
     docs (`docs/`, `local://` plans) to avoid red-herring links from
     skills/standards/config updates; embedding-similarity fallback.
4. **Compute per-project, time-bucketed metrics**:
   - Phase-sequence frequencies (the SDLC "versions" in evidence), by project
     and over time.
   - Little's Law trio: WIP (open PRs, concurrent sessions/work items),
     throughput (items completed / week), cycle time (item start → done).
   - Bottleneck detection: phase with the longest standing queue / highest
     utilization — the review queue is the suspected constraint (5 PRs open
     "the whole time").
   - Stall metrics: idle gaps (stored raw, never interpreted) marked as task
     switches when a gap in one session overlaps activity in another;
     waiting-on-review time; context switches between projects.
5. **Recommend** the single highest-impact actionable change + supporting
   evidence; keep ranked alternatives visible. Advisory only.
6. **Emit artifact** the omp agent can load and argue about: structured JSON +
   human-readable markdown at a stable path in this repo. The conversation
   happens in omp (point the agent at the artifact); no chat UI in V1.
   Nothing ships below the confidence threshold.

### Non-goals (V2+)

- Dashboard / improvement-over-time UI.
- Goal setting and progress tracking (incl. generalized life-goals tracking).
- Skipped-phase detection as a named output — V1 shows sequence frequencies
  instead (user explicitly deferred detection).
- Real-time monitoring, alerts, CI integration, sharing.

## Phase model

User-defined, non-strict order, may repeat. Mapping events → phases is a
hypothesis to validate in the attribution spike; signatures below are the
starting classifier.

| # | Phase | Log signatures (starting classifier) |
|---|-------|--------------------------------------|
| 1 | PRD / requirements | `ask` interviews, writes to `docs/PRD*`, `user-interviews` skill, Notion epic creation/refinement |
| 2 | Technical design | `docs/TECHSPEC*` / design-doc writes, architecture tooling (code-review-graph overview/architecture) |
| 3 | Flow design | `ux-process`/`visual-design`/`user-interviews` skills, browser walkthroughs, `docs/ux-*` writes |
| 4 | Breakdown into tickets | Notion task/epic creation, `backlog-grooming` skill, todo-init with many items |
| 5 | Dev plan | `todo` usage, `local://` plan artifacts, `docs/PLAN*` writes, task-subagent instruction drafting |
| 6 | Execute | `edit`/`write`/`ast_edit`/`lsp` on code, `bash` build/test, `eval`, `debug` |
| 7 | PR + review loop | `pr-workflow` skill, `pr://` reads, git push/PR creation, review iterations |
| 8 | UX loop | `ux-process` fake-user walks, browser user testing, `inspect_image` on screenshots |

Ambiguities the spike MUST resolve: `read`/`grep`/`glob` (research in every
phase), `bash` (build vs deploy vs misc), `write` (docs vs code), session
boundaries vs work-item boundaries.

## Spikes required to confirm

- **S1 — Attribution feasibility (gates everything).** Hand-label a sample of
  sessions (per phase, per project, per PR where identifiable); measure
  classifier agreement. Decide which metrics are trustworthy and which are
  dropped. No metric ships without measured confidence.
- **S2 — PR attribution (in-scope investigation).** Can sessions/work items be
  attributed to PRs consistently? Determines whether the WIP/cycle-time
  metrics run at PR granularity (preferred) or session granularity (fallback).
- **S3 — Plan→execute linkage (in-scope investigation).** Does doc-reference
  linking reliably connect planning sessions to execution sessions, with
  skills/standards red herrings filtered? Determines whether logical work
  items can span sessions.

## Output artifact

All outputs live in the DB (the record of every pipeline decision). `emit`
serializes the latest `AnalysisRun` to `analysis/` (committed):

- `analysis/latest/metrics.json` — structured: per-project, per-time-bucket
  phase sequences, Little's Law metrics, bottleneck evidence, confidence per
  metric, recommendation + ranked alternatives.
- `analysis/latest/report.md` — human-readable: the recommendation first, then
  the evidence trail, sized for an agent to load and reason over in chat.

## Success criteria

- Analyzer runs over the full store on a laptop in bounded time and emits both
  artifact files.
- Report shows: per-project phase-sequence frequencies with time evolution;
  WIP/throughput/cycle time per project; the identified bottleneck with its
  evidence; one recommendation + ranked alternatives; confidence per metric.
- Every confidence < threshold is visibly flagged, not presented as fact.
- Chat loop works: an omp session loads `analysis/latest/report.md` and can
  argue the recommendation ("but what about this?") citing the evidence.
- No metric depends on attribution the S1 spike did not validate.

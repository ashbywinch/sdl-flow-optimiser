# PRD — sdl-flow-optimiser

Analyze omp session logs as a queuing system; surface the single highest-impact
process improvement, with evidence, and let the user verify the analysis by
reading their sessions back and adjudicating it in a phone-usable web tool.

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
- **When I need to verify the analysis, I want to read my sessions back as the
  conversation I actually had** — my words and the agent's replies — not as
  tool calls, JSON, or dashboards. If I cannot recognize my own session, I
  cannot trust the classification built on it.

## Personas

- **Ashby** — solo engineer, omp power user, ~3 concurrent projects, ~118
  sessions / 3 weeks of log history at PRD time. Evidence-first: distrusts a
  recommendation without supporting numbers. Wants suggestions, not mandates —
  may achieve a goal his own way. Wants to interrogate the reasoning.
- **Ashby on his phone** — does the verification work on a phone (small
  screen, thumb). Requirements learned through UX loops (see UX requirements):
  never sees raw JSON, never sees popups/modals, controls are always
  reachable, and the session — not the sample — is the unit of work. Reads
  sessions like Paseo renders them: a conversation with pinned navigation.

## Constraints

- **Local only.** Analysis reads `~/.omp/agent/sessions/` (118 sessions,
  ~385 MB, 14 projects, growing). Never uploads logs anywhere; nothing leaves
  the machine. Omp logs contain personal work product.
- **Data is omp's internal format.** JSONL event stream (`session`, `message`,
  `custom:tool_execution_start`, `toolResult`, `title_change`, `compaction`,
  `model_change`, `session_exit`). Format may change between omp versions —
  parser MUST degrade gracefully and report coverage, never silently drop.
  Compactions are parsed but excluded from analysis (user decision).
- **Harness-injected content is not the user's voice.** Some sessions open
  with an auto-generated user message (code-review requests with file dumps,
  >50k chars). It must be filtered from transcripts and openings (rule: the
  opening user message over 1500 chars is dropped; the user's real openings
  are under 300).
- **Storage: local Postgres.** One instance on the laptop, pgvector enabled.
  All pipeline outputs persist to the DB — the DB is the record of every
  decision the pipeline made, not just the normalized logs.
- **Attribution is uncertain.** Mapping events → project/phase/PR is heuristic;
  some events are phase-ambiguous. Never present a metric as fact without its
  confidence. No metric ships without user-validated attribution.
- **Per-project, time-evolving.** Work differs by project and changes over time
  (past and future). No aggregate metric without its per-project and per-time
  breakdown.
- **Solo, long-lived, boring.** Personal tool, run on a laptop, maintained by
  one person. Prefer boring, standard tooling (Makefile + Python + SQLAlchemy);
  no bespoke infra. The labeler is a local FastAPI app served on the LAN
  without auth — the same trust model as the rest of the personal tooling.
- **Cycle time matters more than speed.** Goal is shorter time-to-done and less
  wasted effort, not more output per hour.

## Scope

### V1 — analyzer + labeler + recommendation

1. **Ingest** all sessions in the store; segment each session's event stream
   into work items (session = smallest unit; title changes mark intent
   shifts). All outputs persist to the DB.
2. **Attribute** activity to the 8 phases, per event, with confidence. The
   domain object is the **phase run** (the interval a work item spends in one
   phase) — per-event labels are the evidence for runs, not the end product.
   Attribution rules:
   - **Delegation is not a phase.** `task` spawns and hub subagent
     coordination are orchestration: the work happens in the subagent's
     session. Delegation events inherit the parent run's phase and are
     measured separately; their existence flags that phase time is
     undercounted where work is delegated.
   - **Chores are not phases.** Sessions doing git/ops maintenance (no file
     modifications across the session) are excluded from phase analysis.
   - **Session-level phase character** is a second, coarser dimension: the
     opening user message → session kind (lifecycle / discovery /
     implementation / plan→design→implement→PR).
   - Embedding classifier (pgvector) is the planned secondary for research
     reads (see Attribution feasibility).
3. **Findings gate metrics** (S1 resolved — see Attribution feasibility):
   every metric's source attribution is validated by a resolved finding backed
   by user adjudication.
4. **Compute per-project, time-bucketed metrics**:
   - Phase-sequence frequencies (the SDLC "versions" in evidence), by project
     and over time.
   - Little's Law trio: WIP (open PRs, concurrent sessions/work items),
     throughput (items completed / week), cycle time (item start → done).
   - Bottleneck detection: phase with the longest standing queue / highest
     utilization — the review queue is the suspected constraint.
   - Stall metrics: idle gaps (stored raw, never interpreted) marked as task
     switches when a gap in one session overlaps activity in another;
     waiting-on-review time; context switches between projects.
   - Only phases S1 validated may feed metrics (see the gating table).
5. **Recommend** the single highest-impact actionable change + supporting
   evidence; keep ranked alternatives visible. Advisory only.
6. **Labeler web app** (`make web`, LAN reachable) — the user's verification
   surface. Requirements in detail below (Labeler requirements).
7. **Session association** — the same tool associates sessions that are one
   piece of work across multiple sessions (plan session → execute session):
   manual pairing from the session list, remove/undo, grouped badges. The
   association feeds work-item assembly (S3).
8. **Emit artifact** the omp agent can load and argue about: structured JSON +
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

User-defined, non-strict order, may repeat. Phases are properties of
**stretches of activity** (runs over a work item), not of individual tool
calls — per-event attribution is the evidence that builds runs.

| # | Phase | Log signatures (starting classifier) |
|---|-------|--------------------------------------|
| 1 | PRD / requirements | `ask` interviews, writes to `docs/PRD*`, `user-interviews` skill, Notion epic creation/refinement; **research reads at session start** (surveying vocabulary, config files: Makefile/pyproject/AGENTS/skill://) |
| 2 | Technical design | `docs/TECHSPEC*` / design-doc writes, architecture tooling, embedding/model research (read/web_search only) |
| 3 | Flow design | `ux-process`/`visual-design`/`user-interviews` skills, browser walkthroughs, interview/transcript docs |
| 4 | Breakdown into tickets | Notion task/epic creation, `backlog-grooming` skill, todo-init with many items |
| 5 | Dev plan | `todo` usage, `local://` plan artifacts, `docs/PLAN*` writes |
| 6 | Execute | `edit`/`write`/`ast_edit`/`lsp` on code, `bash` build/test, `eval`, `debug`, dev-server process management |
| 7 | PR + review loop | `gh pr`, `pr://`, pull request, push/merge, review findings/comments, `round-N`/`bot run` polling. NOT: configuring pr-agent (that is execute) |
| 8 | UX loop | `ux-process` fake-user walks, browser user testing, `inspect_image` on screenshots |

**Not phases:** delegation (orchestration; inherits parent run) and chores
(git/ops maintenance; excluded).

## Attribution feasibility (S1 — resolved)

Measured on 240 hand-labeled executions across 4 frozen sessions / 3 projects,
rule-based prototype (`sdl_flow_optimiser.phase_attribution`), 92.4% accuracy
on 236 phase-bearing events (4 delegation excluded).

| Phase | Precision | Recall | n | Status |
|---|---|---|---|---|
| execute | 92.9% | 98.0% | 146 | ✅ ships |
| dev_plan | 100% | 92.9% | 14 | ✅ ships |
| ux_loop | 100% | 100% | 6 | ✅ ships |
| prd | 93.8% | 81.1% | 37 | ✅ ships (was 37.5% recall; fixed by research-read signals) |
| pr_review | 93.8% | 78.9% | 19 | ⚠️ gated: bottleneck metric needs recall ≥85% |
| tech_design | 77.8% | 87.5% | 8 | ⚠️ small n |
| flow_design | 66.7% | 66.7% | 6 | ⛔ gated: needs more samples |

Lessons baked into the rules: rule ordering (specific before generic —
`prd` before `design`), mechanism-vs-signal (env/design keywords only on
read/web_search, never on edits/greps), case normalization, and delegation
handling. The embedding classifier (pgvector) is the planned next step for
prd recall; run-level evaluation should follow segmentation (PLAN phase 3).

## Labeler requirements (learned via UX loops, iteration 1 + 2)

Verified against the persona by fake-user walks (phone viewport) and the
user's own corrections; recorded in `docs/ux-fixes-plan.md`.

### Reading sessions (the core job)

- **The session is the unit of work.** The app opens on the session list, not
  a sample queue.
- **Transcript = the conversation.** Sessions open in Conversation mode:
  the user's messages and the agent's replies in order. Tool calls are
  hidden by default; an "All" toggle reveals them.
- **Tool calls render as the harness does**: `tool — human-readable intent`
  (e.g. `read — Reading the design doc`). NEVER raw JSON args — the user
  never sees JSON in the harness and must never see it here.
- **Long messages collapse to a chip** ("14k chars — tap to expand") and
  expand **inline** with a collapse link. NEVER popups/modals — removed after
  the user rejected both an overlay and an earlier inline wall.
- **Browsable, not a wall.** Transcript renders in chunks (100 at a time)
  with a **sticky bottom bar**: Top · Show more (N left) · Jump to end —
  always on screen, never buried under content.
- **Phase chips** (e.g. "Execute 120") jump to the first call of that phase.
- **Harness-injected opening prompts are filtered** (see Constraints).
- **Agent-run sessions are flagged** ("agent run — no conversation") and every
  row shows its message count, so conversational sessions are findable.

### Adjudication

- **Full phase names, never abbreviations** ("PRD", "Execute", "PR + review").
- Every Agree/Disagree shows a **saved-verdict toast with Undo**.
- Disagree optionally records a **corrected phase** + comment; adjudication
  persists to `s1_labels.json` and folds into the ground truth via
  `--apply-labels`.
- **Sample queues** (random / low-confidence / disagreements) with the
  surrounding context one tap away — secondary to session browsing, which is
  the primary verification path.
- Filters auto-apply on change; no dead-feeling controls.

### Session association

- Pair two sessions as the same piece of work; **remove/undo** mis-made pairs;
  "grouped" badges on linked rows; persistent selection bar.

## Spikes / investigations

- **S1 — Attribution feasibility** — RESOLVED (see above); label
  adjudication continues via the labeler.
- **S2 — PR attribution (in-scope).** Can sessions/work items be attributed to
  PRs consistently? Determines whether WIP/cycle-time metrics run at PR
  granularity (preferred) or session granularity (fallback).
- **S3 — Plan→execute linkage (in-scope).** Does doc-reference linking
  reliably connect planning sessions to execution sessions (work-product docs
  only; skills/standards red herrings filtered), with the labeler's manual
  associations as ground truth? Embedding-similarity fallback.

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
- **The user can verify the analysis**: opening any conversational session in
  the labeler shows their own words and the agent's replies on a phone, with
  no raw JSON, no popups, and the navigation bar always reachable.
- **Adjudication is complete for the gated metrics**: the review-bottleneck
  metric does not ship until pr_review recall clears 85% via user-adjudicated
  labels; flow_design metrics do not ship until more samples validate them.
- Chat loop works: an omp session loads `analysis/latest/report.md` and can
  argue the recommendation ("but what about this?") citing the evidence.
- No metric depends on attribution that S1 did not validate.

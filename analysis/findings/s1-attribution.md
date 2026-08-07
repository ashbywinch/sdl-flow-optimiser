# Finding S1 — Attribution feasibility (resolved with caveats)

**Question:** Can tool executions be attributed to the 8 phases with enough
confidence to ship metrics? (PRD spike S1 — gates every downstream metric.)

**Method:** Stratified sample of 240 tool executions across 4 frozen sessions
/ 3 projects (omp-config skill-writing, feed embedding+PRD, family-history
implementation, feed PR/deploy). Hand-labeled by the analyst (Ashby to
validate — `s1_ground_truth.json`); attributed by the rule-based prototype
(`sdl_flow_optimiser.phase_attribution`). Delegation events (task spawns, hub
subagent coordination — 4 in the sample) are NOT phase-bearing: the work
happens in the subagent's session, so they inherit the phase of the nearest
phase-bearing activity and are excluded from the confusion. Reproduce:
`python -m sdl_flow_optimiser.findings.attribution_feasibility`.

**Chore exclusion:** the houses branch-divergence session (git maintenance)
was excluded on Ashby's call — chores are not SDLC phases. Candidate chore
signal: no edit/write tool across the session (that session was bash×17,
todo×3, zero file modifications). Chore detection belongs in the segment
stage: sessions with no phase-bearing file activity are filtered from phase
metrics, not forced into execute.

**Session-level validation (Ashby, 2026-08-06):** sessions have their own
phase character, read from the opening user message:
- S1 (ompcfg skill) — full lifecycle within one session (research → policy
  asks → edits → PR)
- feed-08-01 — discovery phase ("make a PRD" is the clue); later phases
  unknown from the opening
- fam — implementation ("find the plan and start work")
- feed-08-04 — plan → design Q&A → implement → PR lifecycle
Session-level attribution is a second, coarser dimension (opening message →
session kind) that run-level phase metrics should be reported against.

**Results (n=236 phase-bearing, overall accuracy 92.4%; 4 delegation events
excluded):**

| Phase | Precision | Recall | n |
|---|---|---|---|
| prd | 93.8% | 81.1% | 37 |
| tech_design | 77.8% | 87.5% | 8 |
| flow_design | 66.7% | 66.7% | 6 |
| dev_plan | 100% | 92.9% | 14 |
| execute | 92.9% | 98.0% | 146 |
| pr_review | 93.8% | 78.9% | 19 |
| ux_loop | 100% | 100% | 6 |

## Answer

**Attribution is usable for every phase except flow_design (small n).** The
rule classifier improved from 82.7% to 91.7% accuracy during the spike, via
four real fixes (each is a lesson, not a hack):

- **prd recall 37.5% → 75%** — requirements work is research reads; they are
  now caught by surveying vocabulary, config-file paths (`Makefile`,
  `pyproject`, `AGENTS.md`, `skill://`) at session start, and session
  position. The original failure was measuring *isolated* events when the
  domain object is the phase *run* (context disambiguates) — see the
  `write-tech-spec` skill rule: design experiments around the primary
  object.
- **Rule ordering** — specific phase signals (`prd`, `flow design`) must
  precede generic ones (`design`, `embedding`).
- **Mechanism-vs-signal** — env/design signals belong to read/web_search
  only; edits and greps whose search paths merely mention `.env.example`
  are not tech design.
- **Case normalization** — pattern matching lowercases args before matching.
- **Delegation is not a phase.** `task` spawns and hub subagent coordination
  are orchestration: the phase work happens in the subagent's session, which
  the parent stream only touches via the coordination call. Forcing them
  into the 8 phases pollutes the confusion (hub/task calls have no signature
  of their own). They inherit the parent run's phase and are measured
  separately — and their existence flags that phase time may be undercounted
  where work is delegated (a subagent's research is phase-1 time invisible in
  the parent's event stream).

**Data-stability finding:** a live session transcript shifts the stratified
sample between runs (sample rows changed mid-spike). Sessions in the sample
MUST be frozen; noted in `attribution_feasibility.py`.

## Gating (per PRD: no metric ships without measured confidence)

- **CAN ship:** execution-time, dev-plan-time, UX-loop-time, and prd-time
  metrics per project × bucket (prd ≥ 75% recall); phase-sequence
  frequencies over these phases.
- **CANNOT ship yet:** time-in-flow_design as a number (n=6, 67% — needs
  more samples), and the review-bottleneck metric until pr_review recall
  clears ~85% (currently 81%).
- **Label validation in flight:** the confirmation list
  (`analysis/findings/s1-confirm.md`, phone-formatted) lists all 18
  classifier-vs-label disagreements plus 29 agreed-low-confidence samples
  for Ashby to adjudicate; corrections update `s1_ground_truth.json` and
  this finding's numbers.

## Recommended next steps (in order)

1. **Ashby adjudicates the confirmation list** — reply with wrong-label
   numbers; rebuild ground truth; re-measure.
2. **Embedding classifier** (pgvector, TECHSPEC) — intent semantics for
   research reads; S1 confirms it is needed to push prd recall past ~85%,
   not speculative.
3. **Run-level evaluation** — the domain object is the phase run
   (`WorkItemPhase`); per-event agreement understates run-level agreement.
   Land with segmentation (PLAN phase 3).
4. Re-run S1 after each change; the finding's numbers are the gate.

**Status:** resolved — S1 answered; flow_design and review-bottleneck
metrics remain gated until steps 1–3 land.

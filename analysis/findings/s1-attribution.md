# Finding S1 — Attribution feasibility (resolved with caveats)

**Question:** Can tool executions be attributed to the 8 phases with enough
confidence to ship metrics? (PRD spike S1 — gates every downstream metric.)

**Method:** Stratified sample of 300 tool executions across 5 frozen sessions
/ 4 projects (omp-config skill-writing, houses auth implementation, feed
embedding spike, family-history planning, feed PR/deploy). Hand-labeled by
the analyst (Ashby to validate — `s1_ground_truth.json`); classified by the
rule-based prototype (`sdl_flow_optimiser.classifier`). Reproduce:
`python -m sdl_flow_optimiser.investigate.s1_attribution`.

**Results (n=300, overall accuracy 82.7%):**

| Phase | Precision | Recall | n |
|---|---|---|---|
| prd | 88.2% | **37.5%** | 40 |
| tech_design | **47.1%** | 100% | 8 |
| flow_design | 66.7% | 66.7% | 6 |
| dev_plan | 100% | 93.8% | 16 |
| execute | 85.4% | 91.9% | 197 |
| pr_review | 73.1% | 70.4% | 27 |
| ux_loop | 85.7% | 100% | 6 |

## Answer

**The rule classifier is trustworthy for execute, dev_plan, and ux_loop;
NOT for prd, tech_design, or pr_review.**

- **prd recall 37.5% — the dominant failure.** Requirements work is mostly
  *research reads* (other repos' Makefiles/CI/pyproject, skills, rules). A
  `read` with no phase-specific vocabulary is indistinguishable from an
  execution read by tool signature. 19 of 40 labeled-prd executions fell to
  the execute fallback.
- **tech_design precision 47%.** The generic `design` keyword overshoots;
  and "tech design" is often done via doc edits the rules catch only by path.
- **pr_review 73/70.** Git-op ambiguity: local commits read as execute, and
  review-loop fixes (edits responding to bot findings) read as execute.
- **Data-stability finding:** a live session transcript shifts the stratified
  sample between runs (sample rows changed mid-spike). Sessions in the sample
  MUST be frozen; noted in `s1_attribution.py`.

## Gating (per PRD: no metric ships without measured confidence)

- **CAN ship:** execution-time, dev-plan-time, UX-loop-time metrics per
  project × bucket; phase-sequence frequencies built from trustworthy phases
  (execute/dev_plan/ux_loop) with untrustworthy phases flagged.
- **CANNOT ship yet:** time-in-PRD, time-in-tech-design, time-in-review as
  computed numbers; any metric whose numerator is a prd/tech_design
  attribution.
- The suspected review-bottleneck metric needs pr_review recall above 70%
  before it is trustworthy.

## Recommended next steps (in order)

1. **Validate the labels** — Ashby reviews `s1_ground_truth.json` (300 rows;
   a skim of the 50 prd/tech_design disagreements is the highest-value pass).
2. **Embedding classifier** (pgvector, TECHSPEC) — intent strings of
   research reads are semantically distinguishable ("survey repos for the
   skill" vs "read this test before editing"); this is the planned fix for
   prd recall, and S1 confirms it is needed, not speculative.
3. **Cheap rule wins first:** session-position signal (research reads in the
   first N% of a session → prd), commit-vs-push disambiguation, review-fix
   detection via `Fixes #`/round-N context.
4. Re-run S1 after each classifier change; the finding's numbers are the
   gate.

**Status:** resolved — S1 answered; phase-1/2/7 metrics remain gated until
steps 1–3 land.

# UX fixes plan — S1 labeler

Decisions from the UX test-and-loop (skill://ux-process). Each row: the
decision, the problem it resolves, the persona it was tested with, the
implementation. Changes land only with Ashby's agreement; acceptance is
re-walking the scenario.

## Iteration 1 — session-centric navigation (2026-08-06)

Persona tested: Ashby — solo engineer who develops by directing AI agents,
works on a phone; the fake-user walk (390×844 viewport) completed the job
but reported 8 confusions; Ashby's own feedback was stronger: "I don't know
how to get to the session contents… I can't see your judgment anywhere."
The session — not the sample — is the unit of work.

| Decision | Resolves | Implementation |
|---|---|---|
| **Full session viewer** — every tool call in order, each with prediction, confidence, analyst label, and inline agree/disagree + phase pills + comment | "how do I get to the session contents", fake-user P5 (re-judging the same session repeatedly) | `GET /api/sessions/{id}` returns the whole classified transcript; Sessions-tab cards open it; prev/next session navigation in the header |
| **Sample → session link** — the session tag on every label card opens its session | "how do I navigate between the sessions" | session tag is a link (`session_id` added to samples) |
| **Analyst judgment visible** — "analyst: X" tag on every card and event row; conflict line when model ≠ analyst ("Model says exec (0.35) — I said prd. Which is right?") | "I can't see your judgment anywhere", fake-user P3 | legend line on the Label tab + conflict rendering |
| **Saved-verdict toast with Undo** — every Agree/Disagree shows exactly what was recorded, with Undo | fake-user P1 (silent disagree), "I don't know what I'm agreeing or disagreeing with" | toast + `DELETE /api/labels/{call_id}` |
| **Instruction line + legend** on the Label tab ("Is the predicted phase right? If not, tap the correct phase, then Disagree") | fake-user P2 (undiscoverable pills) | header hint |
| **Batch-complete summary** — verdict counts + review list + Load more | fake-user P4 (void at batch end) | summary view on queue exhaustion |
| **Associations shown with titles/opening** instead of bare hashes | fake-user P7 | client-side title resolution |

Not yet done (explicitly deferred): live stats-bar semantics (P6), Sessions
first-render skeleton (P8). Re-walk will target P1–P5 residuals.

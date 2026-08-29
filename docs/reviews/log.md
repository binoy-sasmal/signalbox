# Review log

One row per `/review` invocation of the `gate-reviewer` agent. The agent reads this
file at the start of every review and reports the running tally in its output.

**Why this file rather than agent memory.** Claude Code's subagent `memory` field
would have done the tracking, but enabling it automatically grants the subagent
Read, Write and Edit — which would undo the read-only scoping the agent exists
under. A git-tracked file keeps the reviewer read-only, and has the better property
anyway: it is a diff. Agent memory is opaque, this is not.

**What it cannot see.** It records reviews that happened. It cannot record a review
that was never requested, and that — not a corrupted row — is the realistic failure:
`/review` quietly not being run for six turns during a good stretch. CLAUDE.md
covers that separately, by requiring the builder to state the last review's date,
range and verdict at every gate boundary, and to report the absence of one as the
finding when none has run since the previous gate.

**Written by the builder, read by the reviewer.** The builder appends the row after
each verdict. A builder could omit a REJECT, but the omission is visible in git
history, which is more than opaque memory would offer.

## Open limitation: the reviewer cannot be the sole reviewer of its own construction

Rows marked *(self)* below reviewed the review machinery itself. That is the one
subject where this agent has the conflict its own rubric item 7 exists to catch:
the incentive runs one way, and a reviewer that finds its own construction sound
has told you very little.

It is not solved in this repo, and no attempt should be made to solve it here. A
second reviewer would have the same blind spot for the same reason, and a rule
forbidding self-review would only mean the machinery goes unreviewed. **The human
gate-boundary review is what covers it** — see the review-position rule in
CLAUDE.md.

Recorded rather than mitigated, because a limitation written down is one an
interviewer can be walked through, and a limitation quietly worked around is one
that gets discovered.

The evidence so far is encouraging but not conclusive: on its first run the agent
raised eight findings against the four commits that built it, seven of which
verified. That is evidence it does not simply approve itself. It is not evidence
that it found everything.

## Format

| Date | Range reviewed | Verdict | Findings | Notes |
|---|---|---|---|---|

- **Date** — ISO date of the review.
- **Range reviewed** — the git range or working-tree scope given to `/review`,
  verbatim. `working tree + HEAD` when invoked with no argument.
- **Verdict** — `ACCEPT`, `ACCEPT WITH AMENDMENTS`, `REJECT`, or `ESCALATE`.
- **Findings** — count, and the rubric item numbers they fell under. `0` if clean.
- **Notes** — one line. For `ESCALATE`, which halt condition fired.

## Log

| Date | Range reviewed | Verdict | Findings | Notes |
|---|---|---|---|---|
| 2026-08-29 | *(self)* `b1626f2..HEAD` — the review agent's own construction | no verdict returned | 8 raised, 7 confirmed | Findings under items 1, 3, 9, 10. One claim (`context: fork` inherits conversation history) checked against the live docs and found wrong. The agent did not emit a VERDICT line, a tally, or the rubric table -- a defect in the agent, recorded here rather than smoothed over. |
| 2026-08-29 | *(self)* `0419f6b..HEAD` — the seven fixes from review 1 | ESCALATE | 10 raised | Halt under sections 2a and 4.1. F1/F2 are observations of the run itself: the frontmatter hooks and tools allow-list did not apply, and the CLAUDE.md it received was the pre-`c9b7e64` version. Cause is a claim about the harness, correctly marked UNVERIFIED BY ME. F3-F10 stand on repo artefacts and are unfixed. Gap noted by the reviewer: commit `0419f6b` has never been reviewed. |

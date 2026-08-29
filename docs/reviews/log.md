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

**A `*(self)*` row reviewed the review machinery itself.** That is a real
limitation, recorded in [`../limits.md`](../limits.md) rather than here. This file
carries rows, not argument: a reviewer is instructed to read it before it reads a
diff, so anything persuasive in it arrives as framing rather than as evidence.

## Format

| Date | Range reviewed | Verdict | Findings | Notes |
|---|---|---|---|---|

- **Date** — ISO date of the review.
- **Range reviewed** — the git range or working-tree scope given to `/review`,
  verbatim. `working tree + HEAD` when invoked with no argument.
- **Verdict** — `ACCEPT`, `ACCEPT WITH AMENDMENTS`, `REJECT`, or `ESCALATE`.
  Prefixed **`VOID`** if the review turned out to have run from a configuration
  that no longer existed — see the staleness rule in `CLAUDE.md`. VOID is not a
  fifth verdict: it records that the review was not valid, while the parenthesised
  original records what it returned. A VOID row counts in neither the review tally
  nor the rejection tally.
- **Findings** — count, and the rubric item numbers they fell under. `0` if clean.
- **Notes** — one line. For `ESCALATE`, which halt condition fired.

## Log

| Date | Range reviewed | Verdict | Findings | Notes |
|---|---|---|---|---|
| 2026-08-29 | *(self)* `b1626f2..HEAD` — the review agent's own construction | **VOID** (was: no verdict returned) | 8 raised, 7 confirmed | Findings under items 1, 3, 9, 10. One claim (`context: fork` inherits conversation history) checked against the live docs and found wrong. The agent did not emit a VERDICT line, a tally, or the rubric table -- a defect in the agent, recorded here rather than smoothed over. |
| 2026-08-29 | *(self)* `0419f6b..HEAD` — the seven fixes from review 1 | **VOID** (was: ESCALATE) | 10 raised | Halt under sections 2a and 4.1. F1/F2 are observations of the run itself: the frontmatter hooks and tools allow-list did not apply, and the CLAUDE.md it received was the pre-`c9b7e64` version. Cause is a claim about the harness, correctly marked UNVERIFIED BY ME. F3-F10 stand on repo artefacts and are unfixed. Gap noted by the reviewer: commit `0419f6b` has never been reviewed. |
| 2026-08-29 | *(self)* configuration probe — **no work reviewed** | **ESCALATE** | n/a — no diff adjudicated | Halt under 4.1. Scope was five verbatim questions about the running agent's own configuration. Established that the prompt, `CLAUDE.md` and `tools:` scoping were all current while the PreToolUse guard did not fire. Produced the removal in `0381df6` and ADR 0006. |
| 2026-08-29 | *(self, in part)* `0419f6b..09278d2` | **ESCALATE** | 3 raised, 0 adjudicated | Halt under 4.2, 4.4 and the SKILL.md self-configuration touch, any one sufficient. Findings under items 1, 3, 4, 7, derived before the halt and not a verdict on the work. **First non-VOID review of any diff in this repo:** fresh session, clean tree, agent body at `HEAD`, and the agent's own symptom check found every section this range adds present in its prompt and the removed one absent. Escalated to the human unresolved; `0419f6b` itself remains outside the range and unreviewed. |

### Why reviews 1 and 2 are VOID

Both ran in the session that was building the reviewer, and a configuration probe
on 2026-08-29 established that neither reviewed the configuration it appeared to.
The probe found the running agent's system prompt missing section 2a — committed
in `8585810`, before review 2 — and its `CLAUDE.md` still carrying the
`Gate 0 passed` status block that `c9b7e64` had already moved out. The agent type
only became registered partway through that session, so review 1 and review 2 did
not even run from the same configuration as each other.

**Their findings were not acted on**, except F8, which was fixed in `d5d98e5`
because the defect was verifiable directly in the artefact and did not depend on
which configuration reported it. F3 to F7 and F9 to F10 remain untouched.

**Kept, not deleted.** A voided review in the record is evidence about the
harness: it is what established the staleness rule now in `CLAUDE.md`. A deleted
one is a gap that looks like a stretch where nobody asked for a review, which is
the failure the log's own limitation section warns about. Same argument as
keeping this file git-tracked at all.

The verdict column records what the review returned; the VOID marking records
whether it was from a configuration that existed. Those are different facts and
the row keeps both.

### The 2026-08-29 configuration probe

Run from a freshly restarted interactive session with workspace trust accepted —
the state the staleness rule in `CLAUDE.md` requires, and the last remaining
explanation for the guard's earlier silence. It asked the agent five verbatim
questions about its own configuration and instructed it not to review anything.

What it established, in the order it matters:

1. The reviewer ran `git -C "d:/Projects/signalbox" diff` and `cd ... && git status
   --short && echo`. The committed guard denied both by construction. No denial
   appeared. **The frontmatter PreToolUse hook does not apply.**
2. Its system prompt carried section 2a and its `CLAUDE.md` was post-`c9b7e64`.
   **Both current.** So `tools:` scoping and the prompt are applied and the
   `hooks:` key is not — which halves voided review 2's F1 rather than confirming
   it, and means **prompt freshness is not evidence of hook wiring**.

The guard is removed; see [ADR 0006](../decisions/0006-reviewer-read-only-enforcement.md)
and the standing claim in [`../limits.md`](../limits.md).

**This row counts as an escalation and reviews no work.** The tally it feeds
therefore overstates coverage, and the gap the reviewer named itself is unchanged
and now larger: `0419f6b` has never been validly reviewed, and nothing from
`0419f6b` to HEAD has a non-void review behind it — the guard removal included.

That last part cannot be fixed from here. The removal changes `.claude/agents/`, so
a review of it in the session that made it would be reviewing a configuration that
no longer exists, and would be VOID on arrival. It needs a restart first.

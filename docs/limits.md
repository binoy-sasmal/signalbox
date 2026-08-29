# Honest limits

What this system is not. Stated before anyone asks.

**Scope of this file right now.** It carries the limits discovered while building
the review machinery. `docs/PLAN.md` section 9 remains the authoritative list for
the platform itself and has not yet been transcribed here — it is written against
a Stage 1 that has not started. Do not read this file as complete.

---

## The reviewer cannot be the sole reviewer of its own construction

A `*(self)*` row in [`reviews/log.md`](reviews/log.md) marks a review of the review
machinery itself. That is the one subject where the `gate-reviewer` agent has the
conflict its own rubric item 7 exists to catch: the incentive runs one way, and a
reviewer that finds its own construction sound has told you very little.

Not solved in this repo, and no attempt should be made to solve it here. A second
reviewer would carry the same blind spot for the same reason, and a rule forbidding
self-review would only mean the machinery goes unreviewed. **The human
gate-boundary review is what covers it** — see the review-position rule in
`CLAUDE.md`.

Recorded rather than mitigated. A limitation written down can be walked through; a
limitation quietly worked around gets discovered.

The evidence so far is encouraging and not conclusive. On its first run the agent
raised eight findings against the four commits that built it, seven of which
verified. On its second it escalated rather than ruling, and caught the defect that
put this very section in the wrong file. That is evidence it does not simply
approve itself. It is not evidence that it found everything.

## The review machinery's own enforcement is unconfirmed

As of 2026-08-29 it is **not established** that Claude Code applies the
`gate-reviewer` agent's frontmatter — its `tools` allow-list or its PreToolUse
guard — when the agent is dispatched through `/review`. Both reviews to date came
from a configuration that was never verified.

Until a deliberate test settles it, every claim about the reviewer being read-only
is a claim about a mechanism, not an observation of one. `.claude/hooks/` contains
72 passing tests; none of them can prove the harness honours what they check.

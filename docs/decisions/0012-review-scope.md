# 0012 — Review scope: stage boundaries and two triggers, not every gate

**Status:** Accepted
**Date:** 2026-08-30
**Related:** ADR 0004 (probe methodology — one of the two triggers), ADR 0006 (reviewer
read-only enforcement), `docs/reviews/log.md` (the record this decision changes the shape of)

> **Numbering.** 0011 is not used here; it is not a gap left unexplained, it is simply not
> this decision's number. If a document turns up expecting 0011, that is a separate
> question from this one.

## Context

CLAUDE.md has required stating the review position at every gate boundary since Stage 1
began, and in practice that requirement was read as also requiring an *attempt* to run
`/review` at every boundary — five gates in, that has produced seven review invocations,
five of which returned a verdict (all ESCALATE) and two of which returned nothing at all: a
session-quota error at the `f22366f..874e808`/`874e808..HEAD` boundary, and a session rate
limit mid-synthesis at Gate 5's boundary, on 2026-08-30, after the range had already been
corrected once to include a commit the log's own row would have skipped.

Both failures blocked a gate boundary for hours before the position could be reported at
all — the opposite of what a fast-feedback discipline is supposed to buy.

## Decision

**`/review` runs at two trigger conditions, not at every gate boundary:**

1. **Stage boundaries.** Stage 0 → Stage 1 already happened before this rule existed; the
   next is Stage 1 → Stage 2, when Gate 9 closes. A stage boundary is a bigger claim than a
   gate — it is where PLAN.md itself says the next stage's design assumptions get
   committed to — and it is the boundary an ESCALATE actually has room to be acted on
   before the next piece of work builds on top of it.
2. **Any range that touches the enforced credential gate** (`scripts/probe/check_no_secrets.py`
   and its test suite) **or a measurement rule governed by ADR 0004** — `scripts/probe/analyse.py`,
   its counterparts in `services/ingest` (`decode.py`'s key and classification logic,
   `churn.py`), or ADR 0004 itself. These are the two places a subtle defect has actually
   cost something and self-review has not reliably caught it (see *Where the value was*,
   below) — not because either is disproportionately dangerous code in the abstract, but
   because both are places where a rule *reads as narrower than it is* and the failure mode
   is silent by construction: an exemption, a suffix set, a key that isn't a key. `git log`
   over the touched paths decides this mechanically; it is not a judgement call per range.

**A gate boundary no longer triggers `/review` on its own.** Stating the review position at
every gate boundary — the date, range and verdict of the last one, from `reviews/log.md` —
**is unchanged and still required.** What changes is whether that statement is preceded by
a fresh invocation. Under this rule most gate boundaries will report a review position that
predates the gate, and that is now the expected, correct shape rather than a gap to flag.

**The rubric stays as a self-check on every turn, unconditionally.** `gate-reviewer`'s
rubric items — an exemption satisfied by an input that doesn't satisfy its intent, a test
that cannot fail, a claim with no capture behind it — do not require spawning the agent to
apply. This decision scopes *when the isolated agent runs*, not whether its standards are
used. That costs nothing and is not part of what is being cut.

### Why, stated as three separate claims

**1. Cost.** Each review invocation is a real budget expense, and the two that returned
nothing still spent it — a subagent fanning out into seven or eight parallel angle-checks
before the orchestrator that would synthesise them into a verdict died. Two failures in
five gates, both on the exact review the rule requires most (a gate boundary), is not a
tail risk this repo can keep absorbing as a fixed cost of stating position.

**2. Where the value actually was.** Every finding a review returned that the builder had
not already caught, across all five valid reviews, came from a range that touched
`check_no_secrets.py` or ADR 0004's measurement logic. The standout: review 6's F1, the
expression exemption in `check_no_secrets.py` that waved through roughly half of all
base64-shaped secrets — `+` is in the standard base64 alphabet and was also one of the
characters the exemption matched on — with **no test in the suite able to fail on it**, and
all three near-miss tests missing by accident of fixture choice rather than by the
exemption's own logic being sound. That defect shipped in `df63680` with a green suite and
sat there until a review that read the parser, not the intent, found it. Nothing about that
defect was visible from running the tests; it needed an outside reader.

**3. Why the marginal value dropped for everything else.** Every other finding this session
would have wanted a review for was instead caught by the builder applying the same rubric
without spawning the reviewer:

- The `trip_id` semantic-key collapse — HSL publishes no `trip_id`, Stage 0's key mapped
  1,348 entities onto 4 keys, `median_churn_keyed_on_semantic_key: 0.250` was never a churn
  rate. Found by reading a run's own two disagreeing numbers, not by review.
- **The fix for that finding's own fail-first proof was itself incomplete on the first
  pass** — two mutations passed a suite that should have caught them, because the tests
  covered an isolated function and not the report computation the bug actually lived in.
  Caught by running the mutations and reading the result, the exact rubric-item-3 method
  this repo's reviews have used since row 5 of the log — applied without a reviewer present.
- The `.sql` coverage gap in `check_no_secrets.py` — closed by the repo's own
  `test_every_tracked_file_is_scannable`, written for exactly this shape of gap, firing
  without anyone invoking `/review`.
- HSL's transport-compression claim, wrong since Stage 0 run 2 widened the feed set — found
  by re-deriving a claim before relying on it, not by an outside read.
- `run-awake.sh`'s exit-code laundering — a wrapper's cleanup trap silently substituting its
  own exit status for the wrapped command's, found by noticing a run had written no rows
  rather than by review.

Five self-caught findings against one review-found finding, in the same body of work, is
the evidence that the rubric is now load-bearing on its own rather than only through the
isolated agent.

## The cost, stated rather than hidden

**`0f8fbe0..HEAD` — all of Gate 5 — goes unreviewed, and this is not the new rule correctly
skipping a low-value range.** `git log 0f8fbe0..HEAD -- scripts/probe/check_no_secrets.py`
shows two commits touching it directly: `cfd90ac` (narrowing the bracket-depth exemption)
and `2b502bc` (widening `TEXT_SUFFIXES` to include `.sql`). **Under this rule's own trigger
condition, that range qualifies for review.** What is being recorded is not an exemption
this range earns — it is a deliberate decision not to force a third `/review` attempt on a
range that has already failed to produce a verdict twice, accepting the range as
permanently unreviewed history rather than an open obligation. Anyone reading this ADR
should read that plainly: the rule said review it, and it was not reviewed, because the
cost of a third attempt was judged not worth it after two failures. That judgement is the
human's, made with the touch-condition stated in front of them rather than discovered
later.

## What would reverse this

**If two or more real defects are later found — by a review, by a human, by anything — in
ranges this rule would have let pass unreviewed, the scope was wrong**, not merely
unlucky. That is a falsifiable condition, not a vague promise to revisit. It does not
require the defects to be catastrophic; it requires them to be real (the kind a review
records as a numbered finding, not an observation) and to sit in ranges that touched
neither trigger. If that happens, this ADR should be amended or superseded rather than
quietly worked around, and the amendment should say what changed — a third trigger
condition, or a return to boundary-triggered review — rather than restate the same rule
with a caveat bolted on.

## Consequences

- `CLAUDE.md`'s gate-boundary language is corrected to state the review position without
  implying a fresh invocation is expected. `docs/status.md` restates the new scope where a
  reader needs to know it applies going forward.
- Gates 2–9, individually, do not trigger `/review` merely by passing. Stage 1 → Stage 2
  does.
- A range touching `check_no_secrets.py` or ADR 0004's measurement logic still triggers
  `/review` regardless of whether a gate or stage boundary is also in play — the two
  conditions are independent, not gate-boundary-gated.
- The review log (`docs/reviews/log.md`) will show longer gaps between rows under this
  regime. That is the intended shape, not an emerging absence to flag — the absence rule in
  CLAUDE.md is amended accordingly, not silently left to contradict this decision.

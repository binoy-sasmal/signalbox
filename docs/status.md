# Status

**Where the project is right now.** This file is builder-written narrative: a claim about
what has been achieved, not the evidence for it. Evidence lives in `docs/metrics.md`,
method lives in `docs/decisions/`, and what transfers out of a stage lives in its findings
document.

It is deliberately kept out of `CLAUDE.md` and out of `docs/PLAN.md`'s header. Both of
those load into context automatically, which would put this summary in front of the
`gate-reviewer` agent as ambient framing rather than as an artefact it chose to open. A
reviewer that absorbs the builder's account of its own work inherits that account's blind
spots. Here, the reviewer reads this file only if it decides to, and reads it as a claim
under review.

Update this file when a gate closes. Nothing else should restate it.

---

## Current position

**Gate 0 passed 2026-08-29.** Three feeds usable for ingest with measured cadence — VBB
(29.0s), HSL trip updates (15.0s), OVapi trip updates (60.0s) — all three
`header_timestamp_trust: generation`. gtfs.de is characterised and **excluded as a tenant
on measured resource grounds**. Findings that outlive the probe:
[`stage0-findings.md`](stage0-findings.md). Evidence: [`metrics.md`](metrics.md).

**Gate 1 passed 2026-08-29.** Repo layout and remote state. Verified on the observed
result the gate names, not on configuration that looked right:

```
### terraform init - platform (S3 backend) - FRESH CLONE, NO LOCAL STATE ###
Successfully configured the backend "s3"!
Terraform has been successfully initialized!
[exit 0]
```

The clone was made from the repo with `git clone`, and the only file present under
`infra/` besides the `.tf` sources was `.terraform.lock.hcl` — no `.terraform/`
directory and no `.tfstate`. The bucket was confirmed independently through the AWS
CLI: versioning `Enabled`, all four public-access blocks `true`.

**Re-observed and committed as an artefact 2026-08-29** after review 6's F3, which
found this narrative was the only record of the gate. [`runs/gate1/`](../runs/gate1/)
holds program output redirected to disk, not text retyped from a terminal: a fresh
clone, `init` against the real S3 backend downloading the provider from scratch, the
`s3api` responses, and `fmt -check` plus `validate` for both configurations.

**One claim was narrowed by that capture.** This section previously said `terraform
plan` "round-tripped the backend (`No changes.`)". `list-objects-v2` shows the bucket
is **empty** — the platform configuration has never been applied, so there is no state
object to round-trip. What was demonstrated is read access and correct backend wiring.
Nothing in this repo has yet written an object to that bucket; the first `apply` will
be the first write. The `plan` output itself is no longer reproducible either, because
Gate 2 added resources to the same configuration — it was never part of the gate's
criterion, which is `init` from a fresh clone.

Terraform `1.16.0`, AWS provider `6.62.0`, both pinned exactly; the Terraform
download was checksum-verified against HashiCorp's published `SHA256SUMS`.
Decisions in [ADR 0007](decisions/0007-terraform-state-backend.md).

**What is NOT verified.** `use_lockfile = true` is configured and its mechanism was
confirmed from HashiCorp's documentation, but **concurrent lock behaviour has not
been observed** — no two Terraform runs have contended for this state. The claim
"state locking works" rests on documentation, not on evidence from this repo.

**Gate 5 passed 2026-08-30.** Ingest service, one tenant (`hsl_tripupdates`), one feed.
PLAN.md section 7's criterion — *"run locally against the live feed for one hour. Record
parse failure rate, duplicate rate, and bytes saved by conditional requests"* — is met on
observed evidence: 719 requests, 08:07:18–09:07:18 UTC, coverage 99.9%, exit 0. Full
observed-vs-predicted comparison, including two findings recorded rather than resolved
(a false-200 divergence, and a 30% body-size shift traced to Stage 0's single-hour
duration), under "Observed, 2026-08-30" in [`metrics.md`](metrics.md). Raw evidence:
[`runs/gate5/`](../runs/gate5/).

**Design agreed before any code was written**, per CLAUDE.md rule 1 — feed, poll interval,
backpressure, dedup key, storage shape and scheduling were each presented with options and
a recommendation, and confirmed before implementation. ADR 0005 (scheduling) finalised at
this gate; ADR 0009 (storage model, dedup key) and ADR 0010 (backpressure) newly written.
Seven falsifiable predictions were committed **before** the run, so nothing could be
interpreted into passing afterward — PLAN.md section 6.6's own discipline applied a second
time, to a gate rather than a probe.

**Building it found a real Stage 0 defect**, the strongest finding Gate 5 produced: HSL
publishes no `trip_id` at all, so Stage 0's semantic key collapsed 1,348 entities per
snapshot onto four keys, and `median_churn_keyed_on_semantic_key: 0.250` was never a churn
rate — it was one of four date-buckets changing. Recomputed under the key GTFS-RT's other
form actually provides: 0.2879, identical to `entity.id`'s. Full mechanism, and the
guard this produced (`assert_key_is_a_key()`, ADR 0004 §8 instance 9 — a new dimension,
not another sampling case), in `1fe868e`. Verified holding under an
hour of live traffic afterward: 1,745 distinct trips, 1,745 keys, zero collisions.

**A second real defect was found and fixed before this gate was declared passed**, on the
same day, in response to the question "is there actually no issue, or has none been looked
for": HTTP statuses outside 200/304/transport-error built an outcome string
(`f"unexpected_{status}"`) that could never be a member of the closed failure taxonomy, so
a 429 or 500 from the upstream would be recorded to Postgres correctly and vanish from
`pipeline_outcomes.failures` — the number Gate 8's SLI 1 will read. Same shape as ADR
0010's drop-laundering concern, one layer over. It did not corrupt this run's evidence
(`status_counts` was `{200, 304}` only, confirmed by replaying the run's real statuses
through the fixed classifier rather than assumed:
[`runs/gate5/unexpected-status-fix-replay-check.txt`](../runs/gate5/unexpected-status-fix-replay-check.txt)),
so a second hour-long run against the live feed was not taken — what needed proving was
correctness for status codes this run never received, and that is proven by the fix's own
fail-first mutation suite instead
([`runs/gate5/unexpected-status-fix-fail-first.txt`](../runs/gate5/unexpected-status-fix-fail-first.txt)),
which constructs those codes directly. **The first fail-first pass on this fix was itself
incomplete** — it tested the isolated classifier and missed that the report's failure sum
had its own separate bug, caught only by running the mutations and reading that two of them
passed clean. One of those two turned out to be a no-op in the mutation harness itself, not
evidence about the code; both are recorded in the capture rather than only the corrected
result.

**What is NOT verified.** No `/review` has adjudicated this code. Two attempts both failed
before producing a verdict — a session-quota error and, after the range was corrected, a
session rate limit mid-synthesis — and per the rule already in
[`reviews/log.md`](reviews/log.md), neither is a row there. See *Review position*, below,
for the full account and the corrected range a retry should use. **This gate is declared
passed on the observed evidence PLAN.md's own criterion asks for, which is a different and
narrower claim than "reviewed."** The human decision to write it passed under that
condition is recorded here as the human's, made after being shown the review gap explicitly
rather than having it absorbed silently into a clean-looking status line.

**Stage 0 complete. Stage 1 in progress**, and from 2026-08-30 no longer strictly in
order: Gate 1 passed, Gate 2 written but blocked, **Gate 5 passed**, Gates 3, 4 and 6–9
not started. The reasoning for taking Gate 5 out of order is under *Reordering*, below.
A single "gate N of 9" would assert a sequence that no longer holds.

## Review machinery — closed 2026-08-29

Built between Stage 0 and Stage 1, and now settled. The `gate-reviewer` agent and the
`/review` skill stay. The PreToolUse read-only guard is **removed**: a configuration probe
found it not firing in the one session tested, and a check that does not run is not
enforcement ([ADR 0006](decisions/0006-reviewer-read-only-enforcement.md)).

What the reviewer's read-only property actually rests on — enforced tool scoping,
unenforced `Bash`, and restraint — is in [`limits.md`](limits.md), stated at its real size.
The finding worth carrying: **prompt freshness is not evidence of hook wiring.**

**Review position.** Seven rows in [`reviews/log.md`](reviews/log.md). Two are VOID. The
third is the probe, which adjudicated no work. The fourth through seventh —
`0419f6b..09278d2`, `407dc67..f22366f`, `f22366f..874e808` and `874e808..HEAD`, all
2026-08-29 — are the **valid reviews in this repo**, run from restarted sessions whose
configuration was current. All four returned ESCALATE.

So the claim that survives is the narrower one: **no valid review has adjudicated work in
this repo.** Four have now read it and raised fifteen findings and three observations
between them, all actioned. The `0419f6b` gap is closed — `407dc67..f22366f` is
`0419f6b~1..HEAD` and includes that commit.

**Every valid review has escalated, and none has returned ACCEPT or REJECT.** That is a
fact about the review process as much as about the work, and it is stated here rather
than left to be noticed.

**Review 7 named that pattern itself and asked for what would end it.** Its words: five
consecutive escalations, zero merit adjudications, and *"a reviewer that only ever
escalates is functionally close to no reviewer"*. It checked whether it was escalating
reflexively, concluded not, and identified the cause as structural rather than a matter of
verdict-setting: the credential-gate predicate and the OCI tenancy blocker sit in every
range, so each keeps firing a halt until it is ruled on once. **Both rulings were given —
see *Settled or scheduled*, below.** Neither instructs a reviewer to accept anything; they
remove two standing halt triggers so a range can be ruled on at all.

What the escalations put to the human, and what came back: the guard removal stands and
Option 3 was confirmed as their decision; the voided reviews' F3–F7 and F9–F10 are
recorded as **unrecoverable** rather than reconstructed, with the reasoning in the log.

**One deliberate gap, since read.** `f22366f..38a9542` — 15 commits, including a
methodology change to the enforced credential gate — was accepted unreviewed by the human
at the Gate 1 boundary, with the contents and the risk stated first. Review 6's range
strictly contains it, so it has now been **read but not adjudicated**: that review
escalated rather than ruling. Recorded under *Deliberate gaps* in
[`reviews/log.md`](reviews/log.md), not as a table row, because no review was invoked on
that range.

**The risk it named came true, which is why the entry now records a cost.** The commit it
singled out, `df63680`, is where review 6 found F1 — the credential gate's expression
exemption waving through roughly half of all base64-shaped secrets, with no test in the
suite able to fail on it. Accepting the gap was not wrong; the risk was stated first. It
is now an observed cost rather than an abstract one.

## Settled or scheduled — two rulings, 2026-08-29

Recorded here because review 7 showed that neither was a question about a diff, and both
were re-halting every range that contained them.

**1. The narrowed expression predicate is APPROVED as it stands. Settled.** Including its
accepted unmatched-opener gap, which is now pinned by a fixture, a bullet in
[`limits.md`](limits.md) and ADR 0004 §13's eighth entry rather than closed. Closing it
would require depth to return to zero plus a second carve-out for `AUTH_PARAM_PATTERNS = (`
— two exemptions to defend instead of one — and that cost is measured, not asserted
([`runs/secrets-gate/unmatched-opener-fail-first.txt`](../runs/secrets-gate/unmatched-opener-fail-first.txt)).
**A future range containing this predicate is not a methodology change to the enforced
gate.** A new change to it would be.

**2. OCI versus Hetzner is a SCHEDULED decision, not an open question.** The 2026-09-05
deadline stands and the decision is the human's on that date. Until then it is a recorded
pending decision; a range that merely contains the blocker is not thereby escalatable. The
blocker itself is real and unchanged — see *Next*, below.

## Reordering — Gate 5 taken while Gate 2 stays blocked, 2026-08-30

**Gate 2 is blocked on a tenancy that does not exist and cannot be unblocked by working
harder at it.** Rather than idle until 2026-09-05, Gate 5 (ingest service) is taken now.
This is recorded as a decision, before any of it is built, because the alternative is that
a reader later infers a violation of `PLAN.md` section 2 rule 2 — *one gate at a time* —
from the commit order alone.

**The distinction being claimed, stated so it can be disagreed with.**

- **Scaffolding ahead** is speculative work on something not yet reached: building Stage 2's
  tenant module while one tenant exists, writing the Helm chart before the service, adding a
  provider abstraction for a second cloud nobody has chosen. Its defect is that the
  requirements are not known yet, so the work encodes guesses that later have to be unpicked.
- **Reordering** is doing work whose requirements are already fixed, in a different order,
  because the work in front of it is blocked on someone else. Nothing is guessed; only the
  sequence changes.

Gate 5 is the second, and the test is that **every input it needs already exists and none of
them is an output of Gates 2, 3 or 4**:

| Gate 5 needs | Where it comes from | Blocked by OCI? |
|---|---|---|
| A feed with measured cadence, parse rate and conditional-request behaviour | Stage 0, run 2 and 2b | no |
| Python and a local Postgres in Docker | this machine | no |
| Its verification — one hour against the live feed, locally | `PLAN.md` section 7, Gate 5 | no |

Its verification is *"run locally against the live feed for one hour"*. There is no cluster
in that sentence, and no step of it consults anything Gate 2 produces.

**What this does not do, and the honest cost.**

- **Gate 2 is not passed, not skipped and not abandoned.** It is blocked, its configuration
  is written and statically checked, and its verification remains unrun. Nothing here changes
  that entry.
- **Gates 6–9 stay blocked behind Gates 2–4** and are not reordered. Gate 6 is the Helm chart
  deployed by ArgoCD; it needs a cluster and it waits. **If Gate 5 work starts producing chart
  templates or cluster manifests, that is scaffolding ahead and this entry is being abused.**
  That is the line, written down in advance rather than judged afterwards.
- **"Gate N of 9" stops describing the position.** Progress through Stage 1 is now a set, not
  a count: Gate 1 passed, Gate 2 blocked, Gate 5 in progress, Gates 3, 4, 6–9 not started.
  This file says so rather than reporting a number that implies an order that no longer holds.
- **Accepted risk.** A service designed with no cluster in front of it may need rework when
  Gate 6 puts one there — configuration surface, logging shape, readiness. The mitigation is
  the bullet above: Gate 5 stays free of Kubernetes assumptions, so what Gate 6 adds is
  packaging rather than redesign. If that turns out wrong, the cost lands at Gate 6 and gets
  recorded there.

**The OCI decision deadline is unchanged.** 2026-09-05, the human's, between continuing to
wait on the support ticket and falling back to Hetzner CX32 — exactly as recorded under
*Settled or scheduled* and *Next*. **Reordering is not a substitute for resolving it**, and
having other work in flight on that date is not a reason to let it slide. It removes the
idleness, not the blocker.

## Review position — Gate 5, 2026-08-30

**A `/review` was invoked and did not produce a verdict.** Recorded here rather than as a
row in [`reviews/log.md`](reviews/log.md), by the rule already written there — *"a `/review`
invocation that produces no adjudication is not a row"* — the same rule that governed the
identical situation once before (see the entry below this one).

**The range, computed rather than copied from the log.** Review 7's row in `reviews/log.md`
reads `874e808..HEAD`, but that names HEAD *as it stood when review 7 ran*, not the current
one. Its own text says review 7 covered "7 commits: the six responses to review 6, and the
OCI signup rejection." Exactly seven commits between `874e808` (exclusive) and `0f8fbe0`
(inclusive) match that description, and `0f8fbe0`'s own message is "record the OCI signup
rejection" — confirming it as review 7's actual endpoint. The correct next range is
`0f8fbe0..HEAD`, which includes `e7e362e` — the first commit responding to review 7 — as its
first member. A range copied verbatim from the log's own row would have silently skipped it.

**What ran, and where it stopped.** The `gate-reviewer` agent forked into eight parallel
angle-checks over `0f8fbe0..HEAD`. Seven returned findings — some real, none adjudicated.
The eighth (a cross-file tracer) never returned. The orchestrating pass that verifies,
dedupes and ranks those findings into a verdict began — its last recorded words were "All
consistent and verified. Let me wait for the remaining subagent responses now" — and then
failed on a session rate limit before completing. **No ACCEPT/REJECT/ESCALATE, no rubric
table, no adjudicated finding list exists from this invocation.**

**The raw sub-agent output is not being treated as a review**, and is not summarised here.
Some of it may be right — two independent angles both flagged that HTTP statuses outside
200/304/transport-error produce an outcome string absent from Gate 5's failure taxonomy,
which if real is exactly the kind of gap ADR 0010 exists to prevent. But an unverified,
unranked, un-deduplicated pile of subagent claims is not what this repo's discipline calls a
review, and treating it as one here would be exactly the shortcut CLAUDE.md's rule on
`/review` exists to close off — *"it reads artefacts, not your account of them."* Retry after
the session limit resets (2:30pm Europe/Berlin), same range.

**So the position going into this boundary is unchanged from what it was before this
attempt**: no valid review has adjudicated anything since review 7 closed at `0f8fbe0`. That
covers all of Gate 5 — the reordering decision, the three Stage 0 corrections, the service
build with its committed predictions, the trip_id-collapse findings, and the hour-run
evidence. **Gate 5 is not recorded as passed anywhere in this file, and will not be until
either a review adjudicates this range or the human decides otherwise.**

## Known Stage 2 prerequisite — the credential gate cannot see `PASSWORD 'value'`

Recorded here, not only in `docs/limits.md`, so it is read **before** Stage 2 role DDL is
written rather than found after a leak. `docs/limits.md` is where a reader goes looking for a
known limit; this file is where a reader goes looking for what to do next, and this gap has a
concrete next action attached to a stage that has not started.

**The gap.** `.sql` joined the structural credential gate's scan set at Gate 5 (2026-08-30),
widening coverage rather than exempting anything. Its `key = value` / `key: value` rule anchors
on a delimiter — `:` or `=` — between the name and the value. **Postgres's own DDL syntax for
setting a password has no such delimiter**: `CREATE ROLE tenant_x LOGIN PASSWORD 'secret';` is a
keyword followed by a string literal. The rule that exists to catch credentials cannot see the
canonical way SQL spells one. Pinned as a failing-as-designed test,
`test_GAP_sql_string_literal_syntax_evades_the_key_value_regex`, in
[`scripts/probe/test_check_no_secrets.py`](../scripts/probe/test_check_no_secrets.py) —
asserted clean today, with an instruction in the test itself to flip it to `assertCaught` the day
it closes.

**Why it matters now rather than later.** Stage 2 (`docs/PLAN.md` section 11) provisions
per-tenant Postgres roles, and role-creation DDL is exactly the shape this gap describes. Nothing
about that work is blocked — the gap is a known limit of an enforced gate, not a missing
capability — but the person writing that DDL should know before they write `PASSWORD '...'` in a
file the credential gate will wave through.

**What closing it would need**, so it is not re-derived at Stage 2: a keyword-aware rule for
`.sql` specifically — matching `PASSWORD`, `IDENTIFIED BY` and equivalents against the string
literal that follows them, independent of `:`/`=`. Out of scope for Gate 5, which touched no role
DDL; in scope the day Stage 2 does.

## Next

**Gate 2** (Terraform: OCI cloud floor), `docs/PLAN.md` section 7.
**Configuration written and validated. NOT passed — blocked on tenancy creation.**

Observed so far: `terraform fmt -check` clean, `init` successful against the real
S3 backend, `validate` successful, and `plan` failing at `open ~/.oci/config: The system
cannot find the path specified` — the blocker reported by Terraform rather than asserted
here. The static checks now also run in CI on every push
([`terraform-check.yml`](../.github/workflows/terraform-check.yml)), so they are no longer
a local claim.

**Those two `plan` observations are now captures, not narrative.** Review 7's F2 found this
paragraph and ADR 0008 asserting both the `~/.oci/config` failure and the `node_image_ocid`
validation rejection with nothing under `runs/` behind either — review 6's F3 recurring one
commit after its fix. [`runs/gate2/`](../runs/gate2/) holds both runs as an A/B pair one
variable apart, so the rejection is visibly the validation rule firing rather than noise
from the missing config. The same directory holds the image-refresh command tokenising
correctly, after F4 found it had never been runnable. The gate's actual verification — *"destroy then apply produces a working
SSH-able node. Twice. With no manual step"* — has not run and cannot until a tenancy
exists. Decisions in [ADR 0008](decisions/0008-oci-cloud-floor.md).

**The tenancy does not exist, and the reason is not known to us.** An OCI account signup
was **rejected on 2026-08-29**. Oracle returned their generic *"unable to complete your
sign up"* response, which does not name the check that failed. A support ticket is open;
expect days rather than hours. **The cause is recorded as unknown.** Nothing here should
be read as a diagnosis — no message from Oracle identified a card, an address, an identity
check or a capacity limit, so naming one would be exactly the plausible-sounding invention
this repo's evidence rules exist to prevent.

**Decision deadline: 2026-09-05.** If the ticket is unresolved by then, the human decides
between continuing to wait and falling back to **Hetzner CX32 (~EUR 7/month)**, already
carried in `CLAUDE.md` as the settled fallback. **This is a scheduled decision, not an open
question** — see *Settled or scheduled*, above.
[ADR 0008](decisions/0008-oci-cloud-floor.md) holds the reasoning for choosing OCI, so
taking the fallback would be a **recorded reversal with its cost stated** — an amendment
written against that reasoning, and a monthly bill where the Always Free allowance had
none — not a retreat. **No Hetzner configuration is written, and none should be** until
that decision is taken; writing it now would be scaffolding ahead of a choice the human
has not made.

**Discharged early:** the Always Free allowance re-verification that `PLAN.md`
section 3 requires at this gate. Unchanged on 2026-08-29 — [`metrics.md`](metrics.md).

**Three values the operator must supply at apply time**, none committed:
`compartment_ocid`, `ssh_ingress_cidr` and `node_image_ocid`. The second has no default
deliberately — it is a home IP, and this repo is public. The third has none because the
value has never been observed: it is pinned rather than resolved (ADR 0008 decision 4,
reversed after review 6's F4), and its default gets filled in at Gate 2 from the value
actually applied. Committing an OCID nobody has seen would be inventing a number.

**Review position for that boundary.** Review 6 ran on 2026-08-29 over
`f22366f..874e808` and returned **ESCALATE** — four findings and two observations, all
now actioned. That range covers Gate 1's work and Gate 2's configuration, and closes the
gap the previous version of this paragraph reported. Both methodology changes to the
enforced credential gate (`df63680` and `f1d0951`) have now been read.

**That gap is now closed.** Review 7 ran on 2026-08-29 over `874e808..HEAD` — the six
commits responding to review 6, including the third methodology change to the credential
gate — and returned **ESCALATE**: four findings and one observation, all actioned. The
narrowed predicate has now been read by someone who did not write it, and the reading
found a real gap in it (F1). See [`reviews/log.md`](reviews/log.md).

**What is unreviewed is what came after that:** the four commits responding to review 7,
this one included. Stated because it is the gap that exists at this boundary, not because
it is unusual.

**An earlier `/review` on the same range did not run.** It returned a session-quota error
in place of a verdict: no adjudication, no rubric, no findings. It is recorded here because
an unreviewed range looks identical whether a review was never asked for or was asked for
and could not execute, and nothing else in this repo tells those apart. **It is not a row
in [`reviews/log.md`](reviews/log.md), and that is decided by the rule already written
there** — *"a `/review` invocation that produces no adjudication is not a row"* — not left
open. The previous version of this paragraph deferred the question to the human while the
log had already answered it; that was review 7's O1.

Gate 2 re-verifies the OCI Always Free allowance before provisioning — `PLAN.md`
section 3 marks that number as the one most likely to have moved.

Carry into Stage 1: **a measurement must declare its preconditions and stand down when they
fail** (ADR 0004 section 8, five worked examples). This applies directly to Gate 8's SLIs —
an SLI over a window with too few samples reports a reassuring number rather than "no data",
which is the same failure in a far more expensive place.

**Last updated:** 2026-08-30 (UTC)

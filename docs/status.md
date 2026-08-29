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

**Stage 0 complete. Stage 1 in progress: Gate 1 of 9 passed.**

## Review machinery — closed 2026-08-29

Built between Stage 0 and Stage 1, and now settled. The `gate-reviewer` agent and the
`/review` skill stay. The PreToolUse read-only guard is **removed**: a configuration probe
found it not firing in the one session tested, and a check that does not run is not
enforcement ([ADR 0006](decisions/0006-reviewer-read-only-enforcement.md)).

What the reviewer's read-only property actually rests on — enforced tool scoping,
unenforced `Bash`, and restraint — is in [`limits.md`](limits.md), stated at its real size.
The finding worth carrying: **prompt freshness is not evidence of hook wiring.**

**Review position.** Six rows in [`reviews/log.md`](reviews/log.md). Two are VOID. The
third is the probe, which adjudicated no work. The fourth, fifth and sixth —
`0419f6b..09278d2`, `407dc67..f22366f` and `f22366f..874e808`, all 2026-08-29 — are the
**valid reviews in this repo**, run from restarted sessions whose configuration was
current. All three returned ESCALATE.

So the claim that survives is the narrower one: **no valid review has adjudicated work in
this repo.** Three have now read it and raised eleven findings and two observations
between them, all actioned. The `0419f6b` gap is closed — `407dc67..f22366f` is
`0419f6b~1..HEAD` and includes that commit.

**Every valid review has escalated, and none has returned ACCEPT or REJECT.** That is a
fact about the review process as much as about the work, and it is stated here rather
than left to be noticed.

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

## Next

**Gate 2** (Terraform: OCI cloud floor), `docs/PLAN.md` section 7.
**Configuration written and validated. NOT passed — blocked on tenancy creation.**

Observed so far: `terraform fmt -check` clean, `init` successful against the real
S3 backend, `validate` successful, and `plan` failing at `open ~/.oci/config: The system
cannot find the path specified` — the blocker reported by Terraform rather than asserted
here. The static checks now also run in CI on every push
([`terraform-check.yml`](../.github/workflows/terraform-check.yml)), so they are no longer
a local claim. The gate's actual verification — *"destroy then apply produces a working
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
carried in `CLAUDE.md` as the settled fallback.
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

**What is unreviewed is what came after it:** the six commits responding to review 6,
`874e808..HEAD`, which include a third methodology change to that same gate — the
narrowed expression predicate in `72506e4`. It ships with adversarial tests verified by
making them fail, which is the standard the new hard rule in `CLAUDE.md` now requires, but
nobody who did not write it has read it. That is the gap to state at the Gate 2
boundary.

**A review of that range was invoked on 2026-08-29 and did not run.** `/review
874e808..HEAD` returned a session-quota error in place of a verdict: no adjudication, no
rubric, no findings, nothing to report. It is recorded here because an unreviewed range
looks identical whether a review was never asked for or was asked for and could not
execute, and nothing else in this repo tells those two apart. Whether it also belongs in
[`reviews/log.md`](reviews/log.md) as a row is left to the human — the tally there counts
invocations and this was one, but it produced nothing to log. The range is unreviewed
either way.

Gate 2 re-verifies the OCI Always Free allowance before provisioning — `PLAN.md`
section 3 marks that number as the one most likely to have moved.

Carry into Stage 1: **a measurement must declare its preconditions and stand down when they
fail** (ADR 0004 section 8, five worked examples). This applies directly to Gate 8's SLIs —
an SLI over a window with too few samples reports a reassuring number rather than "no data",
which is the same failure in a far more expensive place.

**Last updated:** 2026-08-29

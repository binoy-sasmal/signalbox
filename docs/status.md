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
directory and no `.tfstate`. `terraform plan` then round-tripped the backend
(`No changes.`), and the bucket was confirmed independently through the AWS CLI:
versioning `Enabled`, all four public-access blocks `true`.

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

**Review position.** Five rows in [`reviews/log.md`](reviews/log.md). Two are VOID. The
third is the probe, which adjudicated no work. The fourth and fifth — `0419f6b..09278d2`
and `407dc67..f22366f`, both 2026-08-29 — are the **first valid reviews in this repo**,
run from a restarted session whose configuration was current. Both returned ESCALATE.

So the claim that survives is the narrower one: **no valid review has adjudicated work in
this repo.** Two have now read it and raised five distinct findings between them, all
actioned. The `0419f6b` gap is closed — `407dc67..f22366f` is `0419f6b~1..HEAD` and
includes that commit.

What the escalations put to the human, and what came back: the guard removal stands and
Option 3 was confirmed as their decision; the voided reviews' F3–F7 and F9–F10 are
recorded as **unrecoverable** rather than reconstructed, with the reasoning in the log.

**One deliberate gap.** `f22366f..38a9542` — 15 commits, including a methodology change
to the enforced credential gate — **will not be reviewed**, decided by the human at the
Gate 1 boundary with the contents and the risk stated first. Recorded under *Deliberate
gaps* in [`reviews/log.md`](reviews/log.md), not as a table row, because no review ran.
The review clock restarts at Gate 1.

## Next

**Gate 2** (Terraform: OCI cloud floor — VCN, subnet, gateway, route table, NSG,
compute, block volume), `docs/PLAN.md` section 7. **Not started.**

**Review position for that boundary, stated now so it is not discovered later:**
**no review has run over Gate 1's work.** The clock restarted at Gate 1 by the
deliberate-gap decision above, and Gate 1 then closed without one. Its range is
`38a9542..HEAD` and it includes a second methodology change to the enforced
credential gate (`f1d0951`, the gate-only `key` exemption) on top of the one already
inside the unreviewed gap. Two gate changes now sit unreviewed, not one.

Gate 2 re-verifies the OCI Always Free allowance before provisioning — `PLAN.md`
section 3 marks that number as the one most likely to have moved.

Carry into Stage 1: **a measurement must declare its preconditions and stand down when they
fail** (ADR 0004 section 8, five worked examples). This applies directly to Gate 8's SLIs —
an SLI over a window with too few samples reports a reassuring number rather than "no data",
which is the same failure in a far more expensive place.

**Last updated:** 2026-08-29

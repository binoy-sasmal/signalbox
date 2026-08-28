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

**Stage 0 complete. Stage 1 not started.**

**Next action is Gate 1** (repo layout and remote state), `docs/PLAN.md` section 7. Do not
start it without being asked.

Carry into Stage 1: **a measurement must declare its preconditions and stand down when they
fail** (ADR 0004 section 8, five worked examples). This applies directly to Gate 8's SLIs —
an SLI over a window with too few samples reports a reassuring number rather than "no data",
which is the same failure in a far more expensive place.

**Last updated:** 2026-08-29

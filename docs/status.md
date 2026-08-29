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

## Review machinery — closed 2026-08-29

Built between Stage 0 and Stage 1, and now settled. The `gate-reviewer` agent and the
`/review` skill stay. The PreToolUse read-only guard is **removed**: a configuration probe
established it never fired, and a check that does not run is not enforcement
([ADR 0006](decisions/0006-reviewer-read-only-enforcement.md)).

What the reviewer's read-only property actually rests on — enforced tool scoping,
unenforced `Bash`, and restraint — is in [`limits.md`](limits.md), stated at its real size.
The finding worth carrying: **prompt freshness is not evidence of hook wiring.**

**Review position.** Three rows in [`reviews/log.md`](reviews/log.md). Two are VOID. The
third is the probe, which adjudicated no work. **No valid review has run against any work
in this repo.** `0419f6b` onward, the guard removal included, has never been validly
reviewed — and the removal cannot be reviewed from the session that made it, because it
changes `.claude/agents/`.

## Next

**Gate 1** (repo layout and remote state), `docs/PLAN.md` section 7. Beginning now.

Carry into Stage 1: **a measurement must declare its preconditions and stand down when they
fail** (ADR 0004 section 8, five worked examples). This applies directly to Gate 8's SLIs —
an SLI over a window with too few samples reports a reassuring number rather than "no data",
which is the same failure in a far more expensive place.

**Last updated:** 2026-08-29

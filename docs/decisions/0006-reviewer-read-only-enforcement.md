# 0006 — The reviewer's read-only property: what enforces it

**Status:** Accepted
**Date:** 2026-08-29
**Related:** [`../limits.md`](../limits.md) (where the standing claim lives),
[`../reviews/log.md`](../reviews/log.md) (the probe row and the two voided reviews)

## Context

The `gate-reviewer` agent needs `Bash` to read a diff from git. `Bash` reaches
`git commit`, `rm` and `terraform apply`. A prompt saying "do not mutate anything"
is a request, and this repo's own argument — rubric item 9, applied to Conftest,
to Gatekeeper and to the credential check — is that a local gate is feedback and
only the enforced gate is enforcement.

So a PreToolUse hook was built and wired from the agent's frontmatter
(`ee62582`), hardened to fail closed (`1212d8d`), and given a wiring test and a CI
job (`433b34d`). 73 tests, three days.

## The observation

On 2026-08-29, from a freshly restarted interactive session with workspace trust
accepted, a configuration probe asked the running reviewer to run:

```
git -C "d:/Projects/signalbox" diff
```

It returned a diff. The guard refuses that command for its pre-subcommand `-C`
option. The reviewer then ran `cd ... && git status --short && echo`, which the
guard refuses three separate ways — `&` is outside the character allow-list, and
neither `cd` nor `echo` is an allowed command — and got exit 0. No denial text
appeared on either.

Workspace trust was the last remaining explanation for the earlier non-firing seen
in voided review 2. This eliminates it.

The same probe established the other half:

- The agent's function list was exactly `Read, Grep, Glob, Bash`. No `Write`, no
  `Edit`, no `Agent`. The frontmatter `tools:` line is applied.
- Its system prompt contained section 2a, committed in `8585810`. Its `CLAUDE.md`
  was post-`c9b7e64`. Both current.

**The frontmatter is read. The `hooks:` key inside it does nothing.** Prompt
freshness and hook wiring were assumed to travel together; they do not. That is
the finding that outlives the guard, and it is why voided review 2's F1 — which
reported the prompt *and* the hooks as stale together — was only half right.

*Why the hook does not apply is a claim about Claude Code's own behaviour and is
not asserted here.* What is asserted is the observation: two commands the
committed guard denies by construction were executed without a denial.

## Options

1. **Keep the guard and probe before every review.** Run the `git -C` command
   first; treat a denial as the only positive evidence the guard is live, and
   treat a review without one as unconstrained.
2. **Move the guard to project-level `settings.json` hooks** rather than agent
   frontmatter, and scope it some other way.
3. **Remove the guard and state the smaller true claim.**

## Decision

**Option 3.** Taken by the human, on the reasoning below, recorded here rather
than decided here.

A check that does not run is not enforcement — that is this repo's own argument,
and it does not stop applying when the check is one we built. Worse, a check that
*looks* like enforcement is worse than none: it buys false confidence and costs
maintenance. Section 2 of the agent told every reviewer that a hook enforced
read-only "rather than trusting this paragraph", which was the exact overstatement
rubric item 10 exists to catch, sitting in the file that carries the rubric.

Option 1 was rejected on cost. Gating every review on a probe makes the review
machinery something that has to be verified before it can be used, and three days
of machinery to watch the work is already more than the watching is worth.

Option 2 was not attempted. A project-level hook would fire for the builder too,
which is a different and larger change, and its wiring would rest on the same
unverified harness behaviour that Option 3 exists to stop relying on.

**Better a smaller true claim than a larger one that needs a probe before every
use.**

## Consequences

The read-only property now rests on three things of very different strength, and
[`../limits.md`](../limits.md) states them separately rather than as one claim.
The reviewer's own section 2 says the same, so it does not believe it is guarded
when it is not.

A reviewer with unrestricted `Bash` and no guard is a real exposure. It is
mitigated by the tool scoping that *is* enforced — no `Write`, no `Edit`, no
`Agent` — and otherwise by restraint, which was observed once, when the reviewer
refused a destructive probe on the grounds that a launching agent's instruction is
not the human's consent. Once is not a guarantee and this file does not call it
one.

## The `git -C` probe, kept as a diagnostic

The probe command is documented in [`../limits.md`](../limits.md) and wired to
nothing. It is inert against the current configuration — with no guard installed,
it can only succeed — so it proves nothing today. It is kept because it is the
method, and the reasoning for choosing it, that whoever next tries to wire a
PreToolUse hook here will need.

## What would reopen this

Evidence that agent-frontmatter `hooks:` blocks do apply — a documented mechanism,
or a denial observed in a live review. Either turns this from a settled removal
back into a design question.

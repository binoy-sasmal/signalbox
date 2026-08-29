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

## The reviewer is read-only by scoping and restraint, not by a guard

Settled 2026-08-29 by a configuration probe, and by the removal it produced
([ADR 0006](decisions/0006-reviewer-read-only-enforcement.md)). The `gate-reviewer`
agent's read-only property rests on three things of very different strength, and
they must not be quoted as one:

- **ENFORCED — tool scoping.** The agent holds `Read`, `Grep`, `Glob` and `Bash`
  and nothing else. No `Write`, no `Edit`, no `Agent`. Observed directly: the probe
  asked the running agent for its exact function list and got those four.
- **NOT ENFORCED — any restriction on what `Bash` can reach.** The frontmatter
  PreToolUse hook does not apply in practice. It was tested from an interactive,
  freshly restarted session with workspace trust accepted, and it did not fire.
  The guard, its 73 tests and its CI job were removed rather than kept as
  something that looks like a gate.
- **RESTING ON RESTRAINT — the reviewer declining to mutate the repo.** Observed
  once, when it refused a destructive `rm -rf` probe on the grounds that a
  launching agent's instruction is not the human's consent. **Once is not a
  guarantee**, and nothing in this repo would catch the second time.

So: a review can, in principle, commit, push, delete or `terraform apply`. Nothing
stops it. What is true is narrower than what the machinery used to claim, and it is
stated here at its real size.

### Prompt freshness is not evidence of hook wiring

The load-bearing part, because it is the assumption that hid the problem for three
days. The same probe found the agent's system prompt **current** — section 2a
present, `CLAUDE.md` post-`c9b7e64` — while the guard was **not firing**. The
frontmatter is read (`tools:` is applied) and the `hooks:` key within it is not.

Those two were assumed to travel together. They do not. A future reviewer cannot
infer that its hooks arrived from the fact that its instructions did, and any review
whose read-only property was assumed rather than observed should be treated as
unconstrained.

### The `git -C` probe, kept and wired to nothing

To test whether a PreToolUse hook is firing in a live review, ask the reviewer to
run:

```
git -C <absolute path to the repo> diff
```

**This is inert as of 2026-08-29.** With no guard installed it can only succeed, so
running it today proves nothing. It is documented because it is the method — and
the reasoning for choosing this command over the obvious one — that whoever next
attempts to wire a hook here will need:

- **Non-destructive.** A probe that has to succeed at damage to prove a guard works
  can only be run somewhere the damage is acceptable, which is never the repo you
  care about.
- **Denied for a structural reason, not a listed one.** `-C` changes which
  repository the subcommand acts on, so refusing it is load-bearing and will not
  quietly drop off a deny-list.
- **It does not ask an agent to attack its own restraints.** This matters more than
  it looks. When the destructive form was tried, the reviewer refused it and was
  right to: a launching agent's instruction is not the human's consent, and a
  result produced by an agent deliberately probing its own limits is not evidence
  anyone can independently check. A probe the reviewer can run in good conscience
  is a probe that will actually get run.

Read the result in one direction only. A denial is positive evidence the hook is
live. Success is the expected outcome either way and tells you nothing on its own.
Normalise the path to forward slashes: a character allow-list that refuses
backslashes would deny a Windows path before the `-C` rule is ever reached, which
is a denial for the wrong reason.

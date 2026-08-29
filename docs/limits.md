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
  PreToolUse hook did not fire in the one session it was tested from — an
  interactive, freshly restarted session with workspace trust accepted. **n=1,
  and the cause is UNVERIFIED**; do not read this as "frontmatter hooks never
  work". What follows either way is that nothing observed here constrains `Bash`,
  so the guard, its 73 tests and its CI job were removed rather than kept as
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
present, `CLAUDE.md` post-`c9b7e64` — while the guard was **not firing**. So in
that session the frontmatter was read (`tools:` was applied) and the `hooks:` key
within it did not take effect. One session; why is UNVERIFIED.

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


## The credential gate: one half closed, one half open

Recorded 2026-08-29, after an AWS `credentials` file was created at `.aws/credentials`
inside this repo instead of `~/.aws`. It was caught by reading a directory listing.
No gate was involved, and — measured, not assumed — no gate would have been.

This is rubric item 3 turned on our own check: **a gate that cannot fire and a gate
with nothing to fire on look identical from outside** is this repo's own sentence,
written in `check_no_secrets.py`'s test suite. It applies here.

### Half one: scope. It walks tracked files.

`main()` with no arguments calls `tracked_files()` — `git ls-files`. An untracked
credential in the working tree is invisible to it. While `.aws/credentials` sat in
this repo, the gate reported `passed (49 file(s) scanned, 0 skipped)`, and both
statements were true at once.

So **a pass means "no tracked file violates the rules", never "the working tree is
clean."** The first moment a credential file becomes visible to the tracked-file scan
is the commit that adds it.

### Half two — CLOSED 2026-08-29 in `df63680`: the rule was gated on file suffix.

**This half is fixed. It is kept here because how it was found is the transferable
part.** `check_no_secrets.py` restricted its `key = value` rule to a suffix set —
`.yaml .yml .json .toml .ini .cfg .env .tfvars`. An AWS credentials file is
**extensionless**. `is_scannable()` admitted it, so it was counted as scanned, and
then the one rule that would have caught it never ran. Measured with a synthetic key
pair, never a real one:

| File | Before `df63680` | After |
|---|---|---|
| `credentials` (extensionless) | `passed (1 scanned, 0 skipped)` | **FAILED** on `aws_secret_access_key` |
| identical bytes as `creds.ini` | **FAILED** | **FAILED** |

So, before the fix: **had `git add -A` staged `.aws/credentials`, neither the
pre-commit hook nor the CI job would have stopped the commit.** Both would have
scanned the file and both would have passed it.

The shape, which is the part worth carrying: `is_scannable()` had been widened to
admit extensionless files *precisely because* credentials live in them, and the rule
that catches credentials was left gated on suffix. **The widening opened the hole it
was meant to close.** Rubric item 1 — an exemption satisfied by an input that does not
satisfy its intent — for the fifth or sixth time here.

The fix runs the rule on every scannable file. Adding `""` to the suffix set was
rejected: it closes this case and leaves `.rego`, `.conf` and `.tpl` open for the
identical reason. The cost of ungating is that source files come into scope, where an
auth-shaped name is routinely bound to an expression; `is_an_expression()` exempts
those structurally, on the ground that a credential is a single opaque token.

#### That exemption was itself a bypass, and is narrowed — 2026-08-29, review 6's F1

**The predicate exempted any value containing one of `()[]{}+,`.** It mixed characters
a credential CANNOT contain with characters it CAN: `+` is in the standard base64
alphabet, so roughly half of all base64-shaped secrets carried their own exemption with
them. AWS's own published example secret key circulates in a `/` variant and a `+`
variant, and the gate caught the first and waved the second through.

Three tests came within one character of finding this and all three missed on fixture
choice — the base64 case used a value with no `+`, the AWS fixture used the `/` variant,
and the planted key is `sk-live-...`. Fixture choice was doing the work the test was
supposed to do.

Narrowed to two disjuncts, each requiring syntax in a position a token cannot occupy:
bracket structure, decided by a left-to-right stack scan rather than by character
presence, and a `+` flanked by whitespace on both sides. `,` is dropped entirely. The
generalisation is in [ADR 0004](decisions/0004-probe-methodology.md) section 13: **an
exemption predicate must be defined over the complement of the protected value's
alphabet.**

**Two known and accepted gaps remain in it. Both are now pinned as fixtures marked
*intentional exemption*, not left to this file alone** — an accepted gap with a test is
a decision; one recorded only in prose is something the next person closes or widens
without knowing it was deliberate.

- **A literal split across an operator.** `api_key = "sk-" + "live-real"` reads as an
  expression and is exempt.
- **A credential carrying a nested bracket pair.** `sk-live-abc(def)` is exempt.
  Accepted on the ground that no credential format this project handles — base64,
  base64url, hex, JWT — admits a bracket at all, so it is not a shape a pasted secret
  arrives in. Weaker than the alphabet argument for `+`, and recorded at that strength.

Both are deliberate bypasses rather than accidental commits, and this gate's threat
model is the accident.

**And the reason it stayed invisible:** `TestEveryTrackedFileIsInScope` asserts a
tracked file is *scanned*. It says nothing about which rules then run on it, so it
could never have failed on this. `TestTheRulesRunOnEveryTrackedSuffix` now plants a
credential under every suffix present in the tree and requires each to be caught.
**"Scanned" without "and the relevant rules ran" is not coverage.**

### A third gap, narrower and accepted: unqualified `key`

Opened deliberately 2026-08-29, at Gate 1, the first time real Terraform met this
gate. Terraform's S3 backend names its state object path `key`, so
`key = "platform/terraform.tfstate"` is a path — and the gate rejected it, because
`"key"` is a bare substring in `AUTH_PARAM_PATTERNS`.

**The root cause is not a bug, and that is the interesting part.** `is_auth_param`
is shared by two callers whose cost asymmetries are opposite. Its own comment says
it is *"deliberately broad: over-redacting a manifest costs nothing"* — true for the
probe's `redact_query`. In the gate, over-matching blocks a legitimate commit and
pushes people toward `--no-verify`, which is the failure the CI half of this gate
exists to prevent. One predicate cannot be tuned for both.

So the gate now has its own narrowing, `is_auth_key_for_gate`, exempting the
**exact** name `key`. `allowlist.is_auth_param` is untouched and redaction stays
broad.

**The hole this opens:** an unqualified `key: <literal credential>` in a config file
now passes. In this repo secrets are `*_ref` pointers by schema, so the shape should
not arise — but *should not* is not *cannot*, and it is written here rather than
left implicit.

**What holds it at that size.** Every qualified form still fires, and widening the
exemption to substring matching turns 26 tests red, including the numeric,
placeholder and extensionless suites. Scope is config keys only: the URL
query-parameter path is deliberately untouched, because `?key=` is a real
API-key idiom and some transit APIs authenticate exactly that way — which is why
endpoints are stored split in the first place.

### Half one stays OPEN: scope

Nothing above changes it. The check still walks tracked files, and an untracked
credential in the working tree is still invisible to it.

*What would close it:* scan untracked-but-unignored working-tree files, as a
pre-commit concern rather than a tracked-file one. The tracked-file scan is the wrong
instrument — by the time a file is tracked the decision has been made. `git status
--porcelain --untracked-files=all` minus ignored paths is the candidate set.

**Deliberately not implemented, and the asymmetry is the reason.** Half two failed
toward a *false pass*: it reported a file as scanned and clean while it held a key
pair. Half one fails toward *not looking*, which is honest — the gate never claims to
have inspected the working tree. A limitation that understates its own coverage can
be worked around by someone who reads it; one that overstates cannot.

Until it is done, `.gitignore`'s credential patterns are what stands between
`git add -A` and a pushed key — and an ignore rule is not a gate: `git add -f`
overrides it, and it covers only the paths someone thought of in advance.

# Review log

One row per `/review` invocation of the `gate-reviewer` agent. The agent reads this
file at the start of every review and reports the running tally in its output.

**Why this file rather than agent memory.** Claude Code's subagent `memory` field
would have done the tracking, but enabling it automatically grants the subagent
Read, Write and Edit — which would undo the read-only scoping the agent exists
under. A git-tracked file keeps the reviewer read-only, and has the better property
anyway: it is a diff. Agent memory is opaque, this is not.

**What it cannot see.** It records reviews that happened. It cannot record a review
that was never requested, and that — not a corrupted row — is the realistic failure:
`/review` quietly not being run for six turns during a good stretch. CLAUDE.md
covers that separately, by requiring the builder to state the last review's date,
range and verdict at every gate boundary, and to report the absence of one as the
finding when none has run since the previous gate.

**Written by the builder, read by the reviewer.** The builder appends the row after
each verdict. A builder could omit a REJECT, but the omission is visible in git
history, which is more than opaque memory would offer.

**A `*(self)*` row reviewed the review machinery itself.** That is a real
limitation, recorded in [`../limits.md`](../limits.md) rather than here. This file
carries rows, not argument: a reviewer is instructed to read it before it reads a
diff, so anything persuasive in it arrives as framing rather than as evidence.

## Format

| Date | Range reviewed | Verdict | Findings | Notes |
|---|---|---|---|---|

- **Date** — ISO date of the review.
- **Range reviewed** — the git range or working-tree scope given to `/review`,
  verbatim. `working tree + HEAD` when invoked with no argument.
- **Verdict** — `ACCEPT`, `ACCEPT WITH AMENDMENTS`, `REJECT`, or `ESCALATE`.
  Prefixed **`VOID`** if the review turned out to have run from a configuration
  that no longer existed — see the staleness rule in `CLAUDE.md`. VOID is not a
  fifth verdict: it records that the review was not valid, while the parenthesised
  original records what it returned. A VOID row counts in neither the review tally
  nor the rejection tally.
- **Findings** — count, and the rubric item numbers they fell under. `0` if clean.
  The count is an index, not the record. The findings themselves are written out in
  full under *Findings in full*, below the rows. A row carrying only a count is a
  finding waiting to be lost — see `CLAUDE.md`, and see F3–F7/F9–F10, which were.
- **Notes** — one line. For `ESCALATE`, which halt condition fired.

## Log

| Date | Range reviewed | Verdict | Findings | Notes |
|---|---|---|---|---|
| 2026-08-29 | *(self)* `b1626f2..HEAD` — the review agent's own construction | **VOID** (was: no verdict returned) | 8 raised, 7 confirmed | Findings under items 1, 3, 9, 10. One claim (`context: fork` inherits conversation history) checked against the live docs and found wrong. The agent did not emit a VERDICT line, a tally, or the rubric table -- a defect in the agent, recorded here rather than smoothed over. |
| 2026-08-29 | *(self)* `0419f6b..HEAD` — the seven fixes from review 1 | **VOID** (was: ESCALATE) | 10 raised | Halt under sections 2a and 4.1. F1/F2 are observations of the run itself: the frontmatter hooks and tools allow-list did not apply, and the CLAUDE.md it received was the pre-`c9b7e64` version. Cause is a claim about the harness, correctly marked UNVERIFIED BY ME. F3-F10 stand on repo artefacts and are unfixed. Gap noted by the reviewer: commit `0419f6b` has never been reviewed. |
| 2026-08-29 | *(self)* configuration probe — **no work reviewed** | **ESCALATE** | n/a — no diff adjudicated | Halt under 4.1. Scope was five verbatim questions about the running agent's own configuration. Established that the prompt, `CLAUDE.md` and `tools:` scoping were all current while the PreToolUse guard did not fire. Produced the removal in `0381df6` and ADR 0006. |
| 2026-08-29 | *(self, in part)* `0419f6b..09278d2` | **ESCALATE** | 3 raised, 0 adjudicated | Halt under 4.2, 4.4 and the SKILL.md self-configuration touch, any one sufficient. Findings under items 1, 3, 4, 7, derived before the halt and not a verdict on the work. **First non-VOID review of any diff in this repo:** fresh session, clean tree, agent body at `HEAD`, and the agent's own symptom check found every section this range adds present in its prompt and the removed one absent. Escalated to the human unresolved; `0419f6b` itself remains outside the range and unreviewed. |
| 2026-08-29 | *(self, in part)* `407dc67..f22366f` | **ESCALATE** | 4 raised, 0 adjudicated | Halt under 4.2, 4.4 and the SKILL.md self-configuration touch. Findings under items 1, 3, 6, 7, 8, 10. Range is `0419f6b~1..HEAD`, so it **includes `0419f6b`** and closes the gap the previous three rows named. All four findings actioned on the human's instruction: the scan-coverage claim made structural (`2b01a5b`), the status/log contradiction fixed and ruled against recurring (`084818c`), the `hooks:` claim narrowed to n=1 (`5b0205c`, `4dcd30e`), and the voided reviews' findings disposed of (`ca9f13f`) — F3–F7/F9–F10 recorded as unrecoverable rather than reconstructed. |

### Why reviews 1 and 2 are VOID

Both ran in the session that was building the reviewer, and a configuration probe
on 2026-08-29 established that neither reviewed the configuration it appeared to.
The probe found the running agent's system prompt missing section 2a — committed
in `8585810`, before review 2 — and its `CLAUDE.md` still carrying the
`Gate 0 passed` status block that `c9b7e64` had already moved out. The agent type
only became registered partway through that session, so review 1 and review 2 did
not even run from the same configuration as each other.

**Their findings are disposed of individually below.** The previous wording here
was that they "were not acted on" and "remain untouched", which is a status, not a
disposition.

**Kept, not deleted.** A voided review in the record is evidence about the
harness: it is what established the staleness rule now in `CLAUDE.md`. A deleted
one is a gap that looks like a stretch where nobody asked for a review, which is
the failure the log's own limitation section warns about. Same argument as
keeping this file git-tracked at all.

The verdict column records what the review returned; the VOID marking records
whether it was from a configuration that existed. Those are different facts and
the row keeps both.

### Disposition of the voided reviews' findings

Recorded 2026-08-29, on the human's instruction, after the review of
`407dc67..f22366f` raised it. Voiding two reviews retires ten findings against the
builder's own work; a retirement nobody has to justify is precisely the shape
rubric item 7 exists to catch, so each is disposed of here rather than left
standing as "untouched".

**Recoverable, and closed:**

- **F1, F2** — observations of review 2's own run: that the frontmatter `hooks:`
  and `tools:` keys had not applied, and that the `CLAUDE.md` it received was
  pre-`c9b7e64`. **Adjudicated by the configuration probe, and half overturned.**
  `tools:` *was* applied and the `CLAUDE.md` *was* current; only the `hooks:` half
  held, and that half is now [ADR 0006](../decisions/0006-reviewer-read-only-enforcement.md)
  with the guard removed. Closed.
- **F8** — the self-review limitation sat in the reviewer's first read, framing it
  before it saw a diff. **Fixed in `d5d98e5`**, which moved it to
  [`../limits.md`](../limits.md). Actioned despite the void because the defect was
  checkable directly in the artefact and did not depend on which configuration
  reported it. Closed.

**Not recoverable: F3–F7 and F9–F10.**

Their text was never written to this repo. It is in no commit, no earlier revision
of this file and no commit message — checked with `git grep` across every revision
reachable from `--all`. It lived in a session transcript that no longer exists.
They cannot be enumerated, and no per-finding disposition can honestly be written.
Reconstructing seven plausible findings from memory would be worse than the gap.

Two things can be said about them without inventing their contents:

1. **Anything raised against the guard is moot by construction.** All four files
   under `.claude/hooks/` — the evaluator, the shell shim and both test suites —
   are deleted at `HEAD`. A finding against code that no longer exists has nothing
   left to attach to.
2. **Everything else in that range has since been read by a valid review.** Review
   2's range, `0419f6b..HEAD`, is a strict subset of `407dc67..f22366f`, reviewed
   on 2026-08-29 from a current configuration. Whatever was still live against the
   surviving artefacts had the opportunity to surface there. What surfaced was that
   review's four findings, all since actioned.

**That is a weaker guarantee than enumeration, and it is stated as one.** It is not
"each was checked". It is: the artefacts they were raised against have since had a
valid review, and the ones that no longer exist cannot carry a finding.

The transferable lesson is the reason this section exists at all — **a finding that
lives only in a transcript is a finding that can be lost.** Write findings into this
log when the verdict arrives, not on the assumption that a range can be re-reviewed
later. Re-review regenerates what is still true; it does not recover what was said.

### The 2026-08-29 configuration probe

Run from a freshly restarted interactive session with workspace trust accepted —
the state the staleness rule in `CLAUDE.md` requires, and the last remaining
explanation for the guard's earlier silence. It asked the agent five verbatim
questions about its own configuration and instructed it not to review anything.

What it established, in the order it matters:

1. The reviewer ran `git -C "d:/Projects/signalbox" diff` and `cd ... && git status
   --short && echo`. The committed guard denied both by construction. No denial
   appeared. **The frontmatter PreToolUse hook does not apply.**
2. Its system prompt carried section 2a and its `CLAUDE.md` was post-`c9b7e64`.
   **Both current.** So `tools:` scoping and the prompt are applied and the
   `hooks:` key is not — which halves voided review 2's F1 rather than confirming
   it, and means **prompt freshness is not evidence of hook wiring**.

The guard is removed; see [ADR 0006](../decisions/0006-reviewer-read-only-enforcement.md)
and the standing claim in [`../limits.md`](../limits.md).

**This row counts as an escalation and reviews no work.** The tally it feeds
therefore overstates coverage, and the gap the reviewer named itself is unchanged
and now larger: `0419f6b` has never been validly reviewed, and nothing from
`0419f6b` to HEAD has a non-void review behind it — the guard removal included.

That last part cannot be fixed from here. The removal changes `.claude/agents/`, so
a review of it in the session that made it would be reviewing a configuration that
no longer exists, and would be VOID on arrival. It needs a restart first.

## Findings in full

Per the rule in `CLAUDE.md`. Reviews 1 and 2 predate it and their findings are gone;
these are transcribed from the reviewer's own output, not from a summary of it.

### Review 4 — `0419f6b..09278d2`, 2026-08-29, ESCALATE

**F1 — voiding two reviews discharges eight findings that no longer exist anywhere.**
Rubric item 7. In `log.md`, the row for review 2 asserted "F3-F10 stand on repo
artefacts and are unfixed" while the prose repeated "F3 to F7 and F9 to F10 remain
untouched". The repo therefore asserted eight open, artefact-grounded findings and
recorded nowhere what any of them were; their content lived in a transcript that no
longer exists. Voiding was the correct call and the reasoning was sound, but the side
effect is that eight findings against the builder's own work became permanently
unenumerable in the same commit that declared them valid and outstanding — a change
that would not have been made the same way had the findings been in the builder's
favour. *What would close it:* write them out, or state plainly that they are
unrecoverable; the middle position is closeable by nobody.
**Disposed:** `ca9f13f`, and the rule in `0550456`. Unrecoverable, stated as such.

**F2 — ADR 0006 asserts the human made the decision; the artefact order shows
act-then-record.** Rubric item 4. The removal is `0381df6`; the ADR is `471af6a`, one
commit later, so the three options, their costs and the rejections of Options 1 and 2
all first appear in a document written after the guard was already deleted. CLAUDE.md
rule 1 is "options, tradeoff, recommendation. Then wait." A reviewer restricted to
artefacts cannot distinguish a decision the human made from one narrated as theirs
afterwards. The reviewer explicitly declined to call the claim false or established.
*What would close it:* the options presented before the removal commit, or the human
confirming directly.
**Disposed:** `89565a2`. The human confirmed Option 3 was their decision, taken before
the removal. Claim stands; the commit ordering was the defect.

**F3 — `is_scannable` keeps a bypassable suffix exemption under a claim of total
coverage.** Rubric items 1 and 3. `check_no_secrets.py` returned `False` for any suffix
outside `TEXT_SUFFIXES`, while CLAUDE.md claims the structural check "covers every
committed file". Smallest input satisfying the exemption without satisfying its intent:
any tracked UTF-8 text file with an unlisted suffix — `creds.conf`, `backup.xml`,
`local.properties`, `terraform.tfstate`. Coverage was 49/49 only by accident of the
current file set. The structural half: no test in the suite could ever fail when a newly
tracked file drops out of scope, because every case builds its own fixture. *What would
close it:* a test walking `git ls-files` asserting every tracked path is `is_scannable`.
**Disposed:** `2b01a5b`.

*Observations, not findings:* `.claude/settings.json` is gitignored, so ADR 0006's
Option 2 would now land in a file that does not rebuild from git — recorded in
`6737cec`. And the range was exclusive of `0419f6b`, leaving that commit unreviewed —
closed by review 5.

### Review 5 — `407dc67..f22366f`, 2026-08-29, ESCALATE

**F1 — "covers every committed file" is true of today's tree, not by construction.**
Rubric items 1, 3 and 6. Independent restatement of review 4's F3, with the live case
named: `.rego` is absent from `TEXT_SUFFIXES` and CLAUDE.md commits this repo to
Conftest, so Stage 3 adds policy files under exactly such a suffix. Also: `main()`
printed only the scanned count and never a skipped count, so coverage could shrink in
CI with no output changing. *What would close it:* assert `is_scannable()` over
`tracked_files()`, so the first unscannable tracked file is a red build.
**Disposed:** `2b01a5b`.

**F2 — `status.md` contradicts `reviews/log.md` at HEAD.** Rubric item 10. `status.md`
said "Three rows... **No valid review has run against any work in this repo**" while
`f22366f` had added a fourth row labelled the first non-VOID review of any diff here.
`status.md` was written in `40fceef` and never revisited. Both are tracked artefacts
asserting incompatible facts at the same commit; the narrower reading ("no valid review
has *adjudicated* work") survives, the sentence as written does not. *What would close
it:* update the review position in the same commit that adds a log row.
**Disposed:** `084818c`, which also added that rule to CLAUDE.md.

**F3 — the range deletes an enforced CI gate.** Rubric item 7. `review-guard.yml` ran on
`push:` and `pull_request:` at `407dc67` and does not exist at `f22366f`, and `0c9649b`
retired reviews 1 and 2's findings as "untouched". The reviewer did not dispute the
removal's reasoning; it recorded that both moves reduce outstanding obligations on the
builder, which is the incentive shape item 7 exists for, and that it is the human's call.
**Disposed:** guard deletion stands, affirmed by the human. The retirement was disposed
of properly in `ca9f13f`.

**F4 — "the `hooks:` key does nothing" is a harness claim generalised from n=1.**
Rubric items 8 and 10. ADR 0006 asserted "**The frontmatter is read. The `hooks:` key
inside it does nothing**" and `limits.md` "The frontmatter PreToolUse hook does not apply
in practice." What the artefacts support is narrower: in one probe session, two commands
the committed guard denies by construction executed with no denial. The step from that to
a general property of Claude Code is UNVERIFIED — the reviewer has no web access and the
repo settles nothing. Raised because ADR 0006 is otherwise scrupulous about that line and
these two sentences crossed it. *What would settle it:* the hooks documentation, or a
second observation from an independently configured session.
**Disposed:** `5b0205c`, and a third copy in `status.md` found and narrowed in `4dcd30e`.

*Note, not a finding:* whether `.claude/settings.json` is Claude Code's shared or local
settings tier is itself a harness claim, UNVERIFIED. Nothing left git either way, since
the file was never tracked.

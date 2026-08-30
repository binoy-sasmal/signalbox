# 0004 — Stage 0 probe methodology

**Status:** Accepted
**Date:** 2026-08-28
**Related:** ADR 0002 (the `feed_freshness` SLI this probe decides the validity of)

## Context

Stage 0 answers questions that shape things we cannot easily change later: the tenant schema, and
whether Gate 8's `feed_freshness` SLI means anything per tenant. The measurements therefore have to
be defensible, not merely produced. This ADR records how, and why each choice is the way it is.

## Decisions

### 1. The poller performs no analysis

Poller captures raw evidence; a separate offline analyser derives everything. The header-timestamp
analysis was wrong on its first pass, as expected. Re-running the analyser costs seconds; re-running
the poller costs polling budget we may not be able to afford on a rate-limited feed. Raw payloads
and raw allow-listed headers are stored because we do not yet know every question we will want to
ask.

### 2. Header timestamp: five tests, unanimity or `unknown`

A: content hash with the header timestamp zeroed. B: shape of lag over time. C: asynchronous
re-poll. D: header against entity timestamps. E: cross-check with HTTP `Date` / `Last-Modified`.

**Combination rule: unanimous among available tests, otherwise `unknown`.** Disagreement is not
resolved by argument. Per-test votes are recorded so a human can look, and the tenant stays
`unknown` until one does. Recording `unknown` costs us a tenant in the freshness SLO; recording a
guess costs us the SLO's credibility.

### 3. Test A is unavailable on static content

A degraded producer that still regenerates on schedule but emits a near-empty snapshot yields
identical content alongside a legitimately advancing generation timestamp — Test A's echo signature
from the opposite cause. The analyser detects the condition (low median entity count, low semantic
churn) and marks Test A unavailable rather than misreading it. Test C is unaffected by static
content and carries the verdict there. This is not hypothetical: VBB has been degraded since
2026-06-04.

### 4. `entity.id` stability is measured by ratio, with a denominator floor

`FeedEntity.id` is scoped to uniqueness *within a FeedMessage*, so a compliant `FULL_DATASET`
producer may regenerate it every snapshot. Churn keyed on it alone would report ~100% on a stable
feed and produce a wrong "dedup is impossible" finding.

Two rejected measures, both of which we implemented and then found wrong:

- **Churn disagreement.** Blind whenever a producer restamps every entity each snapshot — which is
  common. Both churn figures saturate at 100% and their difference carries no signal.
- **An absolute threshold on Jaccard id persistence.** Conflates unstable ids with genuine entity
  turnover. For a stable-id feed where a fraction *f* of entities enters and leaves between compared
  snapshots, persistence is `(1−f)/(1+f)`: 0.74 at f=0.15 but **0.43 at f=0.40**, which a 0.5 cut
  calls "regenerating" while the ids are perfectly stable.

**Decision: verdict on `id_persistence / semantic_persistence`.** Turnover moves both keyings
identically, so the ratio is invariant to it: ≈1.0 for stable ids at any turnover, ≈0 for
regenerating ids. Bands are ≥0.8 stable, ≤0.2 regenerating, otherwise indeterminate — the middle
band being consistent with partial regeneration across entity types. Id persistence is computed over
semantically-keyable entities only, so both keyings cover an identical population and an alert-heavy
feed cannot skew the comparison.

**Denominator floor: semantic persistence below 0.2 gives `indeterminate` regardless of ratio.** A
ratio of two small numbers is unstable, and that is exactly the far-apart-snapshot case that
motivated using a ratio in the first place. Below the floor the entity population itself has turned
over almost completely between compared snapshots and the measurement carries no signal. Reporting
indeterminate there is the honest outcome; reporting a ratio would be arithmetic dressed as
evidence.

**Every verdict records the wall-clock gap between the snapshots it was computed from.** A verdict
from snapshots eleven minutes apart is weaker evidence than one from ten seconds apart, and
`docs/metrics.md` must show that rather than presenting both as equal.

Verified against synthetic fixtures with known ground truth, including the 40%-turnover case that
broke the previous measure. Stable and regenerating fixtures with *identical* turnover and identical
semantic persistence separate 1.00 against 0.00.

**QUALIFIED 2026-08-30 — HSL trip updates' evidence for this method was degenerate, though its
verdict was not wrong.** Gate 5 found that HSL's `entity.id` persistence, as recorded in
`docs/metrics.md`, was computed with `semantic_persistence` measured against `(trip_id,
start_date)` — a key that collapses HSL's 1,348 entities per snapshot onto **four** keys, because
this producer supplies no `trip_id` at all. See §8 instance 9.

The population "both keyings cover an identical population" describes was, for HSL, four groups
rather than 1,348 entities. The `id_persistence / semantic_persistence` ratio computed from a
four-key denominator is not the number this method's design assumes it is measuring, whatever value
it happened to produce.

**The verdict stands regardless, for a reason external to this method.** Recomputed directly on
1,348 entities under the corrected key, `entity.id` and the corrected semantic key agree to four
decimal places (churn 0.2879 both, `runs/gate5/predictions.txt`) — which is the stable-id case this
method's ratio is built to detect, confirmed on the population the method was supposed to have used
in the first place. HSL's `stable` verdict is corroborated, not merely surviving.

**VBB, OVapi and `hsl_vehiclepositions` are unaffected.** Each populates the fields its own key uses
— `trip_id` for the first two, `vehicle.id` for the third — so none inherits HSL's collapse. This is
a defect in one tenant's key selection, not in the ratio method or in the other three verdicts.

### 5. Cadence is only a feed property if we sampled fast enough for it

**Nyquist rule: if the observed cadence is under twice the interval we actually
achieved, the figure is our sampling grid and is flagged unreliable.** Independent of the
header-timestamp verdict — undersampling and echo stamping are different ways for the same number
to be meaningless, and the analyser originally only flagged the second.

The interval compared against is **measured, not configured.** The configured value is a sleep
*after* each request completes, so a slow fetch silently widens the real interval: run 1 configured
5s against gtfs.de and achieved 17.8s, because each 40 MB fetch took 12–27s. Both are recorded; the
measured one is what any cadence claim is judged against.

**Grid-multiple clustering is corroborating evidence only, never an independent trigger.** It was
specified as one, and measurement showed it is unsound in both directions: it scored 0.0 on
gtfs.de — the worst real case — while flagging fixtures we were sampling four times faster than
they regenerate, where the cadence figure is correct. A feed whose period is a multiple of our
interval lands every delta on the grid legitimately. Nyquist caught both real cases; clustering is
reported because it is informative when it agrees.

**A second cadence measure comes from `Last-Modified`**, which is available on HEAD responses. For
a feed too expensive to GET at its true rate this is the only cadence we can afford to measure
honestly; for the others it cross-checks the header-derived figure at no cost. It is sampled at the
poll rate, not at the rate observations happen to carry the header — under conditional requests only
a *changed* response returns `Last-Modified`, so deriving the interval from those alone would equal
the cadence and trip the guard on a feed sampled perfectly well.

### 6. Test E compares the two references to each other, with a floor

An absolute tolerance discarded a discriminating result: on gtfs.de, `Last-Modified` sat 3.0s from
the header timestamp and `Date` 8.5s — a clear lean toward generation stamping — but both exceeded
a fixed 2s cut and the test returned `unavailable`. What matters is which reference is closer and by
how much, so the verdict now requires one to be at least **2× closer** than the other.

**Floor: if both references sit within 1s of the header timestamp, the answer is `unavailable`.**
Same argument as the id-stability denominator floor — below that separation the comparison is
sub-second jitter, and a verdict taken off it would be invented rather than measured.

### 7. Test C never sends validators, and is unreliable on slow feeds

Test C is defined as comparing two *bodies*. A 304 has none, so sending conditional headers on a
re-poll destroys the test rather than economising on it. Run 1 lost Test C on two of three feeds
exactly that way — both re-polls returned 304. Re-poll requests now send no validators and are
always full GETs even in HEAD mode.

A separate limit is structural and not worth fixing: the re-poll gap is measured from the completion
of the first fetch, so on a feed where a fetch takes 20s the two observations are ~22s apart, not
2s. Against gtfs.de's ~29s cadence the pair frequently straddles a generation. Closing that would
mean issuing both requests concurrently, which would break the single-flight property that keeps our
request rate honest. Test C is therefore expected to be unavailable on large, slow feeds, and those
verdicts rest on the remaining tests.

### 8. THE PRINCIPLE: a measurement declares its preconditions and stands down when they fail

**Silence from a structurally incapable test is not evidence of absence.**

This is the single most important thing Stage 0 produced. It was not designed in — it was found five
separate times, each time as a specific bug, before the shape common to all five became visible. Each
instance passed its fixture and failed on live data, and in three cases the test did not merely go
quiet: it returned a confident wrong answer that outvoted correct ones.

Every measurement here now states the domain in which its answer means anything, and reports
`unavailable` outside it rather than a number.

| # | Measurement | Precondition | Found on | What it did when violated |
|---|---|---|---|---|
| 1 | **Test A** — restamping via content hash | Content must actually change | VBB | Near-static content plus an advancing timestamp is A's echo signature from the opposite cause |
| 2 | **Test B** — sawtooth of lag | Cadence must span ≥5 one-second quanta, and median lag must fall inside `[0, cadence]` | `hsl_vehiclepositions` | Cleared its threshold by **0.0009** with a spread half its own model predicts |
| 3 | **Test C** — asynchronous re-poll | Re-poll gap must be shorter than the cadence | `hsl_vehiclepositions` | Returned a false `echo` that **outvoted two correct tests**, dragging the verdict to `unknown` |
| 4 | **Cadence** | Sampling must be at least 2× the cadence (Nyquist) | gtfs.de | Reported a 30s cadence that was purely our own sampling grid |
| 5 | **304 rate** | More than one poll per generation | OVapi | Reported 0% from **77 observations** in a regime where a 304 was near-impossible, and a Gate 5 design consequence was drawn from it |
| 9 | **Semantic churn** — dedup key partitions the population | The key must be 1:1 with the entities it identifies | HSL trip updates, Gate 5 | Collapsed 1,348 entities onto 4 keys and reported a plausible churn rate computed over the wrong population |

Instances 4 and 5 are the same statement about different quantities, which is what made the pattern
visible: **sampling at or near the rate of the thing you are measuring destroys the information you
are trying to collect.** The analyser had been taught that for cadence and not for 304 rates, so it
made the identical mistake twice in two hours.

**Instance 9 is a different dimension, found five months later while building Gate 5, and it belongs
in this table rather than a new one precisely because the principle is the same and the axis is
not.** Instances 1–5, 6–8 (below) all check a *sampling* precondition: was there enough signal, over
enough time, at a fine enough grain, for this test to have an opinion. Instance 9 checks a
*grouping* precondition instead: does the key a measurement aggregates by actually separate the
population it claims to describe. No amount of correct sampling rescues an aggregate computed over
the wrong groups — the two axes are independent, and this repo had a guard for one and none for the
other.

**HSL publishes no `trip_id` — 0 of 1,348 entities, every snapshot checked.** The semantic key
`(trip_id, start_date)` was written from the GTFS-RT specification's primary identification form
without checking which form this producer actually uses. On this feed it collapsed one snapshot into
**four keys**, one per `start_date`, and `median_churn_keyed_on_semantic_key: 0.250` was never a
churn rate over 1,348 entities — it was one of four date-buckets changing. Corrected to **0.2879**,
recomputed on the key GTFS-RT's other permitted form actually provides
(`route_id`+`direction_id`+`start_date`+`start_time`); identical to `FeedEntity.id`'s figure on this
feed. Full arithmetic in `runs/gate5/predictions.txt`; correction recorded in `docs/metrics.md`.

**The tell was in the committed output for days, survived a review, and was used as the basis for a
prediction that was approved.** The old key's churn carries a **p95 of 0.75** — three of four
date-buckets changing — which is not a shape a real key over 1,348 entities produces; a healthy
dedup key on a feed this size does not swing between "nothing changed" and "75% changed" from one
comparison to the next. The number was visible in `runs/run2/analysis.json` from the moment it was
committed. Nobody read it as a symptom, including during the review that ran over the range
containing it. It took building the consumer — a table that filled with 4 rows for 863 entities
while the same run's churn figure claimed 25% — to make the collapse impossible to miss.

**The guard this instance produced, `assert_key_is_a_key()`, has no analogue among 1–8.** It does
not check sample count, sampling rate, or content staticness; it checks that
`distinct_keys / keyable_entities` clears a threshold, and refuses rather than reporting a number
computed over a degenerate grouping. Any future dedup key — a second tenant, a different entity
type — inherits this check rather than this instance's specific bug.

Three properties of this failure that make it worth a principle rather than five patches:

- **Volume of evidence is no defence.** 77 observations produced a confident, actionable, wrong
  conclusion. More samples from an incapable measurement give more confidence in the same error.
- **It survives fixtures.** Every one of these passed synthetic tests, because a fixture only models
  the world its author already understood. See §14.
- **It is invisible in the output.** A test that cannot fire and a test that fired and found nothing
  produce identical numbers. Only the precondition distinguishes them, and only if someone wrote it
  down.

**A verdict also carries how many tests could speak to it.** Five tests agreeing and one test
unopposed are both "unanimous", and reporting them identically overstates the second. Verdicts read
`generation [strong, 4/5]` or `generation [weak, 1/5]`. Evidence strength travels with the verdict,
as the comparison gap travels with persistence.

#### Where this transfers, and why it matters more there

**Gate 8.** An SLI computed over a window with too few samples has exactly this problem, and it is a
far more expensive place to learn it. A burn-rate alert evaluated over a window containing three
requests is not a low error rate; it is no measurement at all — and unlike a probe, it will be
trusted by an on-call human at 3am. Every SLI recording rule must declare its minimum sample count
and report *no data* rather than a reassuring number below it. The multiwindow burn-rate alerts in
Gate 8 need this before they are wired to anything that pages.

**Gate 7.** A cardinality or scrape-health figure taken over a window shorter than the scrape
interval is the same error.

**Stage 2.** An onboarding-time measurement taken before a tenant has produced data is the same
error again, and would make every new tenant look healthy.

### 9. When two criteria documents disagreed, we measured rather than interpreted

A process finding worth keeping. PLAN.md section 6.6 defined "usable" before any numbers existed,
specifically so that nothing would need interpreting at the gate. Section 6.7's Gate 0 sentence
restated the criteria in its own words — and the two diverged: 6.6 accepted "established why a
cadence is not derivable", 6.7 asked flatly for "measured cadence". At the gate, two feeds had a
measured cadence and two had a documented reason why not.

**The right reading was probably 6.6**, since it was the purpose-built definition. It was still the
wrong way to settle it: choosing between two disagreeing documents by adopting the one that passes is
indistinguishable, from outside, from moving the goalposts — and a gate decided that way is not
evidence of anything.

The ambiguity was removed instead of argued. A 25-minute HEAD-only run resolved OVapi's cadence at
near-zero bandwidth, after which three feeds had measured cadences and the disagreement no longer
mattered. 6.7 now defers to 6.6 rather than restating it, so the two cannot diverge again.

**Generalisation for later gates:** when a gate's criteria admit two readings, the cost of removing
the ambiguity is usually far lower than the cost of a gate whose passage rests on a reading. Measure
first; reconcile the documents second.

### 10. Clock discipline

Wall clock anchored once; every interval from a monotonic base. NTP offset is **recorded, not
applied**, so the correction stays visible and reversible. A failed sync records `null` with a flag
and **never zero** — a silent zero is a fabricated measurement that would lend unearned precision to
every derived lag figure. HTTP `Date` provides an independent per-request reference.

### 11. No deliberate rate-limit provocation, on any feed

A 429 is recorded in full if it arrives, but we do not chase one. VBB is degraded, so provoking it
would perturb an upstream that is not behaving normally; CH holds a revocable key whose loss costs
the project a real capability. Section 6 of the plan originally called for approaching the documented
limit; that was dropped.

### 12. One endpoint is one feed id

Every timestamp test assumes one feed is one message stream. OVapi alone exposes four endpoints
(`tripUpdates`, `vehiclePositions`, `alerts`, `trainUpdates`) which may stamp differently. Two
config entries sharing an id would interleave two streams into a single verdict that looked
plausible and was meaningless. The poller rejects duplicate ids and non-string `base_url` at
startup.

### 13. Credential capture is structural

Headers by explicit allow-list, dropped at capture rather than redacted after. Endpoints stored
split into `base_url` plus a query map, never joined, because some transit APIs authenticate by
query parameter and a run manifest is not covered by a header allow-list. The check is a structural
assertion over every committed file and runs in CI as well as pre-commit, with an adversarial test
suite ahead of it — a gate that cannot fire and a gate with nothing to fire on look identical from
outside.

**Amended 2026-08-29.** "Over every committed file" was true of the tree and not of the code. The
file selector scanned a suffix allow-list plus extensionless files, so any tracked text file under
an unlisted suffix — `policy.rego`, `values.tpl`, `app.conf` — was silently out of scope, and the
adversarial suite could not see it: every case there builds its own fixture, so none of them can
fail when a *newly tracked* file leaves the scan set. The claim held by accident of which suffixes
happened to be present.

Closed by asserting the claim itself: a test over `git ls-files` requires every tracked file to be
scannable, and `main()` now prints the skipped count beside the scanned one. The `.rego` case is
not hypothetical — Conftest is a settled decision, so Stage 3 adds policy files under exactly such
a suffix.

*Recorded because of the shape, not the bug.* This is rubric item 1 — an exemption satisfied by an
input that does not satisfy its intent — for the fourth or fifth time in this repo. The pattern to
watch for is a value-parsing exemption, not a logic error: the numeric exemption, the placeholder
substring match, the angle-bracket value class, and now the suffix allow-list all failed the same
way. When a check exempts something, the question is what else satisfies the exemption.

**A predicate shared between redaction and gating is wrong by construction.**
Recorded 2026-08-29, at Gate 1, as a general lesson rather than the bug that produced it.

`is_auth_param` decides both what the probe redacts and what the gate rejects. Those two
uses have *opposite* cost asymmetries, and no single tuning is right for both:

| | over-matching costs | under-matching costs |
|---|---|---|
| **Redacting** output | nothing — a redacted non-secret is still readable | a live key in git |
| **Gating** a commit | a blocked legitimate change, and pressure toward `--no-verify` | a live key in git |

The allow-list's own comment — *"deliberately broad: over-redacting a manifest costs
nothing"* — is correct for the first row and false for the second. It was written for the
redactor and inherited by the gate without anyone deciding it should be.

It surfaced when the gate rejected `key = "platform/terraform.tfstate"`, Terraform's S3
backend argument for the state object path. Not a wrong rule: a rule tuned for the wrong
caller. The fix is a gate-local narrowing (`is_auth_key_for_gate`), leaving redaction broad.

**The transferable form:** when one predicate serves both a *sanitiser* and a *gate*, split
it before the first false positive, not after. The sanitiser wants recall, the gate wants
precision, and a gate that cries wolf teaches people to route around it — which this repo
already argues elsewhere and then did to itself.

**An exemption predicate must be defined over the complement of the protected value's
alphabet.** Recorded 2026-08-29, after review 6's F1. This is the seventh value-parsing
bypass in an exemption here, and the first one where the general rule is stateable.

`is_an_expression()` exempted any value containing one of `()[]{}+,`, on the reasoning that
a credential is a single opaque token and syntax means code. The reasoning was right and
the predicate did not implement it: **it mixed characters a credential CANNOT contain with
characters it CAN.** `+` and `,` are the second kind — `+` is in the standard base64
alphabet, so roughly half of all base64-shaped secrets carried their own exemption with
them. AWS's own published example secret key circulates in two variants differing by one
character, `/` against `+`; the gate caught one and waved the other through.

The narrowing keeps two disjuncts and deletes the rest: bracket structure, verified by a
stack scan rather than by character presence, and a `+` flanked by whitespace on both
sides. No credential format this project handles — base64, base64url, hex, JWT — admits a
bracket, and base64 `+` is never space-flanked. Both are outside the alphabet. Nothing
inside it is exempt any more.

**Seven is a design property, not luck.** The sequence: the numeric exemption, the
placeholder substring match, the angle-bracket value class, the suffix allow-list, the
shared `is_auth_param` predicate, the unqualified `key` narrowing, and now the expression
predicate. *Every guard in this repo that parses a value has eventually been bypassed
through the parsing.* A predicate over a value's characters is a small parser, and a small
parser written to admit the cases in front of its author will admit cases its author did
not think of. Expecting the next one to be different is the error.

**So the mitigation is not better predicates. It is that an exemption ships with an
adversarial test targeting its parser specifically, not its intent.** A test of intent
plants what the author already imagined; a test of the parser plants what the *predicate*
accepts and the author did not mean. The difference is measurable here: three tests came
within one character of the hole — a base64 case, an AWS case and a planted key — and all
three missed because no fixture happened to contain a `+`. Fixture choice was doing the
work the test was supposed to do.

Accepted gaps now ship as fixtures marked *intentional exemption* rather than living in
`docs/limits.md` alone. An accepted gap with a test is a decision; one recorded only in
prose is something the next person closes or widens without knowing it was deliberate.

#### Eight. The eighth was inside the fix for the seventh — 2026-08-29, review 7's F1

**This is the most useful entry in the sequence, and it is the one that cost the least to
find.** The narrowing above shipped with two fixtures marked *intentional exemption*, and
both were written from the exemption's **intent**: a literal split across an operator, a
credential carrying a nested bracket pair. Review 7 planted what the **parser** accepts and
found a third, smaller case neither covered — a single unmatched opener:

```
api_key: sk-live-9f8e7d6c5b4a3210fedc(
```

One appended character. `has_bracket_structure` returns with a non-empty stack on purpose,
so that `AUTH_PARAM_PATTERNS = (` — the first line of a multi-line tuple, a real value in
this repo — stays exempt. The consequence is that any credential with an opener stuck on
the end is exempt too. The predicate's acceptance set was wider than the suite and
`docs/limits.md` both described it.

**The rule was right and did not fire on its own author.** The commit immediately before
this one wrote the hard rule into `CLAUDE.md`: *an exemption ships with an adversarial test
targeting its parser, not its intent.* One commit later, the tests written to close the
seventh bypass were themselves tests of intent. Nothing about knowing the rule, having just
written it down, and applying it deliberately was sufficient — which is the strongest
available evidence that the mitigation has to be **an outside reader planting inputs**, not
the author's own care. This one was found by a reviewer looking for exactly the shape that
had just been named, one commit after it was named, in the code written to close it.

**Ruled accepted, not closed** — the human, 2026-08-29. Requiring depth to return to zero
closes the gap and breaks `AUTH_PARAM_PATTERNS = (`, so it needs a second carve-out: two
exemptions to defend instead of one. That reasoning was already on the record and still
holds. What changes is that the gap is now pinned at its true width — a third fixture in
`TestAcceptedExemptionGaps`, a third bullet in `docs/limits.md`, and this entry — rather
than being one character wider than either document said.

The cost of the ruling is verified rather than asserted: under `return seen and not stack`
the suite fails on exactly two cases, the new fixture and `AUTH_PARAM_PATTERNS = (`.
Captured in [`runs/secrets-gate/unmatched-opener-fail-first.txt`](../../runs/secrets-gate/unmatched-opener-fail-first.txt).

**The narrowed predicate, with this gap accepted, is approved as it stands.** Future ranges
containing it are not a methodology change to the enforced gate and are not grounds for a
halt on that basis.

*A correction to the record, and then a correction to the correction.* The commit that
added this exemption, `df63680`, reported that ungating raised **7** findings against the
repo. Re-measured 2026-08-29 at `874e808`, disabling the exemption raises **10**. That much
was already recorded here. Review 7's F3 then asked for the output behind the 10, on the
principle that a number written to correct another number should arrive with its evidence,
and capturing it changed two of the surrounding claims:

- **10 is confirmed**, at `874e808`, by disabling the exemption's disjunct and running the
  gate over every tracked file:
  [`runs/secrets-gate/ungated-scan-874e808.txt`](../../runs/secrets-gate/ungated-scan-874e808.txt).
- **7 does not reproduce.** The same method at `df63680` raises **9**:
  [`runs/secrets-gate/ungated-scan-df63680.txt`](../../runs/secrets-gate/ungated-scan-df63680.txt).
  The procedure behind the 7 was never written down and cannot be recovered, so the honest
  statement is that it does not reproduce — not that it was wrong.
- **The decomposition given here was wrong.** It said the three additions were `compute.tf`'s
  `ssh_authorized_keys` and two later lines, one of them `is_an_expression`'s own docstring.
  Measured, the move from 9 to 10 is *two additions and one removal*: `compute.tf:50` and
  `check_no_secrets.py:220` appear, and `allowlist.py:81` — the unqualified `key` — drops out
  because entry six of the sequence above narrowed the gate's key matching. The docstring
  lines were present at `df63680` and were never additions. **The count went up while one of
  its members was removed by a different exemption widening**, which is the part worth
  keeping.

Seven was correct-as-reported when written and is not the number to quote now; 10 is. The
count of *bypasses* above is a different sequence and is unaffected.

**Process note.** The narrowed predicate was stated to the human and approved before it was
written, rather than written and explained afterwards — the sequence CLAUDE.md rule 1 asks
for and the one ADR 0006 and ADR 0008 were both found not to have followed.

### 14. A wrapper reports the status of the wrong thing — twice now

A small pattern, recorded because it has now happened twice in this repo, in two different
languages, both times silently.

**First instance, Stage 0.** The probe test suite was run as `python -m unittest ... | tail -N`.
`tail`'s exit status is what a shell sees, and `tail` always exits 0 — so a failing test suite
still reported success to anything checking `$?`. The pipeline reported the status of the last
command in it, not the status of the command that mattered.

**Second instance, Gate 5, 2026-08-30.** `scripts/probe/run-awake.sh` disables sleep, runs the
wrapped command, then always runs a `restore` function on `trap ... EXIT` to put the machine's
power settings back. The wrapped command's exit code was never captured, so whatever the trap's
own last statement returned — a `powercfg` call, near-universally 0 — became the script's exit
status. A `python -m ingest.run ...` that died instantly on `ModuleNotFoundError` still reported
exit 0. Found because the Gate 5 run wrote no rows and the console log was checked by hand; nothing
automated caught it.

**The shape is identical both times: a wrapper whose own final action determines the reported
outcome, independent of whether the thing it wraps succeeded.** A pipe's last stage, a trap that
runs unconditionally on exit — either one silently substitutes its own status for the status that
was supposed to be reported. This is the same defect as the coverage check in §8's introduction —
a run reporting success while being 94% hole — one layer further out: there it was a *program*
that did not verify its own completion; here it is a *harness around* the program doing the same
thing to the program's exit code.

**The fix in both cases is to capture and re-raise explicitly**, rather than trust the last thing
that happened to run. In the second instance: `"$@"; STATUS=$?; ...; exit "$STATUS"`, with the
restore trap left in place for the side effect it exists for, but no longer trusted for the exit
code.

**Where to look for a third instance:** any wrapper whose job is "do something around a command" —
retry logic, a timing harness, a cleanup trap, a logging pipe — is a candidate, because the
wrapper's own control flow has an exit path of its own that can silently outrank the wrapped
command's.

## Consequences

- `header_timestamp_trust` and the dedup key both become tenant schema facts derived from measured
  evidence rather than assumption.
- `unknown` and `indeterminate` are expected outcomes, not failures. CH at 45s polling is likely to
  produce `unknown`, and that is the correct record.
- The probe is throwaway. None of this code is intended to survive into the ingest service; its
  numbers are.

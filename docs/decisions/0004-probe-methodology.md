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

Instances 4 and 5 are the same statement about different quantities, which is what made the pattern
visible: **sampling at or near the rate of the thing you are measuring destroys the information you
are trying to collect.** The analyser had been taught that for cadence and not for 304 rates, so it
made the identical mistake twice in two hours.

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

## Consequences

- `header_timestamp_trust` and the dedup key both become tenant schema facts derived from measured
  evidence rather than assumption.
- `unknown` and `indeterminate` are expected outcomes, not failures. CH at 45s polling is likely to
  produce `unknown`, and that is the correct record.
- The probe is throwaway. None of this code is intended to survive into the ingest service; its
  numbers are.

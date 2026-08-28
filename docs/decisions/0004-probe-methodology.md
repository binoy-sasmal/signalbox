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

### 8. Clock discipline

Wall clock anchored once; every interval from a monotonic base. NTP offset is **recorded, not
applied**, so the correction stays visible and reversible. A failed sync records `null` with a flag
and **never zero** — a silent zero is a fabricated measurement that would lend unearned precision to
every derived lag figure. HTTP `Date` provides an independent per-request reference.

### 9. No deliberate rate-limit provocation, on any feed

A 429 is recorded in full if it arrives, but we do not chase one. VBB is degraded, so provoking it
would perturb an upstream that is not behaving normally; CH holds a revocable key whose loss costs
the project a real capability. Section 6 of the plan originally called for approaching the documented
limit; that was dropped.

### 10. One endpoint is one feed id

Every timestamp test assumes one feed is one message stream. OVapi alone exposes four endpoints
(`tripUpdates`, `vehiclePositions`, `alerts`, `trainUpdates`) which may stamp differently. Two
config entries sharing an id would interleave two streams into a single verdict that looked
plausible and was meaningless. The poller rejects duplicate ids and non-string `base_url` at
startup.

### 11. Credential capture is structural

Headers by explicit allow-list, dropped at capture rather than redacted after. Endpoints stored
split into `base_url` plus a query map, never joined, because some transit APIs authenticate by
query parameter and a run manifest is not covered by a header allow-list. The check is a structural
assertion over every committed file and runs in CI as well as pre-commit, with an adversarial test
suite ahead of it — a gate that cannot fire and a gate with nothing to fire on look identical from
outside.

## Consequences

- `header_timestamp_trust` and the dedup key both become tenant schema facts derived from measured
  evidence rather than assumption.
- `unknown` and `indeterminate` are expected outcomes, not failures. CH at 45s polling is likely to
  produce `unknown`, and that is the correct record.
- The probe is throwaway. None of this code is intended to survive into the ingest service; its
  numbers are.

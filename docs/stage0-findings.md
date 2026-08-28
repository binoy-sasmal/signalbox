# Stage 0 findings

**What a week of measuring feeds bought, before a line of Terraform.**

Stage 0 probed five public transit realtime feeds to decide which could become tenants and how they
behave. It produced four results that outlive the probe itself — the probe is throwaway code, these
are not. Numbers and full evidence are in [`metrics.md`](metrics.md); method and reasoning are in
[ADR 0004](decisions/0004-probe-methodology.md).

**Outcome:** Gate 0 passed with three feeds — VBB, HSL trip updates, OVapi trip updates — each with
a measured cadence, characterised conditional-request behaviour, and a header-timestamp verdict.

---

## 1. A documented cadence is a hypothesis, and so is a short measurement

| Source | Documented | Measured |
|---|---|---|
| gtfs.de | 10s | **30s** — 3× off, stdev 2.0s over 119 intervals |
| HSL trip updates | 15s | **15.0s** — exact |
| VBB, by our own probe | — | **16s** from a 16-minute run, **29s** from a 60-minute run |

The claim is *not* "vendor documentation is wrong" — HSL's is precise. It is that documented cadence
is **unverified in either direction**, so you cannot tell the accurate sources from the inaccurate
ones without measuring.

The third row is the important one. **Our own instrument was off by nearly 2×**, for exactly the
reason gtfs.de's documentation is off: insufficient observation. A measurement is not automatically
better than a document; it is better when it has adequate duration behind it, and worse when it does
not.

**Why this mattered before Stage 1:** Gate 8 calibrates a `feed_freshness` SLO per tenant. A target
set from gtfs.de's documented 10s, against a feed regenerating every 30s, would have burned its error
budget continuously while nothing was broken — and the error runs in the direction that looks like a
system fault rather than a configuration one. We would have spent that debugging.

## 2. A measurement must declare its preconditions and stand down when they fail

**Silence from a structurally incapable test is not evidence of absence.**

Found five times, one at a time, before the common shape became visible:

| Measurement | Precondition | What it did when violated |
|---|---|---|
| Restamping detection | Content must actually change | Read near-static content as an echoed timestamp |
| Lag-shape test | Cadence ≥5 timestamp quanta; lag inside `[0, cadence]` | Cleared its threshold by **0.0009** |
| Re-poll test | Gap shorter than the cadence | False `echo` that **outvoted two correct tests** |
| Cadence | Sampling ≥2× cadence (Nyquist) | Reported our own sampling grid as a feed property |
| 304 rate | More than one poll per generation | Reported 0% from **77 observations** where a 304 was near-impossible |

The last two are the same statement about different quantities: **sampling at the rate of the thing
you are measuring destroys the information you are collecting.** The analyser had been taught that
for cadence and not for 304 rates, and made the identical mistake twice within two hours.

Three properties make this a principle rather than five patches. **Volume of evidence is no
defence** — 77 observations produced a confident, actionable, wrong conclusion, and a Gate 5 design
decision was drawn from it before the correction. **It is invisible in the output** — a test that
cannot fire and a test that fired and found nothing produce identical numbers. And **it survives
fixtures**, which is finding 3.

**Where it transfers:** Gate 8. An SLI computed over a window with too few samples has exactly this
problem, and a burn-rate alert over a window containing three requests is not a low error rate — it
is no measurement at all. Unlike a probe, it will be trusted by an on-call human at 3am. Every SLI
recording rule needs a minimum sample count and must report *no data* rather than a reassuring
number below it.

## 3. A fixture can only test the world it models

Two bugs passed synthetic tests and were caught only by live feeds, both because the synthetic
environment lacked the property that mattered:

- **Conditional requests.** The re-poll test compares two payloads. Synthetic responses have no
  notion of a 304, so the fixture passed; against real feeds both re-polls returned 304 and the test
  had nothing to compare. It was lost on two of three feeds before anyone noticed.
- **A network that can fail.** No fixture forced an NTP sync failure. A real one occurred mid-run and
  the null-not-zero rule held — a rule written from reasoning and confirmed by accident.

The counter-example matters for honesty: the static-content guard **was** correctly predicted by its
fixture, and a live feed then confirmed it. Fixtures are not useless. They are bounded by their
author's imagination, which is a different and more precise complaint.

## 4. A feed characterised and rejected is a result, not a gap

**gtfs.de was excluded as a tenant on measured resource grounds**, with the arithmetic written down:

- ~42 MB uncompressed per fetch — the only probed feed that does not gzip — against a measured 30s
  cadence. Tracking it costs **5–10 GB/hour**, continuous, from a sponsored volunteer service.
- 178,942 entities per snapshot, twice a minute, into one Postgres shared by every tenant on a 12 GB
  node.
- Slowing to 5-minute polling still costs ~363 GB/month **and** makes freshness meaningless against a
  30s upstream. Both properties fail together.
- Its licence is clean (CC BY-SA 4.0). The exclusion is purely about resources.

A documented rejection with numbers behind it is worth more than a feed that quietly never appeared.
It is also the first evidence that **feed size is an admission constraint** for this platform —
discovered by measurement rather than assumed, and now recorded in the honest-limits section of the
plan.

---

## What this cost, and why it was worth it

Roughly four hours of polling across four runs, about 2 GB of other people's bandwidth, and one run
voided when the machine slept for 56 of its 60 minutes — which is itself how the coverage check came
to exist, after a run reported `complete` with 6.3% coverage.

Against that: a tenant schema with the right fields, an SLI that is known to be meaningful for three
specific feeds and known *not* to be for a fourth, a rejected feed with arithmetic behind the
rejection, and a measurement principle that Gate 8 would otherwise have learned at the cost of an
alerting system nobody could trust.

None of that was derivable from documentation. Two of the four findings contradict it.

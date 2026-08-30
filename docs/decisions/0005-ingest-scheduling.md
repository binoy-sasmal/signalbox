# 0005 — Ingest poll scheduling: fixed-rate vs sleep-after-completion

**Status:** Accepted — 2026-08-30, at Gate 5, which is where the stub said to decide it.
**Date:** proposed 2026-08-29 (stub), decided 2026-08-30
**Related:** ADR 0004 (probe methodology, where the same choice was made implicitly and bit us),
ADR 0010 (backpressure, which depends on the achieved interval meaning what it says)

## Context

The Stage 0 probe sleeps a fixed interval *after* each request completes. That is a real scheduling
decision and it was made by default rather than on purpose, which is how it went unnoticed that the
achieved interval bears little relation to the configured one:

| Feed | Configured | Achieved | Cause |
|---|---|---|---|
| gtfs_de | 5s | **17.8s** | each 40 MB fetch took 12–27s |
| vbb | 5s | 5.12s | fetches are fast |
| ovapi_tripupdates | 60s | 62.0s | fetches are fast |

The consequence was not merely cosmetic. gtfs.de's cadence figure was computed against a 5s interval
we never achieved, and only a Nyquist check against the *measured* interval revealed the number was
our own sampling grid. **Gate 5's ingest service faces exactly the same choice**, with the same
failure mode available to it.

A second instance of the same defect surfaced on 2026-08-30, while designing Gate 5, and it is the
one that settles this ADR. HSL's 304 ceiling in `metrics.md` was computed from the **median**
inter-request gap of 5.17s. The mean is 6.15s. They differ because sleep-after-completion makes the
interval a function of the response: 304s return in 125 ms and 200s take 2.4 s, so the gap
distribution is bimodal and its median sits on the 304 mode. **Under sleep-after-completion the
sampling interval is not a number, it is a distribution shaped by the thing being sampled** — and
every claim computed from it inherits that.

## Options

### 1. Sleep after completion (what the probe does)

Self-limiting under upstream slowness: a slow feed automatically reduces our request rate, which is
polite and needs no explicit handling.

But the effective rate is emergent. A rate-limit budget, an SLO, or a bytes-saved figure stated in
terms of the configured interval is wrong whenever fetches are slow — and *how* wrong is not
constant, because the interval correlates with the response class.

### 2. Fixed-rate scheduling

The interval means what it says, which makes rate budgeting, Nyquist reasoning and freshness
arithmetic honest. Cost: an explicit decision for the case where a fetch outlasts the interval —
skip, queue, or overlap. Overlap breaks the single-flight property that keeps our request rate
bounded, and is rejected on that basis: two concurrent requests to a volunteer-run feed doubles our
instantaneous rate exactly when the feed is already struggling.

## Decision

**Fixed-rate, single-flight, skip missed ticks.**

Ticks fire on a fixed grid. If a fetch is still in flight when the next tick arrives, that tick is
**skipped and counted**, not queued and not overlapped. Both the configured and the achieved
interval are recorded, and every cadence, freshness or rate claim is judged against the achieved
one.

**The cost is measured, not hand-waved.** HSL's fetch durations from run 2: p50 2.39 s, p95 3.16 s,
**max 5.09 s**, against a 5 s tick. Two of 247 body-returning fetches exceeded 5 s and none exceeded
5.5 s, so skips will happen, they will be rare, and each loses exactly one tick. The predicted rate
is in `metrics.md` under the Gate 5 predictions, written before the run.

**Why skip rather than queue:** a queued tick fires immediately after the slow fetch returns, which
is a burst — the opposite of what a fixed rate is for — and it cannot catch up without exceeding the
rate ceiling. Skipping keeps the request rate bounded by construction, which is the property the
ceiling exists to guarantee.

## A rule that carries over from the probe regardless

**A request whose purpose is to obtain a body must not send conditional validators.**

This was found twice in Stage 0, in two different guises, and generalised the second time:

1. Test C compares two payloads. Sending validators made both re-polls return 304, and the test was
   lost on two of three feeds.
2. In HEAD mode, every HEAD refreshed the stored ETag, so the periodic full GET — issued purely to
   obtain a payload — was guaranteed a 304.

The ingest service will have the same shape of request: ordinary polls that *should* be conditional
because a 304 is a cheap "nothing changed", and backfill or re-read requests that exist to obtain
content and must not be. Conditional requests are an optimisation for the first kind and a defect
for the second.

**At Gate 5 there is exactly one request class** — ordinary polls, all conditional — so the rule has
nothing to do yet. It binds as a constraint on what may be added: **no backfill or re-read path
exists, and one added later must not send validators.**

## Consequences

- The achieved interval is exported as a metric and written into the run report. It is never
  inferred from configuration. That much was settled by measurement before this ADR was written.
- Skipped ticks are counted. A skip rate far above the predicted one means fetch latency changed,
  which is worth knowing on its own.
- The rate ceiling is bounded by construction: at most one request in flight, at most one per tick.
- **`metrics.md`'s HSL ceiling figure was computed under the other regime** and is corrected there
  (2026-08-30). Under fixed-rate the interval is a single number and the ambiguity does not recur.

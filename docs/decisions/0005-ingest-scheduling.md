# 0005 — Ingest poll scheduling: fixed-rate vs sleep-after-completion

**Status:** Proposed — stub. **Do not decide this before Gate 5.** Recorded now because Stage 0
measured the consequence and the evidence would otherwise be lost.
**Related:** ADR 0004 (probe methodology, where the same choice was made implicitly and bit us)

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

## Options, not yet weighed

- **Sleep after completion** (what the probe does). Self-limiting under upstream slowness: a slow
  feed automatically reduces our request rate. But the effective rate is emergent, so an SLO or a
  rate-limit budget stated in terms of the configured interval is wrong whenever fetches are slow.
- **Fixed-rate scheduling.** The interval means what it says, which makes rate budgeting and
  freshness reasoning honest. But it needs explicit handling for the case where a fetch outlasts the
  interval — skip, queue, or overlap — and overlap breaks the single-flight property that keeps our
  request rate bounded.

Whatever is chosen, **the achieved interval must be exported as a metric**, not inferred from
configuration. That much is settled by measurement already.

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
for the second. Carry the distinction into the ingest poller's design rather than rediscovering it a
third time.

## Consequences

- Gate 5 must state its scheduling choice explicitly and justify it, rather than inheriting the
  probe's by accident.
- Whichever is chosen, configured and achieved intervals are both recorded, and any cadence,
  freshness or rate-budget claim is judged against the achieved one.

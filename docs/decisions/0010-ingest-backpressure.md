# 0010 — Ingest backpressure: what happens when the queue fills

**Status:** Accepted — 2026-08-30, at Gate 5
**Date:** 2026-08-30
**Related:** ADR 0005 (scheduling), ADR 0009 (storage model), ADR 0002 (the SLIs this feeds)

## Context

PLAN section 7 requires an explicit decision here and says each option is defensible while silence
is not. The bounded queue sits between the poller and the writer: the poller puts a fetched body on
it, the writer decodes, dedups and persists.

## Options

| Option | What it costs on this feed |
|---|---|
| **Block** | The poller stalls waiting for the writer. The achieved interval stretches, and ADR 0005's exact failure returns: a rate budget and a cadence claim stated against an interval we no longer achieve. Lag grows with no bound and nothing reports it. |
| **Drop newest** | Discards the freshest snapshot to preserve a superseded one. On a `FULL_DATASET` feed this maximises staleness — strictly the wrong direction. |
| **Drop oldest** | Discards a snapshot that the newer one entirely supersedes. Loss is bounded and semantically near-free. |

## Decision

**Drop oldest. Queue depth 2. Every drop is counted, and counts as a pipeline failure.**

### Why depth 2, stated plainly

For a `FULL_DATASET` feed feeding a current-state table, **drop-oldest at depth 2 is a
latest-value register with a counter on it**, and that is the correct structure for this workload.
A deeper queue only buys the right to eventually write staler data. The queue exists rather than a
plain slot because PLAN asks for a bounded queue and because the drop counter is the observable;
this ADR is not going to claim depth 8 would be better.

### The dependency that makes it correct, and that must not be inherited silently

**Drop-oldest is safe only because `incrementality` is `FULL_DATASET`** — measured at Stage 0 on
all four probed feeds, not assumed. Each snapshot fully supersedes its predecessor, so a dropped
snapshot loses nothing that the next one does not carry.

For a `DIFFERENTIAL` producer this is **wrong**: a dropped message loses state permanently and
unrecoverably. So the policy is gated on the tenant file's `incrementality` field, and a tenant
declaring `DIFFERENTIAL` must fail at startup rather than inherit a policy chosen for a different
feed shape. The check is in code, not in a comment.

### Drops are failures, not silent successes

**A drop policy that is not counted launders errors out of the error budget.** If a dropped
snapshot is invisible, the fastest route to a green `ingest_pipeline_success_rate` at Gate 8 is a
more aggressive drop policy — the SLO would reward exactly the behaviour it exists to detect.

So: every drop increments a counter, is logged, and is classified as a **failure** for SLI 1. This
is written down at Gate 5, three gates before the SLI exists, because it is not a property that can
be added afterwards to data already collected.

### Expected drops at Gate 5: zero

A fetch takes 2.4 s and the writer handles about 1,261 entities. Nothing in the measured numbers
suggests the queue can fill with one feed at a 5 s interval. **A non-zero drop count in the
verification run is therefore itself a finding**, not a tolerance to be absorbed.

## The test, and why the policy alone is not enough

Expected drops are zero, so **the verification run will not exercise the drop path at all**. A rule
that ships unexercised into Gate 8 — where it decides whether an error budget is honest — is a rule
nobody has ever seen work.

**An adversarial test forces the drop and asserts it is counted as a failure:** a writer that
blocks, a queue filled past its depth, and assertions on the counter, the classification and *which*
item survived. The test drives the queue's own accounting, not a narrative about it.

This is the repo's standing method, recorded at review log row 5: a fix is verified by making it
fail, not by watching it pass, because a test that only ever passes and a test that cannot fail look
identical from outside.

## Consequences

- The queue's drop counter is in the run report and, at Gate 7, becomes a metric labelled by tenant
  and reason — never by entity id, per the cardinality rule.
- `incrementality` earns its place in the tenant schema by gating this decision. It is the one of
  PLAN section 4's six fields that the Gate 5 service actually reads.
- The staleness bound is explicit: at depth 2 with a 5 s interval, a snapshot is dropped only if the
  writer is more than roughly two ticks behind, and what is lost is at most one superseded snapshot.
- Blocking remains the right answer for a feed where every message is needed. That is not this feed,
  and the condition under which the answer changes is written down above rather than left implicit.

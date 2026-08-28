# 0002 — Split the lag SLI into pipeline_latency and feed_freshness

**Status:** Accepted
**Date:** 2026-08-28
**Related:** ADR 0001 (creates the provisioning window excluded below)

## Context

The plan originally specified a single end-to-end lag SLI: `FeedHeader.timestamp` → row committed,
budgeted, with an "upstream-outage exclusion". Two problems, either of which would end an SLO
conversation badly.

**It is partly self-referential.** If we poll every N seconds, measured lag is roughly uniform on
[0, N] plus processing time — before any upstream or pipeline behaviour enters the number at all.
The SLI therefore mostly measures our own configuration, and the SLO can be "improved" by
tightening the poll interval. That is a knob, not an achievement, and an interviewer will find it.

**The exclusion was unfalsifiable.** "Budgeted with an upstream-outage exclusion" did not say what
counts as an outage, who declares one, or how it is applied. An exclusion a human can invoke by
hand reads as "we exclude the periods where we did badly".

A third issue, which the split resolves incidentally: the original SLI mixed two fault domains —
ours and the upstream's — into one budgeted number, so a burn alert could not tell you which one
was at fault.

## Decision

Split it in two, named for what each actually measures.

### `pipeline_latency` — fetch-completion → row committed

Our fault domain, and it **carries the error budget**. The poll interval cannot influence it, since
both endpoints are events in our own process. Both endpoints are also on the same clock, so it
carries no clock-skew uncertainty whatsoever.

This is the SLI that should drive paging, because it is the one we can act on.

### `feed_freshness` — `FeedHeader.timestamp` → row committed

Shared fault domain. **The poll interval is a stated parameter of the SLO definition**, written
into the SLO document rather than left as an implicit input. Changing the poll interval means
restating the SLO — which is exactly the point: the dependency becomes visible instead of being a
lever.

Applies **only** to tenants whose `header_timestamp_trust` is `generation`, as determined by the
Stage 0 probe. Tenants marked `echo` or `unknown` are excluded from this SLO entirely, because for
them the number would measure our poll offset plus RTT and nothing else.

### Exclusion predicate

Replace the hand-declared outage exclusion with a mechanical one: **exclude windows where upstream
availability is zero for the whole window**, implemented as a recording rule. No human declares an
outage; nobody can invoke it selectively.

### Provisioning-window exclusion

ADR 0001 makes a newly onboarded tenant sit not-ready while its cloud-side resources are applied by
CI. **A tenant correctly waiting for its own provisioning is not a pipeline failure and must not burn
the ingest error budget.** Without this exclusion, every successful onboarding would show up as a
self-inflicted SLO violation — which would make the onboarding metric and the reliability metric
fight each other.

Mechanical, in keeping with the rule above — no hand-declared windows. A
`signalbox_tenant_provisioning` gauge reads 1 while the tenant's readiness gate is unsatisfied **and**
the tenant is younger than a bounded provisioning deadline. Recording rules exclude windows where it
is 1, for SLIs 1 and 2, for that tenant only.

**The bound is the point.** Past the deadline the gauge drops to 0 and the tenant starts burning
budget normally, because a tenant that never finishes provisioning genuinely is a failure. An
unbounded exclusion would let a permanently broken onboarding hide indefinitely, which is the same
unfalsifiability this ADR exists to remove.

### Unchanged

Ingest pipeline success rate stays our fault domain and keeps carrying the error budget alongside
`pipeline_latency`. Upstream availability stays measured, dashboarded, and **never budgeted**.

## Consequences

- Four SLIs instead of three. The error budget lives entirely in our own fault domain, which is
  what an error budget is for.
- The clock-skew caveat now attaches to `feed_freshness` alone. `pipeline_latency` is clean. The
  node's NTP offset is exported as a metric so the remaining caveat carries a number rather than
  being a disclaimer.
- **The predicate cannot distinguish "upstream is down" from "our own egress is broken."** A window
  where we broke our own networking is excluded from `feed_freshness` as though the upstream had
  failed. Accepted: `pipeline_latency` and ingest success rate still carry the budget and still
  catch that fault, so nothing hides.
- **Partial upstream degradation is not excluded.** An upstream at a 50% error rate burns freshness
  budget. Accepted, and arguably correct — a degraded upstream genuinely does produce stale data,
  and pretending otherwise would be the same dishonesty in the other direction.
- Stage 0 must produce a `header_timestamp_trust` verdict per feed, because `feed_freshness` cannot
  be applied without one. This is now a first-class tenant schema field (PLAN.md section 4).
- SLO targets stay provisional until two weeks of real data exist. Unchanged from the original
  plan, and the split does not license inventing targets any earlier.
- **The provisional target comes from measured cadence, never from the provider's documentation.**
  Stage 0 found gtfs.de documenting 10-second updates and delivering ~30 — wrong by 3×, in the
  direction that would have burned freshness budget continuously while nothing was broken. See
  "Documented cadence is unverified in either direction" in `docs/metrics.md`. This binds every
  tenant, not only the one that produced it: cadence is measured at onboarding, cheaply, by HEAD
  against `Last-Modified`, and the measured figure is what `feed_freshness` is calibrated to. A
  documented cadence is a hypothesis, and a cheap one to test.
- **A cadence measured over a short window is provisional too.** Stage 0 measured VBB at 16s from
  16 minutes and at 29s from a full hour — our own instrument was off by nearly 2× for exactly the
  reason gtfs.de's documentation was: insufficient observation. HSL, meanwhile, matched its
  documented 15s precisely. The rule is therefore not "trust measurement over documentation" but
  **"a cadence figure is only as good as the duration behind it"**, whoever produced it. Any figure
  an SLO is calibrated to is re-derived over a full window first. See the three-way finding in
  `docs/metrics.md`.

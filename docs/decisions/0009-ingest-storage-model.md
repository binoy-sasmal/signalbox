# 0009 — Ingest storage model and dedup key

**Status:** Accepted — 2026-08-30, at Gate 5
**Date:** 2026-08-30
**Related:** ADR 0003 (who owns Postgres objects), ADR 0002 (the SLI split, which reads this
schema at Gate 8), ADR 0010 (backpressure)

> **Numbering.** There is no ADR 0009 gap and no missing document. The reordering of Gate 5
> ahead of Gate 2 was considered as an ADR and deliberately recorded in `docs/status.md`
> instead, because it is a statement about position rather than a technical decision with
> options and consequences. This file took the next free number.

## Context

Gate 5 persists one feed to Postgres. Three things have to be decided together, because each
constrains the others: **what a duplicate is**, **what a row is**, and **who creates the schema**.

The third is the one that can go quietly wrong. ADR 0003 settles that Postgres schemas and roles
are owned by ArgoCD through an operator with declarative CRDs, precisely so that no component
becomes a third reconciler with no drift detection. A service that creates its own schema on
startup is exactly that component.

## Decision 1 — the dedup key is the semantic key, and the change predicate is the probe's

**Key:** `(trip_id, start_date)` for a TripUpdate.
**Changed:** `sha256` of the entity serialized with `FeedEntity.id` cleared.

**This is character-for-character the definition the Stage 0 analyser used** — `entity_payload()`
and `entity_semantic_key()` in `scripts/probe/analyse.py`. That is the point of choosing it.

Stage 0 measured HSL's median semantic churn at **0.250**. Reusing the identical key and predicate
turns that into a **prediction the gate can falsify**: the service should suppress about **75%** of
entity writes. A design with its own predicate inherits no number and can only report whatever it
happens to do.

**Why not `entity.id`, which measured stable.** The premise this decision was first put under —
that `entity.id` is unstable and the semantic key differed — is the opposite of what Stage 0 found.
`entity.id` is stable on all four probed feeds (persistence ratio 0.9925 on HSL, 0.95–1.00
elsewhere) and the analyser's own finding string says it *is* usable as a dedup key here. Two
weaker reasons still favour the semantic key:

1. **Churn keyed on `entity.id` is 0.288 against 0.250 semantic** — about 15% more writes for no
   benefit.
2. **`FeedEntity.id` is scoped to uniqueness within one `FeedMessage`** by the specification. Its
   stability is a property of this producer today, guaranteed by nothing. The semantic key is
   guaranteed by the data model.

Both keyings are counted at runtime so the disagreement stays visible rather than becoming an
assumption.

## Decision 2 — "duplicate rate" is two numbers, never one

| Level | Key | What it detects | Stage 0 value |
|---|---|---|---|
| Snapshot | `sha256(body)` | A 200 whose body is byte-identical to its predecessor — a false-200 | 3 / 247 ≈ 1.2% |
| Entity | `(semantic key, content hash)` | An entity unchanged since the last snapshot | ≈ 75% suppressed |

Collapsing them into one figure would hide which is which. They have different causes, different
magnitudes and different consequences: the first is upstream behaviour, the second is our write
load.

## Decision 3 — schema shape

Objects live in a **named schema taken from configuration**, never `public`, so that PLAN section
9's "schema per tenant, per-tenant DB roles" is honoured from the first tenant rather than
retrofitted.

```
fetch                       -- one row per HTTP request, the provenance record
  id, requested_at, responded_at, status, conditional_mode,
  etag, last_modified, body_sha256, body_bytes,
  header_timestamp, decode_status, entity_count,
  entities_written, entities_suppressed, error

trip_update                 -- current state, upserted on change
  (trip_id, start_date)     PRIMARY KEY
  route_id, schedule_relationship, entity_timestamp,
  stop_time_update_count, content_hash, entity_bytes,
  first_seen_fetch_id, last_seen_fetch_id, updated_at
```

Three deliberate non-goals, each with a reason rather than an omission:

- **No stop-level table.** Exploding 1,261 trip updates into roughly 25,000 stop-time rows every
  15 s would dominate every number this gate measures. `entity_bytes` keeps the faithful record, so
  exploding later needs no re-fetch. Gate 5's claim is that the pipeline works, not that the query
  model is finished.
- **No history or versioning table.** Current state plus the `fetch` log. Adding history later is
  purely additive; carrying it now multiplies storage for nothing Gate 5 verifies.
- **No retention policy.** One hour of one feed. A retention decision with no data behind it would
  be a guess, and PLAN puts retention at Gate 7 where there are numbers.

**`fetch` is the one table built for a later gate, deliberately.** ADR 0002's `pipeline_latency` is
fetch-completion → row committed, and both endpoints live in this table. The alternative is
re-instrumenting the write path at Gate 8.

## Decision 4 — the service never creates its own schema

DDL lives in `services/ingest/sql/` as plain SQL and is applied by an **explicit, idempotent
command**. It is never run at service startup, and the service fails loudly against a missing
schema rather than helpfully creating one.

This is the decision that keeps ADR 0003 intact. A service that self-migrates converges its own
schema on every boot, which is a second reconciler over objects ADR 0003 assigns to ArgoCD.
Applied this way, Stage 2 substituting operator-managed schema and role creation is a swap, not a
conflict.

**ADR 0003 is not a prerequisite for this ADR**, and the reason is worth stating rather than
assuming: Gate 5 has no cluster and no operator, and its Postgres is a development dependency in
Docker. Waiting on ADR 0003's outstanding verification item — whether CloudNativePG's CRD surface
reaches schema granularity — would block ready work on a Stage 2 question.

## Consequences

- The 75% suppression figure is a falsifiable prediction, recorded in `metrics.md` before the run
  with its Stage 0 provenance, and the observed value is recorded alongside it. **Neither replaces
  the other.**
- Storing `entity_bytes` means the database holds protobuf, not columns. Accepted: it is the
  faithful record and it defers a query-model decision that has no requirement behind it yet.
- Stage 2 must provide the schema through the operator before a second tenant exists. Until then
  the explicit command is the only path, and it is a documented manual step, not a hidden one.
- If a later feed is `DIFFERENTIAL`, the current-state table is wrong for it — see ADR 0010, which
  makes the same dependency explicit for backpressure.

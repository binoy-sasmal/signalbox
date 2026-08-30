-- Gate 5 schema, one tenant. ADR 0009.
--
-- Applied by an EXPLICIT command (`python -m ingest.migrate`), never by the
-- service at startup. A service that converges its own schema on every boot is
-- a second reconciler over objects ADR 0003 assigns to ArgoCD. Stage 2 replaces
-- this file with operator-managed CRDs; that must be a swap, not a conflict.
--
-- {schema} is substituted from the tenant file's db_schema. It is validated
-- against ^[a-z][a-z0-9_]*$ before it reaches this file -- see migrate.py.

CREATE SCHEMA IF NOT EXISTS {schema};

-- One row per HTTP request. The provenance record, and the source of Gate 8's
-- pipeline_latency (ADR 0002): both endpoints of that SLI are columns here.
CREATE TABLE IF NOT EXISTS {schema}.fetch (
    id                  bigserial PRIMARY KEY,
    requested_at        timestamptz NOT NULL,
    responded_at        timestamptz,
    committed_at        timestamptz,
    status              integer,
    conditional_mode    text        NOT NULL,
    etag                text,
    last_modified       text,
    body_sha256         text,
    body_bytes          integer,
    header_timestamp    bigint,
    decode_status       text,
    entity_count        integer,
    entities_written    integer,
    entities_suppressed integer,
    outcome             text        NOT NULL,
    error               text
);

CREATE INDEX IF NOT EXISTS fetch_requested_at_idx
    ON {schema}.fetch (requested_at);

-- Current state, upserted on change. No history table and no stop-level
-- explosion; both are deliberate non-goals with reasons in ADR 0009.
CREATE TABLE IF NOT EXISTS {schema}.trip_update (
    -- The canonical TripDescriptor identity. NOT (trip_id, start_date): HSL
    -- publishes no trip_id at all, and that key maps a whole snapshot onto one
    -- row per start_date. `key_form` records which of GTFS-RT's two trip
    -- identification forms produced this row, so the choice is visible in the
    -- data rather than only in the code that wrote it.
    trip_key               text        PRIMARY KEY,
    key_form               text        NOT NULL,

    trip_id                text,
    route_id               text,
    direction_id           integer,
    start_date             text,
    start_time             text,

    schedule_relationship  text,
    entity_timestamp       bigint,
    stop_time_update_count integer     NOT NULL,
    content_hash           bytea       NOT NULL,
    entity_bytes           bytea       NOT NULL,
    first_seen_fetch_id    bigint      NOT NULL,
    -- "changed", not "seen". An unchanged entity is deliberately not written at
    -- all -- that is the dedup -- so this column cannot mean last-seen without
    -- writing every row every snapshot, which is the cost dedup exists to avoid.
    last_changed_fetch_id  bigint      NOT NULL,
    updated_at             timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS trip_update_last_changed_idx
    ON {schema}.trip_update (last_changed_fetch_id);

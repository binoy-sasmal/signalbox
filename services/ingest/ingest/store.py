"""Postgres writes. ADR 0009.

The service never creates its own schema (ADR 0009 decision 4). It fails loudly
against a missing one rather than helpfully creating it, because a service that
converges its own schema on every boot is a second reconciler over objects ADR
0003 assigns to ArgoCD.
"""
from __future__ import annotations

import datetime

import psycopg

from .decode import assert_key_is_a_key, content_hash, entity_payload, semantic_key, trip_key


class SchemaMissing(RuntimeError):
    pass


class Store:
    def __init__(self, dsn: str, schema: str) -> None:
        self.schema = schema
        self.conn = psycopg.connect(dsn, autocommit=False)
        self._assert_schema()

    def _assert_schema(self) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT to_regclass(%s), to_regclass(%s)",
                (f"{self.schema}.fetch", f"{self.schema}.trip_update"),
            )
            fetch_table, trip_table = cur.fetchone()
        self.conn.rollback()
        if fetch_table is None or trip_table is None:
            raise SchemaMissing(
                f"schema {self.schema!r} is not present or incomplete. Apply it with "
                "`python -m ingest.migrate <tenant file>`. This service does not create "
                "its own schema -- ADR 0009 decision 4."
            )

    def record_fetch(self, record: dict) -> int:
        """Insert the provenance row and return its id."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self.schema}.fetch (
                    requested_at, responded_at, status, conditional_mode, etag,
                    last_modified, body_sha256, body_bytes, outcome, error
                ) VALUES (
                    %(requested_at)s, %(responded_at)s, %(status)s, %(conditional_mode)s,
                    %(etag)s, %(last_modified)s, %(body_sha256)s, %(body_bytes)s,
                    %(outcome)s, %(error)s
                ) RETURNING id
                """,
                record,
            )
            fetch_id = cur.fetchone()[0]
        self.conn.commit()
        return fetch_id

    def persist_entities(self, fetch_id: int, entities, now=None) -> dict:
        """Upsert changed entities and return counts plus this snapshot's key maps.

        The returned maps are what ChurnTracker compares against the previous
        snapshot. They are built here because the id-cleared payload is already
        computed for the write, and hashing every entity a second time to keep the
        two concerns apart would cost more than it clarifies.
        """
        now = now or datetime.datetime.now(datetime.timezone.utc)
        rows = []
        by_semantic: dict[tuple, bytes] = {}
        by_entity_id: dict[str, bytes] = {}
        entities_without_identity = 0

        keyable = 0
        for entity in entities:
            key = semantic_key(entity)
            if key is None or key[0] != "trip_update":
                entities_without_identity += 1
                continue
            keyable += 1
            payload = entity_payload(entity)
            digest = content_hash(payload)
            by_semantic[key] = digest
            # Same population under both keyings, so an unkeyable entity cannot
            # skew the comparison -- the analyser's by_id_comparable rule.
            by_entity_id[entity.id] = digest

            update = entity.trip_update
            trip = update.trip
            canonical, key_form = trip_key(trip)
            rows.append((
                canonical,
                key_form,
                trip.trip_id or None,
                trip.route_id or None,
                trip.direction_id if trip.HasField("direction_id") else None,
                trip.start_date or None,
                trip.start_time or None,
                _schedule_relationship(trip),
                update.timestamp or None,
                len(update.stop_time_update),
                digest,
                payload,
                fetch_id,
                fetch_id,
                now,
            ))

        # A collapsed key still yields a suppression rate, a churn figure and a
        # full table, all wrong and none obviously so. Refuse instead.
        assert_key_is_a_key(len(by_semantic), keyable)

        written = 0
        if rows:
            with self.conn.cursor() as cur:
                # The WHERE clause IS the dedup. An entity whose content hash is
                # unchanged is not written at all, which is why the column is
                # named last_changed_fetch_id rather than last_seen.
                cur.executemany(
                    f"""
                    INSERT INTO {self.schema}.trip_update (
                        trip_key, key_form, trip_id, route_id, direction_id,
                        start_date, start_time, schedule_relationship,
                        entity_timestamp, stop_time_update_count, content_hash,
                        entity_bytes, first_seen_fetch_id, last_changed_fetch_id, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (trip_key) DO UPDATE SET
                        schedule_relationship  = EXCLUDED.schedule_relationship,
                        entity_timestamp       = EXCLUDED.entity_timestamp,
                        stop_time_update_count = EXCLUDED.stop_time_update_count,
                        content_hash           = EXCLUDED.content_hash,
                        entity_bytes           = EXCLUDED.entity_bytes,
                        last_changed_fetch_id  = EXCLUDED.last_changed_fetch_id,
                        updated_at             = EXCLUDED.updated_at
                    WHERE {self.schema}.trip_update.content_hash
                          IS DISTINCT FROM EXCLUDED.content_hash
                    """,
                    rows,
                )
                # Rows carrying this fetch id are exactly those inserted or
                # updated: an unchanged row was not touched, so its
                # last_changed_fetch_id still names an earlier fetch.
                cur.execute(
                    f"SELECT count(*) FROM {self.schema}.trip_update "
                    f"WHERE last_changed_fetch_id = %s",
                    (fetch_id,),
                )
                written = cur.fetchone()[0]
            self.conn.commit()

        return {
            "presented": len(rows),
            "written": written,
            "suppressed": len(rows) - written,
            "entities_without_identity": entities_without_identity,
            "by_semantic": by_semantic,
            "by_entity_id": by_entity_id,
        }

    def finalise_fetch(self, fetch_id: int, **fields) -> None:
        assignments = ", ".join(f"{name} = %({name})s" for name in fields)
        with self.conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self.schema}.fetch SET {assignments} WHERE id = %(fetch_id)s",
                {**fields, "fetch_id": fetch_id},
            )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def _schedule_relationship(trip) -> str | None:
    if not trip.HasField("schedule_relationship"):
        return None
    enum_type = trip.DESCRIPTOR.fields_by_name["schedule_relationship"].enum_type
    return enum_type.values_by_number[trip.schedule_relationship].name

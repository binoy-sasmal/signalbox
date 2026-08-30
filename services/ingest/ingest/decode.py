"""Protobuf decode, semantic key, and the change predicate. ADR 0009.

`semantic_key` and `entity_payload` are character-for-character the definitions the
Stage 0 analyser used (scripts/probe/analyse.py). That is deliberate and it is the
point: Stage 0 measured HSL's median semantic churn at 0.250 under exactly these
definitions, so reusing them turns 75% suppression into a prediction this service
can falsify. A different predicate would inherit no number at all.
"""
from __future__ import annotations

import hashlib

from google.transit import gtfs_realtime_pb2

#: Leading bytes of an HTML document, in the two cases seen in the wild. A feed
#: returning an error page is a different and worse failure than a truncated body,
#: and the rate alone hides that (PLAN.md section 6.3).
_HTML_PREFIXES = (b"<!DOCTYPE", b"<!doctype", b"<html", b"<HTML")


class DecodeResult:
    __slots__ = ("status", "message", "entities", "header_timestamp", "detail")

    def __init__(self, status, message=None, entities=None, header_timestamp=None, detail=None):
        self.status = status
        self.message = message
        self.entities = entities or []
        self.header_timestamp = header_timestamp
        self.detail = detail


class KeyCollapsed(RuntimeError):
    """The dedup key is not a key on this feed. Raised rather than worked around."""


def trip_key(trip) -> tuple[str, str]:
    """Canonical identity of a TripDescriptor, and which form produced it.

    GTFS-RT permits two ways to identify a trip, and this feed uses the second:

      1. `trip_id`, with `start_date` disambiguating repeats across days.
      2. `route_id` + `direction_id` + `start_date` + `start_time`, for producers
         that do not expose trip ids.

    **HSL uses form 2 exclusively: 0 of 1,348 entities carry a trip_id.** Keying on
    `(trip_id, start_date)` collapses a whole snapshot into one key per start_date
    -- four keys for 1,348 entities. Under form 2 the key is exactly 1:1 with
    entities, with zero collisions across every Stage 0 snapshot checked.

    Returning the form alongside the key keeps that visible in the stored data
    rather than only in this comment.
    """
    if trip.trip_id:
        return f"trip:{trip.trip_id}@{trip.start_date}", "trip_id"
    return (
        f"route:{trip.route_id}/{trip.direction_id}@{trip.start_date}T{trip.start_time}",
        "route_start",
    )


def semantic_key(entity) -> tuple | None:
    """Semantic identity of an entity, independent of FeedEntity.id.

    FeedEntity.id is scoped to uniqueness *within a FeedMessage*. Stage 0 measured
    it stable on all four probed feeds, but that is a property of those producers
    rather than a guarantee; the semantic key is guaranteed by the data model.
    """
    if entity.HasField("trip_update"):
        return ("trip_update", trip_key(entity.trip_update.trip)[0])
    if entity.HasField("vehicle"):
        return ("vehicle", entity.vehicle.vehicle.id)
    return None


def assert_key_is_a_key(distinct_keys: int, keyable_entities: int,
                        tolerance: float = 0.99) -> None:
    """A dedup key that collapses the population is not a key.

    Stage 0's transferable principle is that a measurement must declare its
    preconditions and stand down when they fail, because a test that cannot fire
    and a test that fired and found nothing produce identical numbers. A dedup key
    has exactly that shape: a collapsed key still yields a suppression rate, a
    churn figure and a full table, all of them wrong and none of them obviously so.

    This is the check that would have caught the original key immediately -- it
    mapped 1,348 entities onto 4 keys and reported 99.5% suppression.
    """
    if keyable_entities == 0:
        return
    ratio = distinct_keys / keyable_entities
    if ratio < tolerance:
        raise KeyCollapsed(
            f"dedup key is not unique: {distinct_keys} distinct keys for "
            f"{keyable_entities} keyable entities (ratio {ratio:.4f}, "
            f"minimum {tolerance}). Suppression and churn computed on this key "
            "would be artefacts of the collapse."
        )


def entity_payload(entity) -> bytes:
    """Entity bytes with id cleared -- the change predicate's input.

    Normalised to a constant rather than cleared: FeedEntity.id is a proto2
    required field, so clearing it makes the message unserialisable.
    """
    copy = gtfs_realtime_pb2.FeedEntity()
    copy.CopyFrom(entity)
    copy.id = ""
    return copy.SerializeToString(deterministic=True)


def content_hash(payload: bytes) -> bytes:
    return hashlib.sha256(payload).digest()


def decode(body: bytes) -> DecodeResult:
    """Classify and decode one response body.

    Failure classes are distinguished rather than collapsed into a rate, because
    a feed returning HTML 0.5% of the time is a different problem from one
    returning truncated bodies at the same rate.
    """
    if not body:
        return DecodeResult("empty_body")
    if body[:9] in _HTML_PREFIXES or body[:5] in _HTML_PREFIXES:
        return DecodeResult("not_protobuf", detail="body begins as HTML")

    message = gtfs_realtime_pb2.FeedMessage()
    try:
        message.ParseFromString(body)
    except Exception as exc:  # protobuf raises DecodeError and friends
        return DecodeResult("parse_error", detail=f"{type(exc).__name__}: {exc}")

    if not message.HasField("header"):
        return DecodeResult("wrong_schema", detail="no FeedHeader")

    if not message.entity:
        return DecodeResult(
            "valid_but_empty",
            message=message,
            header_timestamp=message.header.timestamp or None,
        )

    return DecodeResult(
        "ok",
        message=message,
        entities=list(message.entity),
        header_timestamp=message.header.timestamp or None,
    )

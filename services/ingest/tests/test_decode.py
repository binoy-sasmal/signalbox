"""Decode classification, the dedup key, and the guard that the key is a key."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google.transit import gtfs_realtime_pb2  # noqa: E402

from ingest.churn import churn  # noqa: E402
from ingest.decode import (  # noqa: E402
    KeyCollapsed,
    assert_key_is_a_key,
    content_hash,
    decode,
    entity_payload,
    semantic_key,
    trip_key,
)


def build(entities, timestamp=1_800_000_000):
    message = gtfs_realtime_pb2.FeedMessage()
    message.header.gtfs_realtime_version = "2.0"
    message.header.timestamp = timestamp
    for spec in entities:
        entity = message.entity.add()
        entity.id = spec["id"]
        trip = entity.trip_update.trip
        for field in ("trip_id", "route_id", "start_date", "start_time"):
            if spec.get(field):
                setattr(trip, field, spec[field])
        if "direction_id" in spec:
            trip.direction_id = spec["direction_id"]
        if "delay" in spec:
            stop = entity.trip_update.stop_time_update.add()
            stop.stop_sequence = 1
            stop.arrival.delay = spec["delay"]
    return message


HSL_SHAPED = [
    {"id": "7990512198312769", "route_id": "31M2", "direction_id": 1,
     "start_date": "20260828", "start_time": "17:55:00"},
    {"id": "7990512196968657", "route_id": "31M1", "direction_id": 1,
     "start_date": "20260828", "start_time": "17:30:00"},
    {"id": "7990512196972892", "route_id": "31M1", "direction_id": 0,
     "start_date": "20260828", "start_time": "17:33:00"},
]


class TripKeyTest(unittest.TestCase):

    def test_uses_trip_id_when_the_producer_supplies_one(self):
        message = build([{"id": "e1", "trip_id": "T7", "start_date": "20260828"}])
        key, form = trip_key(message.entity[0].trip_update.trip)
        self.assertEqual(form, "trip_id")
        self.assertIn("T7", key)

    def test_falls_back_to_route_and_start_when_there_is_no_trip_id(self):
        message = build(HSL_SHAPED)
        for entity in message.entity:
            _, form = trip_key(entity.trip_update.trip)
            self.assertEqual(form, "route_start")

    def test_hsl_shaped_entities_get_distinct_keys(self):
        """The regression this whole key exists for.

        Under the original (trip_id, start_date) key these three entities --
        which carry no trip_id and share a start_date -- collapse to ONE key.
        On the live feed that mapped 1,348 entities onto 4 rows and reported
        99.5% suppression.
        """
        message = build(HSL_SHAPED)
        keys = {semantic_key(entity) for entity in message.entity}
        self.assertEqual(len(keys), 3)

        collapsed = {(e.trip_update.trip.trip_id, e.trip_update.trip.start_date)
                     for e in message.entity}
        self.assertEqual(len(collapsed), 1, "the old key really did collapse these")

    def test_same_route_and_date_but_different_start_time_are_different_trips(self):
        message = build([
            {"id": "a", "route_id": "31M1", "direction_id": 1,
             "start_date": "20260828", "start_time": "17:30:00"},
            {"id": "b", "route_id": "31M1", "direction_id": 1,
             "start_date": "20260828", "start_time": "17:45:00"},
        ])
        self.assertNotEqual(semantic_key(message.entity[0]), semantic_key(message.entity[1]))

    def test_direction_is_part_of_the_key(self):
        message = build([
            {"id": "a", "route_id": "31M1", "direction_id": 0,
             "start_date": "20260828", "start_time": "17:30:00"},
            {"id": "b", "route_id": "31M1", "direction_id": 1,
             "start_date": "20260828", "start_time": "17:30:00"},
        ])
        self.assertNotEqual(semantic_key(message.entity[0]), semantic_key(message.entity[1]))


class KeyGuardTest(unittest.TestCase):

    def test_accepts_a_one_to_one_key(self):
        assert_key_is_a_key(distinct_keys=1348, keyable_entities=1348)

    def test_rejects_the_collapse_that_actually_happened(self):
        """4 keys for 1,348 entities -- the observed failure, not a hypothetical."""
        with self.assertRaises(KeyCollapsed) as caught:
            assert_key_is_a_key(distinct_keys=4, keyable_entities=1348)
        self.assertIn("1348", str(caught.exception))

    def test_rejects_a_key_that_is_only_slightly_collapsed(self):
        """A key that is 95% unique is still not a key, and the failure would be
        far harder to notice than the 4-for-1,348 case."""
        with self.assertRaises(KeyCollapsed):
            assert_key_is_a_key(distinct_keys=950, keyable_entities=1000)

    def test_an_empty_snapshot_is_not_a_collapse(self):
        assert_key_is_a_key(distinct_keys=0, keyable_entities=0)


class ChangePredicateTest(unittest.TestCase):

    def test_identical_entities_hash_identically(self):
        one = build([dict(HSL_SHAPED[0], delay=60)])
        two = build([dict(HSL_SHAPED[0], delay=60)])
        self.assertEqual(content_hash(entity_payload(one.entity[0])),
                         content_hash(entity_payload(two.entity[0])))

    def test_a_changed_delay_changes_the_hash(self):
        one = build([dict(HSL_SHAPED[0], delay=60)])
        two = build([dict(HSL_SHAPED[0], delay=120)])
        self.assertNotEqual(content_hash(entity_payload(one.entity[0])),
                            content_hash(entity_payload(two.entity[0])))

    def test_entity_id_alone_does_not_change_the_hash(self):
        """The id is cleared before hashing, so a producer that regenerates ids
        every snapshot cannot make every entity look modified."""
        one = build([dict(HSL_SHAPED[0], delay=60)])
        two = build([dict(HSL_SHAPED[0], id="totally-different", delay=60)])
        self.assertNotEqual(one.entity[0].id, two.entity[0].id)
        self.assertEqual(content_hash(entity_payload(one.entity[0])),
                         content_hash(entity_payload(two.entity[0])))


class ChurnTest(unittest.TestCase):

    def test_no_change_is_zero_churn(self):
        snapshot = {"a": b"1", "b": b"2"}
        self.assertEqual(churn(snapshot, dict(snapshot)), 0.0)

    def test_modified_added_and_removed_all_count(self):
        previous = {"a": b"1", "b": b"2"}
        current = {"a": b"CHANGED", "c": b"3"}
        # union {a,b,c}: a modified, b removed, c added -> 3/3
        self.assertEqual(churn(previous, current), 1.0)

    def test_empty_pair_is_none_not_zero(self):
        """No data is not the same claim as no change."""
        self.assertIsNone(churn({}, {}))


class DecodeTest(unittest.TestCase):

    def test_a_good_message_decodes(self):
        result = decode(build(HSL_SHAPED).SerializeToString())
        self.assertEqual(result.status, "ok")
        self.assertEqual(len(result.entities), 3)
        self.assertEqual(result.header_timestamp, 1_800_000_000)

    def test_an_html_error_page_is_classified_as_such(self):
        """Not 'a parse failure'. PLAN.md section 6.3: a feed returning error
        pages is a different and worse problem than one returning short bodies,
        and a single failure rate hides which one you have."""
        result = decode(b"<!DOCTYPE html><html><body>502 Bad Gateway</body></html>")
        self.assertEqual(result.status, "not_protobuf")

    def test_a_truncated_body_is_a_parse_error(self):
        full = build(HSL_SHAPED).SerializeToString()
        result = decode(full[:len(full) // 2])
        self.assertIn(result.status, ("parse_error", "wrong_schema"))

    def test_an_empty_body_is_distinguished_from_an_empty_feed(self):
        self.assertEqual(decode(b"").status, "empty_body")
        empty_feed = gtfs_realtime_pb2.FeedMessage()
        empty_feed.header.gtfs_realtime_version = "2.0"
        empty_feed.header.timestamp = 1
        self.assertEqual(decode(empty_feed.SerializeToString()).status, "valid_but_empty")


if __name__ == "__main__":
    unittest.main()

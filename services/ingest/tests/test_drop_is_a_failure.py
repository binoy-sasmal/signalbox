"""A drop must be COUNTED AS A FAILURE, not merely counted. ADR 0010.

The queue's own accounting is tested in test_dropqueue.py. This file tests the
half that decides whether Gate 8's error budget is honest: that an evicted fetch
is written to the database with a failure outcome, and that the outcome is in the
failure set rather than quietly outside it.

Both halves are needed. A queue that counts drops perfectly, feeding a taxonomy
that calls a drop a success, produces a green SLI while losing data -- and the
verification run cannot catch it, because expected drops are zero.
"""
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.dropqueue import DropOldestQueue  # noqa: E402
from ingest.run import (  # noqa: E402
    DROP_OUTCOME,
    FAILURE_OUTCOMES,
    OUTCOMES,
    is_failure,
    record_drop,
)


class RecordingStore:
    """Stands in for Store, capturing what the run loop would have written."""

    def __init__(self):
        self.finalised = []

    def finalise_fetch(self, fetch_id, **fields):
        self.finalised.append((fetch_id, fields))


class DropIsAFailureTest(unittest.TestCase):

    def test_drop_outcome_is_in_the_failure_set(self):
        """The membership ADR 0010's whole argument turns on."""
        self.assertIn(DROP_OUTCOME, FAILURE_OUTCOMES)
        self.assertTrue(is_failure(DROP_OUTCOME))

    def test_a_successful_304_is_not_a_failure(self):
        """The counter-case. If everything were a failure the test above would
        pass for the wrong reason and the taxonomy would carry no information."""
        self.assertFalse(is_failure("not_modified"))
        self.assertFalse(is_failure("persisted"))

    def test_every_failure_outcome_is_a_declared_outcome(self):
        """A failure outcome the pipeline never writes is a rule with no subject."""
        self.assertLessEqual(FAILURE_OUTCOMES, set(OUTCOMES))

    def test_recording_a_drop_writes_a_failure_outcome_and_a_reason(self):
        store = RecordingStore()
        outcome = record_drop(store, fetch_id=42)

        self.assertEqual(outcome, DROP_OUTCOME)
        self.assertTrue(is_failure(outcome))
        self.assertEqual(len(store.finalised), 1)

        fetch_id, fields = store.finalised[0]
        self.assertEqual(fetch_id, 42)
        self.assertEqual(fields["outcome"], DROP_OUTCOME)
        self.assertTrue(fields["error"], "a drop must carry a reason, not just a status")
        self.assertIsNotNone(fields["committed_at"])

    def test_forced_drops_each_produce_one_recorded_failure(self):
        """End to end, with a stalled consumer: every evicted item is recorded.

        This is the shape the verification run will never produce -- expected
        drops there are zero -- which is why it is forced here.
        """
        queue = DropOldestQueue(depth=2)
        store = RecordingStore()
        release = threading.Event()
        took_first = threading.Event()

        queue.put((0, b"body"))

        def stalled_writer():
            queue.get(timeout=5)
            took_first.set()
            release.wait(timeout=5)

        thread = threading.Thread(target=stalled_writer, daemon=True)
        thread.start()
        # Synchronised, not slept on: this test asserts exact counts, so the
        # handoff must not depend on the scheduler.
        self.assertTrue(took_first.wait(timeout=5))

        for fetch_id in range(1, 9):
            evicted = queue.put((fetch_id, b"body"))
            if evicted is not None:
                record_drop(store, evicted[0])

        release.set()
        thread.join(timeout=5)

        # Eight produced into a depth of 2, so six must be lost.
        self.assertEqual(queue.dropped, 6)
        self.assertEqual(len(store.finalised), 6,
                         "every drop must produce exactly one recorded failure")
        self.assertTrue(all(is_failure(fields["outcome"])
                            for _, fields in store.finalised))

        # The recorded ids are the OLDEST six, which is what drop-oldest means.
        # Under drop-newest these would be the last six instead.
        self.assertEqual([fetch_id for fetch_id, _ in store.finalised], [1, 2, 3, 4, 5, 6])


if __name__ == "__main__":
    unittest.main()

"""The drop policy, exercised by forcing drops. ADR 0010.

Expected drops during the Gate 5 verification run are zero, so the verification
run does not exercise this path at all. A rule that ships unexercised into Gate 8
-- where it decides whether an error budget is honest -- is a rule nobody has ever
seen work.

These tests drive the queue's own accounting rather than a narrative about it, and
several of them assert the queue is WRONG in the ways it could plausibly be wrong:
that a drop is counted, that it is the oldest item that goes, and that a survivor
is the newest.
"""
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.dropqueue import DropOldestQueue  # noqa: E402


class DropOldestQueueTest(unittest.TestCase):

    def test_admits_up_to_depth_without_dropping(self):
        queue = DropOldestQueue(depth=2)
        self.assertIsNone(queue.put("a"))
        self.assertIsNone(queue.put("b"))
        self.assertEqual(queue.dropped, 0)
        self.assertEqual(queue.high_water, 2)

    def test_overflow_evicts_the_oldest_and_counts_it(self):
        queue = DropOldestQueue(depth=2)
        queue.put("a")
        queue.put("b")
        evicted = queue.put("c")

        # The evicted item is returned so the caller can record what was lost,
        # rather than discarded silently.
        self.assertEqual(evicted, "a")
        self.assertEqual(queue.dropped, 1)

        # Oldest went, newest stayed. The opposite policy -- drop newest --
        # would leave ["a", "b"] here, so this assertion distinguishes them.
        self.assertEqual(queue.get(timeout=1), "b")
        self.assertEqual(queue.get(timeout=1), "c")

    def test_every_overflow_is_counted_not_just_the_first(self):
        queue = DropOldestQueue(depth=1)
        queue.put(1)
        for value in range(2, 12):
            queue.put(value)
        self.assertEqual(queue.dropped, 10)
        self.assertEqual(queue.get(timeout=1), 11)

    def test_dropped_counts_items_lost_not_puts_that_found_it_full(self):
        """These are the same number only by accident, so they are checked apart.

        A depth-1 queue that is drained between puts never drops, even though
        every put after the first found a non-empty queue at some instant.
        """
        queue = DropOldestQueue(depth=1)
        for value in range(5):
            queue.put(value)
            self.assertEqual(queue.get(timeout=1), value)
        self.assertEqual(queue.dropped, 0)

    def test_put_never_blocks_when_full(self):
        """The poller must not be stalled by a slow writer -- that is 'block',
        the option ADR 0010 rejected. A put that blocked would hang here."""
        queue = DropOldestQueue(depth=1)
        queue.put("a")
        finished = threading.Event()

        def fill():
            for _ in range(100):
                queue.put("x")
            finished.set()

        thread = threading.Thread(target=fill, daemon=True)
        thread.start()
        self.assertTrue(finished.wait(timeout=5), "put() blocked when the queue was full")

    def test_stalled_writer_forces_drops_that_are_counted(self):
        """The end-to-end shape: a writer that stops consuming, a poller that
        keeps producing, and drops that show up in the accounting."""
        queue = DropOldestQueue(depth=2)
        release = threading.Event()
        took_first = threading.Event()
        consumed = []

        queue.put(0)

        def writer():
            first = queue.get(timeout=5)
            consumed.append(first)
            took_first.set()
            release.wait(timeout=5)          # stalled here, holding the pipeline
            while True:
                item = queue.get(timeout=0.2)
                if item is None:
                    return
                consumed.append(item)

        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        # Synchronised, not slept on: a sleep makes the arithmetic below depend
        # on the scheduler, and this test asserts exact counts.
        self.assertTrue(took_first.wait(timeout=5))

        for snapshot in range(1, 8):
            queue.put(snapshot)

        release.set()
        thread.join(timeout=5)

        # Seven produced after the first, a depth of 2, so five must be lost.
        self.assertEqual(queue.dropped, 5)
        self.assertEqual(consumed[0], 0)
        # What survives is the newest, which is the property that makes
        # drop-oldest correct for a FULL_DATASET feed.
        self.assertEqual(consumed[-1], 7)
        self.assertEqual(len(consumed), 3)

    def test_depth_must_be_at_least_one(self):
        with self.assertRaises(ValueError):
            DropOldestQueue(depth=0)

    def test_get_returns_none_once_closed_and_drained(self):
        queue = DropOldestQueue(depth=2)
        queue.put("a")
        queue.close()
        self.assertEqual(queue.get(timeout=1), "a")
        self.assertIsNone(queue.get(timeout=1))


if __name__ == "__main__":
    unittest.main()

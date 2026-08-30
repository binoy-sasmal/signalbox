"""The bounded queue and its drop policy. ADR 0010.

Drop oldest, depth 2, every drop counted and classified as a pipeline failure.

The counting is not incidental. A drop policy that is not counted launders errors
out of the error budget: if a dropped snapshot is invisible, the fastest route to a
green ingest_pipeline_success_rate at Gate 8 is a more aggressive drop policy, and
the SLO rewards exactly the behaviour it exists to detect.
"""
from __future__ import annotations

import collections
import threading

#: ADR 0010. For a FULL_DATASET feed feeding a current-state table this is a
#: latest-value register with a counter on it, which is the right structure. A
#: deeper queue only buys the right to eventually write staler data.
DEFAULT_DEPTH = 2


class DropOldestQueue:
    """Bounded FIFO that evicts its oldest item to admit a new one.

    Every eviction is counted. `dropped` is the number of items that were put on
    the queue and never handed to a consumer, which is the number that must be
    reported as pipeline failures -- not the number of `put` calls that found the
    queue full, which would be the same figure only by accident.
    """

    def __init__(self, depth: int = DEFAULT_DEPTH) -> None:
        if depth < 1:
            raise ValueError("depth must be at least 1")
        self.depth = depth
        self._items: collections.deque = collections.deque()
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._closed = False
        self.dropped = 0
        self.high_water = 0

    def put(self, item):
        """Admit `item`, evicting the oldest if full. Returns what was dropped.

        Never blocks and never refuses. Returning the evicted item rather than
        discarding it silently lets a caller record what was lost.
        """
        with self._not_empty:
            evicted = None
            if len(self._items) >= self.depth:
                evicted = self._items.popleft()
                self.dropped += 1
            self._items.append(item)
            self.high_water = max(self.high_water, len(self._items))
            self._not_empty.notify()
            return evicted

    def get(self, timeout: float | None = None):
        """Take the oldest item. Returns None if closed and drained, or on timeout."""
        with self._not_empty:
            while not self._items and not self._closed:
                if not self._not_empty.wait(timeout):
                    return None
            if self._items:
                return self._items.popleft()
            return None

    def close(self) -> None:
        with self._not_empty:
            self._closed = True
            self._not_empty.notify_all()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

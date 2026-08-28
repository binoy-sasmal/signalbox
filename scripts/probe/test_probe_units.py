"""Unit regressions for the three defects run 1 exposed.

Each of these was a real failure on live data, not a hypothetical:

  1. Test C sent conditional headers, so both re-polls returned 304 and the
     test -- which compares two BODIES -- had nothing to compare. It was lost
     on two of three feeds.
  2. Cadence was never checked against the interval we actually achieved, so
     gtfs.de reported a 30s cadence that was purely our sampling grid, and
     nothing flagged it.
  3. Test E used an absolute tolerance and discarded a discriminating result:
     Last-Modified 3.0s versus Date 8.5s leans clearly toward generation
     stamping, but both exceeded a fixed 2s cut.

These are pure-function tests, so they stay fast and do not need a fixture run.

    python -m unittest discover -s scripts/probe -p 'test_probe*.py'
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from analyse import (  # noqa: E402
    E_NOISE_FLOOR_S,
    nyquist_check,
    test_e,
)


class FakeSnapshot:
    """Minimal stand-in: test_e reads only these three attributes."""

    def __init__(self, header_ts: int, date: str | None, last_modified: str | None) -> None:
        self.header_ts = header_ts
        headers = {}
        if date:
            headers["date"] = date
        if last_modified:
            headers["last-modified"] = last_modified
        self.record = {"response_headers": headers}


def http_date(epoch: float) -> str:
    from email.utils import format_datetime
    return format_datetime(datetime.fromtimestamp(epoch, timezone.utc), usegmt=True)


BASE = int(datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc).timestamp())


class TestConditionalHeadersOnRePoll(unittest.TestCase):
    """Defect 1: the deliberate perturbation must never send validators.

    A 304 carries no body, and Test C is defined as comparing two bodies.
    Sending validators does not economise on the test, it destroys it.
    """

    def _probe(self):
        import poll

        cfg = {
            "id": "x", "base_url": "https://example.invalid/f.pb", "query": {},
            "sleep_after_completion_s": 5, "self_imposed_ceiling": {"requests": 5, "window_s": 60},
        }
        probe = poll.FeedProbe.__new__(poll.FeedProbe)
        probe.cfg = cfg
        # Not 0, 20 or 21: those are validator-rotation points, where one
        # conditional header is dropped deliberately to learn which the server
        # honours. Testing the exemption on a rotation boundary would conflate
        # the two behaviours.
        probe.seq = 5
        probe.etag = '"abc123"'
        probe.last_modified = "Fri, 28 Aug 2026 12:00:00 GMT"
        return probe

    def _plan_and_headers(self, probe_action: str):
        probe = self._probe()
        method, wants_body = probe._plan_request(probe_action)
        headers, mode = probe._conditional_headers(wants_body)
        return method, wants_body, headers, mode

    def test_scheduled_requests_do_send_validators(self):
        _, _, headers, mode = self._plan_and_headers("scheduled")
        self.assertIn("If-None-Match", headers)
        self.assertIn("If-Modified-Since", headers)
        self.assertNotEqual("none", mode)

    def test_repoll_sends_no_validators_and_is_a_get(self):
        for action in ("async_repoll_a", "async_repoll_b"):
            with self.subTest(action=action):
                method, wants_body, headers, mode = self._plan_and_headers(action)
                self.assertEqual("GET", method)
                self.assertTrue(wants_body)
                self.assertEqual({}, headers)
                self.assertEqual("none", mode)

    def test_head_mode_polls_with_head_and_validators(self):
        probe = self._probe()
        probe.cfg["method"] = "HEAD"
        probe.cfg["full_get_every_n"] = 60
        method, wants_body = probe._plan_request("scheduled")
        self.assertEqual("HEAD", method)
        self.assertFalse(wants_body)

    def test_periodic_full_get_sends_no_validators(self):
        """Regression: run 1b's first scheduled GET returned 304 and no body.

        In HEAD mode every HEAD refreshes the stored validator, so a GET whose
        entire purpose is to obtain a body is certain to be told it already has
        one. A request that exists for its body must not ask to be told no.
        """
        probe = self._probe()
        probe.cfg["method"] = "HEAD"
        probe.cfg["full_get_every_n"] = 6
        probe.seq = 5  # next request is the 6th
        method, wants_body = probe._plan_request("scheduled")
        self.assertEqual("GET", method)
        self.assertTrue(wants_body)
        self.assertEqual({}, probe._conditional_headers(wants_body)[0])


class TestNyquistGuard(unittest.TestCase):
    """Defect 2: a cadence under 2x the achieved interval is our sampling grid."""

    def test_resolvable_cadence_is_not_flagged(self):
        # VBB-shaped: 5s achieved interval, ~16s cadence with real spread.
        result = nyquist_check([16, 14, 19, 12, 31, 15, 17], 16.0, 5.0)
        self.assertFalse(result["undersampled"])

    def test_cadence_below_nyquist_is_flagged(self):
        # gtfs.de-shaped: ~22s achieved, 30s observed cadence.
        result = nyquist_check([30, 30, 30, 60, 30], 30.0, 22.0)
        self.assertTrue(result["undersampled"])
        self.assertTrue(result["below_nyquist"])
        self.assertIn("under", result["reason"])

    def test_cadence_equal_to_the_interval_is_flagged(self):
        # OVapi-shaped: cadence indistinguishable from the 60s interval.
        result = nyquist_check([60, 60, 120, 60, 60], 60.0, 60.0)
        self.assertTrue(result["undersampled"])
        self.assertGreaterEqual(result["grid_multiple_fraction"], 0.8)

    def test_grid_clustering_alone_does_not_flag(self):
        """Corroborating evidence only, never an independent trigger.

        A feed sampled well above Nyquist also lands every delta on the grid --
        cadence 30s at a 10s interval is 3x oversampled and its cadence figure
        is correct. Treating clustering as proof would flag a feed we are
        resolving perfectly well, which is what it did to the fixtures.
        """
        result = nyquist_check([30, 30, 30, 30, 60], 30.0, 10.0)
        self.assertFalse(result["below_nyquist"])
        self.assertGreaterEqual(result["grid_multiple_fraction"], 0.8)
        self.assertFalse(result["undersampled"])

    def test_missing_inputs_yield_no_verdict(self):
        self.assertIsNone(nyquist_check([], None, None)["undersampled"])


class TestEIsRelativeWithAFloor(unittest.TestCase):
    """Defect 3: which reference is closer, not whether either clears a cut."""

    def _snapshots(self, lm_offset: float, date_offset: float, n: int = 12):
        return [
            FakeSnapshot(BASE + i * 30,
                         http_date(BASE + i * 30 + date_offset),
                         http_date(BASE + i * 30 + lm_offset))
            for i in range(n)
        ]

    def test_the_gtfs_de_case_now_discriminates(self):
        """3.0s vs 8.5s: previously discarded by an absolute 2s tolerance."""
        result = test_e(self._snapshots(lm_offset=3, date_offset=9))
        self.assertEqual("generation", result["verdict"])

    def test_date_tracking_is_echo(self):
        result = test_e(self._snapshots(lm_offset=20, date_offset=0))
        self.assertEqual("echo", result["verdict"])

    def test_both_within_the_noise_floor_is_unavailable(self):
        """Sub-second separation is jitter. A verdict off it would be invented."""
        result = test_e(self._snapshots(lm_offset=0, date_offset=0))
        self.assertEqual("unavailable", result["verdict"])
        self.assertIn("noise", result["reason"])

    def test_insufficient_separation_is_unavailable(self):
        """Within 2x of each other, neither reference is clearly closer."""
        result = test_e(self._snapshots(lm_offset=5, date_offset=7))
        self.assertEqual("unavailable", result["verdict"])

    def test_floor_is_reported(self):
        self.assertEqual(E_NOISE_FLOOR_S, test_e(self._snapshots(3, 9))["noise_floor_s"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""A non-200/304 HTTP response must be COUNTED AS A FAILURE. Found 2026-08-30.

Same shape as ADR 0010's drop-is-a-failure rule, and found the same way a
verification run cannot catch: the Gate 5 hour run's live feed returned only
200 and 304 the entire hour, so this path was never exercised by evidence
anyone had actually looked at. It was found by checking the taxonomy directly,
not by running against a feed that happened to misbehave.

Before the fix, `classify_fetch_outcome` did not exist -- the outcome for a
429/500/502/etc. was built inline as f"unexpected_{status}", a fresh string per
status code that could never be a member of the closed FAILURE_OUTCOMES set by
construction. `is_failure()` returned False for it and `pipeline_outcomes.failures`
never counted it: a real upstream failure, correctly written to Postgres (the
`status` column has the real code), silently absent from the number Gate 8's SLI 1
would read. This file tests that the closed outcome "unexpected_status" now
carries it into the failure set, the same way "dropped" does.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import config  # noqa: E402
from ingest.churn import ChurnTracker  # noqa: E402
from ingest.dropqueue import DropOldestQueue  # noqa: E402
from ingest.run import (  # noqa: E402
    Counters,
    FAILURE_OUTCOMES,
    OUTCOMES,
    build_report,
    classify_fetch_outcome,
    is_failure,
)

TENANT_PATH = Path(__file__).resolve().parents[3] / "tenants" / "hsl_tripupdates.yaml"


class ClassifyFetchOutcomeTest(unittest.TestCase):
    """The pure decision, isolated from counters and the DB."""

    def test_a_transport_error_is_classified_as_such(self):
        self.assertEqual(classify_fetch_outcome(status=None, has_error=True),
                         "transport_error")

    def test_200_is_queued(self):
        self.assertEqual(classify_fetch_outcome(status=200, has_error=False), "queued")

    def test_304_is_not_modified(self):
        self.assertEqual(classify_fetch_outcome(status=304, has_error=False),
                         "not_modified")

    def test_real_failure_status_codes_are_unexpected_status(self):
        """429 (rate-limited) and 5xx are exactly the upstream failure modes a
        public transit feed under load actually produces -- not a hypothetical."""
        for status in (429, 500, 502, 503, 403, 404, 301):
            self.assertEqual(
                classify_fetch_outcome(status=status, has_error=False),
                "unexpected_status",
                f"status {status} was not classified as unexpected_status",
            )

    def test_an_error_takes_priority_over_a_status(self):
        """httpx can populate both in principle; the transport failure is the
        more specific and more actionable classification."""
        self.assertEqual(classify_fetch_outcome(status=500, has_error=True),
                         "transport_error")


class UnexpectedStatusIsAFailureTest(unittest.TestCase):

    def test_unexpected_status_is_in_the_failure_set(self):
        """The membership this whole fix turns on -- the regression test for the
        original bug, stated as directly as possible."""
        self.assertIn("unexpected_status", FAILURE_OUTCOMES)
        self.assertTrue(is_failure("unexpected_status"))

    def test_unexpected_status_is_a_declared_outcome(self):
        """A failure outcome nothing ever writes is a rule with no subject."""
        self.assertIn("unexpected_status", OUTCOMES)

    def test_a_successful_outcome_is_still_not_a_failure(self):
        """The counter-case. If everything were a failure this file would prove
        nothing about the specific gap it closes."""
        self.assertFalse(is_failure("not_modified"))
        self.assertFalse(is_failure("persisted"))

    def test_every_declared_status_code_round_trips_through_is_failure(self):
        """End to end: classify, then ask whether the result counts against the
        error budget, for the actual codes a feed can return."""
        for status in (429, 500, 502, 503):
            outcome = classify_fetch_outcome(status=status, has_error=False)
            self.assertTrue(
                is_failure(outcome),
                f"status {status} classified as {outcome!r}, which is_failure() "
                "does not count -- the original bug, reproduced",
            )


class BuildReportCountsUnexpectedStatusTest(unittest.TestCase):
    """End to end through build_report() itself -- the function whose SUM is
    where the original bug actually lived.

    The first version of this file tested only classify_fetch_outcome() and
    is_failure() in isolation, and a fail-first check (runs/gate5/... method)
    found that insufficient: mutating pipeline_outcomes.failures' sum to drop
    the unexpected_statuses term left every test in this file green, because
    none of them called build_report() at all. This class exists because of
    that gap, not despite it having been checked.
    """

    def setUp(self):
        self.tenant = config.load(TENANT_PATH)
        self.queue = DropOldestQueue(depth=2)
        self.churn = ChurnTracker()

    def _report(self, counters: Counters) -> dict:
        return build_report(
            self.tenant, counters, self.churn, self.queue,
            started_at=1_800_000_000.0, ended_at=1_800_000_060.0,
            duration_s=60.0, depth=2, awake=None,
        )

    def test_unexpected_statuses_reach_the_reported_failure_count(self):
        counters = Counters()
        counters.requests = 3
        counters.unexpected_statuses = 3

        report = self._report(counters)

        self.assertEqual(report["pipeline_outcomes"]["unexpected_statuses"], 3)
        self.assertEqual(
            report["pipeline_outcomes"]["failures"], 3,
            "3 unexpected-status responses did not reach pipeline_outcomes.failures "
            "-- the exact shape of the original bug",
        )

    def test_zero_unexpected_statuses_reports_zero_of_that_term(self):
        """The counter-case, matching the real Gate 5 hour run: HSL returned
        only 200/304 all hour, so this term should be exactly zero there."""
        counters = Counters()
        counters.requests = 719

        report = self._report(counters)

        self.assertEqual(report["pipeline_outcomes"]["unexpected_statuses"], 0)
        self.assertEqual(report["pipeline_outcomes"]["failures"], 0)

    def test_unexpected_statuses_sum_alongside_every_other_failure_kind(self):
        """All four terms in the sum, together -- proves the fix adds a term
        rather than replacing one, and that ADR 0010's drop accounting still
        works after this change touched the same expression."""
        counters = Counters()
        counters.requests = 10
        counters.transport_errors = 2
        counters.unexpected_statuses = 3
        counters.write_failures = 1
        counters.decode_classes = {"parse_error": 4, "ok": 0}
        self.queue.dropped = 5

        report = self._report(counters)

        self.assertEqual(report["pipeline_outcomes"]["failures"], 2 + 3 + 1 + 4 + 5)


if __name__ == "__main__":
    unittest.main()

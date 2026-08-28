"""Regression tests for the analyser, against synthetic feeds with known answers.

The fixtures exist because two earlier versions of the id-stability measure were
wrong, and each was wrong in a way that looked right on the data available at
the time:

  1. Inferring id stability from churn disagreement. Blind whenever a producer
     restamps every entity each snapshot -- both churn figures saturate at 100%
     and their difference carries no signal. It reported "ids stable" on the
     feed where ids regenerate every snapshot.
  2. An absolute threshold on Jaccard id persistence. Conflates unstable ids
     with genuine entity turnover: a stable-id feed at 40% turnover scores 0.43
     and gets called "regenerating".

`test_high_turnover_stable_ids_are_not_called_regenerating` is the guard on (2)
and asserts both halves -- that persistence really is below the old threshold,
and that the verdict is nonetheless correct. If someone reintroduces an absolute
cut, that test fails rather than the finding quietly reverting.

Requires the analyser's dependencies; run in its own CI job.

    python -m unittest discover -s scripts/probe -p 'test_analyse*.py'
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from analyse import analyse_run, markdown_table  # noqa: E402
from fixtures import build_synthetic_run  # noqa: E402


class FixtureTestCase(unittest.TestCase):
    """Built once: generating six feeds and decoding every payload is slow."""

    output: dict
    feeds: dict[str, dict]

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        run_dir = build_synthetic_run(Path(cls._tmp.name))
        cls.output = analyse_run(run_dir)
        cls.feeds = {feed["feed"]: feed for feed in cls.output["feeds"]}

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def verdict(self, feed: str) -> str:
        return self.feeds[feed]["header_timestamp"]["verdict"]

    def stability(self, feed: str) -> str | None:
        return self.feeds[feed]["churn"].get("id_stability")


class TestHeaderTimestampVerdicts(FixtureTestCase):
    def test_generation_feed(self):
        self.assertEqual("generation", self.verdict("fake_generation"))

    def test_echo_feed(self):
        self.assertEqual("echo", self.verdict("fake_echo"))

    def test_echo_feed_cadence_is_flagged_unreliable(self):
        """Cadence off an echoed timestamp measures our poll interval, not theirs."""
        self.assertTrue(self.feeds["fake_echo"]["cadence"].get("unreliable"))

    def test_static_feed_is_not_misread_as_echo(self):
        """A degraded producer emitting near-empty snapshots is Test A's blind spot.

        Identical content plus a legitimately advancing timestamp is the echo
        signature from the opposite cause. Test A must stand down and the other
        tests must carry the verdict.
        """
        feed = self.feeds["fake_static"]
        self.assertTrue(feed["header_timestamp"]["static_content_guard_triggered"])
        self.assertEqual("unavailable", feed["header_timestamp"]["votes"]["A_body_modulo_timestamp"])
        self.assertEqual("generation", self.verdict("fake_static"))


class TestEntityIdStability(FixtureTestCase):
    def test_regenerating_ids_detected(self):
        self.assertEqual("regenerating", self.stability("fake_generation"))

    def test_stable_ids_detected(self):
        self.assertEqual("stable", self.stability("fake_echo"))

    def test_moderate_turnover_with_stable_ids(self):
        self.assertEqual("stable", self.stability("turnover15_stable"))

    def test_high_turnover_stable_ids_are_not_called_regenerating(self):
        """Regression: the case that broke an absolute persistence threshold.

        Jaccard persistence here is ~0.43 -- genuinely below the 0.5 cut an
        earlier version used -- yet the ids are perfectly stable. The ratio
        against semantic persistence is invariant to turnover and gets it right.
        """
        churn = self.feeds["turnover40_stable"]["churn"]
        self.assertLess(
            churn["median_key_persistence_entity_id"], 0.5,
            "fixture no longer exercises the sub-threshold case it exists for",
        )
        self.assertEqual("stable", self.stability("turnover40_stable"))
        self.assertAlmostEqual(1.0, churn["id_vs_semantic_persistence_ratio"], places=2)

    def test_turnover_alone_does_not_distinguish_the_two_feeds(self):
        """Stable and regenerating at identical turnover: only the ratio separates them."""
        stable = self.feeds["turnover15_stable"]["churn"]
        regen = self.feeds["turnover15_regen"]["churn"]
        self.assertAlmostEqual(
            stable["median_key_persistence_semantic"],
            regen["median_key_persistence_semantic"], places=3,
            msg="fixtures must share semantic persistence for this to prove anything",
        )
        self.assertEqual("stable", self.stability("turnover15_stable"))
        self.assertEqual("regenerating", self.stability("turnover15_regen"))

    def test_comparison_gap_is_recorded(self):
        """A verdict from far-apart snapshots is weaker evidence and must say so."""
        gap = self.feeds["turnover15_stable"]["churn"]["comparison_gap_seconds"]
        self.assertIn("p50", gap)
        self.assertGreater(gap["p50"], 0)


class TestCadenceResolvability(FixtureTestCase):
    """A cadence figure is only a feed property if we sampled fast enough for it.

    gtfs.de reported a 30s cadence in run 1 that was purely our sampling grid,
    and nothing flagged it. The guard is independent of the header-timestamp
    verdict: undersampling and echo stamping are different ways for the same
    number to be meaningless.
    """

    def test_resolvable_feed_is_not_flagged(self):
        cadence = self.feeds["fake_generation"]["cadence"]
        self.assertFalse(cadence.get("unreliable", False))
        self.assertFalse(cadence["sampling"]["undersampled"])

    def test_feed_regenerating_as_fast_as_we_poll_is_flagged(self):
        cadence = self.feeds["undersampled_fast"]["cadence"]
        self.assertTrue(cadence["sampling"]["undersampled"])
        self.assertTrue(cadence["unreliable"])
        self.assertIn("UNDERSAMPLED", cadence["note"])

    def test_flag_is_independent_of_the_header_verdict(self):
        """The flag fires without the verdict being `echo`.

        Previously cadence was only ever flagged when the header timestamp was
        echoed. Undersampling is a separate failure mode and must flag on its
        own. (This feed's verdict comes out `unknown`, which is itself correct:
        sampling as fast as the feed regenerates leaves Test B unable to tell a
        sawtooth from a flat band, so the tests disagree and we record that
        rather than resolving it.)
        """
        self.assertNotEqual("echo", self.verdict("undersampled_fast"))
        self.assertTrue(self.feeds["undersampled_fast"]["cadence"]["unreliable"])

    def test_effective_interval_is_measured_not_configured(self):
        sampling = self.feeds["fake_generation"]["cadence"]["sampling"]
        self.assertIsNotNone(sampling["effective_interval_s"])
        self.assertIsNotNone(sampling["nyquist_limit_s"])


class TestSyntheticOutputIsLabelled(FixtureTestCase):
    """metrics.md holds measured numbers only; synthetic output must never pass for one."""

    def test_analysis_json_carries_the_flag(self):
        self.assertTrue(self.output["synthetic"])

    def test_rendered_table_is_banner_marked(self):
        table = markdown_table(self.output["feeds"], synthetic=self.output["synthetic"])
        self.assertIn("SYNTHETIC FIXTURE DATA", table)
        self.assertIn("NOT MEASURED", table)
        self.assertIn("metrics.md", table)

    def test_measured_output_carries_no_banner(self):
        table = markdown_table(self.output["feeds"], synthetic=False)
        self.assertNotIn("SYNTHETIC", table)


class TestPreconditionGuards(FixtureTestCase):
    """A test whose discriminating assumption is violated must stand down.

    `fast_cadence` regenerates every 2s, violating Test B's quantisation
    precondition and Test C's gap precondition simultaneously. Live evidence:
    hsl_vehiclepositions, where C's false `echo` outvoted two correct tests.
    """

    def test_b_stands_down_on_a_cadence_too_coarse_to_resolve(self):
        detail = self.feeds["fast_cadence"]["header_timestamp"]["detail"]["B_lag_shape"]
        self.assertEqual("unavailable", detail["verdict"])

    def test_c_stands_down_when_the_gap_spans_generations(self):
        detail = self.feeds["fast_cadence"]["header_timestamp"]["detail"]["C_async_repoll"]
        self.assertEqual("unavailable", detail["verdict"])
        self.assertIn("spans real generations", detail["reason"])

    def test_guards_do_not_disarm_the_tests_on_a_normal_feed(self):
        """The guards must cost nothing where the preconditions hold."""
        votes = self.feeds["fake_generation"]["header_timestamp"]["votes"]
        self.assertEqual("generation", votes["A_body_modulo_timestamp"])
        self.assertEqual("generation", votes["B_lag_shape"])
        self.assertEqual("generation", votes["C_async_repoll"])

    def test_strength_is_recorded_with_every_verdict(self):
        for feed in self.feeds.values():
            strength = feed["header_timestamp"]["strength"]
            self.assertIn(strength["label"], {"none", "weak", "moderate", "strong"})
            self.assertEqual(5, strength["total_tests"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

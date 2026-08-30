"""Fixed-rate ticking (ADR 0005) and tenant-file validation."""
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import config  # noqa: E402
from ingest.poller import FixedRateTicker, Poller  # noqa: E402

VALID = """
name: test_feed
jurisdiction: FI
base_url: https://example.invalid/feed
query: {}
rate_limit:
  documented: null
  self_imposed:
    requests: 15
    window_s: 60
auth_ref: null
licence: CC-BY-4.0
attribution: "(c) Someone {year_of_delivery}"
header_timestamp_trust: generation
incrementality: FULL_DATASET
poll_interval_s: 5
db_schema: tenant_test_feed
"""


def write(body):
    handle = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8")
    handle.write(textwrap.dedent(body))
    handle.close()
    return handle.name


class FixedRateTickerTest(unittest.TestCase):
    """The scheduler is a pure function of a clock and a set of durations, which
    is why it is separated from the poller: skip accounting is testable with no
    network and no sleeping."""

    def test_ticks_land_on_a_fixed_grid(self):
        ticker = FixedRateTicker(interval_s=5.0, start=1000.0)
        self.assertEqual(ticker.next_tick(now=1001.0), (1005.0, 0))
        self.assertEqual(ticker.next_tick(now=1006.0), (1010.0, 0))
        self.assertEqual(ticker.next_tick(now=1011.0), (1015.0, 0))

    def test_the_grid_does_not_drift_when_work_is_slow_but_fits(self):
        """A 2.4s fetch on a 5s tick -- HSL's p50 -- must not move the grid."""
        ticker = FixedRateTicker(interval_s=5.0, start=0.0)
        now = 0.0
        for expected in (5.0, 10.0, 15.0, 20.0):
            target, skipped = ticker.next_tick(now)
            self.assertEqual(target, expected)
            self.assertEqual(skipped, 0)
            now = target + 2.4        # work takes 2.4s, then the next tick is due

    def test_a_fetch_that_outlasts_the_interval_skips_exactly_one_tick(self):
        """HSL's max observed fetch was 5.09s against a 5s tick. One tick lost,
        not two, and not a burst to catch up."""
        ticker = FixedRateTicker(interval_s=5.0, start=0.0)
        target, skipped = ticker.next_tick(now=5.09)
        self.assertEqual(skipped, 1)
        self.assertEqual(target, 10.0)
        self.assertEqual(ticker.skipped, 1)

    def test_a_very_slow_fetch_skips_every_tick_it_covers(self):
        ticker = FixedRateTicker(interval_s=5.0, start=0.0)
        target, skipped = ticker.next_tick(now=23.0)
        self.assertEqual(skipped, 4)          # 5, 10, 15, 20 all in the past
        self.assertEqual(target, 25.0)

    def test_skipping_never_produces_a_catch_up_burst(self):
        """The property that keeps the request rate bounded: after any delay the
        next tick is still on the original grid, never immediate."""
        ticker = FixedRateTicker(interval_s=5.0, start=0.0)
        target, _ = ticker.next_tick(now=17.4)
        self.assertGreater(target, 17.4)
        self.assertEqual(target % 5.0, 0.0)


class ConditionalRequestTest(unittest.TestCase):

    def test_the_first_request_carries_no_validators(self):
        poller = Poller("https://example.invalid/feed", {})
        headers, mode = poller._conditional_headers()
        self.assertEqual(headers, {})
        self.assertEqual(mode, "none")
        poller.close()

    def test_both_validators_are_sent_once_known(self):
        poller = Poller("https://example.invalid/feed", {})
        poller.etag = '"abc"'
        poller.last_modified = "Fri, 28 Aug 2026 15:16:11 GMT"
        headers, mode = poller._conditional_headers()
        self.assertEqual(headers["If-None-Match"], '"abc"')
        self.assertEqual(headers["If-Modified-Since"], "Fri, 28 Aug 2026 15:16:11 GMT")
        self.assertEqual(mode, "if-none-match+if-modified-since")
        poller.close()


class TenantConfigTest(unittest.TestCase):

    def test_the_real_tenant_file_loads(self):
        tenant = config.load(Path(__file__).resolve().parents[3] / "tenants"
                             / "hsl_tripupdates.yaml")
        self.assertEqual(tenant.name, "hsl_tripupdates")
        self.assertEqual(tenant.incrementality, "FULL_DATASET")

    def test_a_differential_feed_is_refused(self):
        """ADR 0010: dropping a DIFFERENTIAL message loses state permanently, so
        the service must refuse rather than inherit a policy chosen for a
        different feed shape."""
        path = write(VALID.replace("FULL_DATASET", "DIFFERENTIAL"))
        with self.assertRaises(config.ConfigError) as caught:
            config.load(path)
        self.assertIn("DIFFERENTIAL", str(caught.exception))

    def test_a_resolved_url_with_a_query_string_is_refused(self):
        """Some transit APIs authenticate by query parameter, so a resolved URL
        is where a credential lands in a committed file.

        The fixture uses the redaction placeholder rather than a credential-shaped
        value, because the credential gate scans this file too and would flag a
        realistic one. No strength is lost: the validator rejects on the presence
        of `?`, so the parameter's value is not what is under test. Where a fixture
        DOES need an attack string, the gate has an escape marker scoped to its own
        adversarial suite -- this is not that case.
        """
        path = write(VALID.replace(
            "base_url: https://example.invalid/feed",
            "base_url: https://example.invalid/feed?apikey=<redacted:auth_ref>"))
        with self.assertRaises(config.ConfigError) as caught:
            config.load(path)
        self.assertIn("query string", str(caught.exception))

    def test_a_missing_auth_ref_is_refused_but_null_is_accepted(self):
        """Absent and null are different claims: null says we checked."""
        path = write("\n".join(line for line in VALID.splitlines()
                               if not line.startswith("auth_ref")))
        with self.assertRaises(config.ConfigError) as caught:
            config.load(path)
        self.assertIn("auth_ref", str(caught.exception))
        self.assertIsNone(config.load(write(VALID)).auth_ref)

    def test_a_schema_name_that_is_not_a_bare_identifier_is_refused(self):
        """db_schema is interpolated into DDL, so its shape is constrained
        rather than quoted and hoped."""
        # Single-quoted so YAML parses each value and the VALIDATOR is what
        # rejects it. Double quotes would make the injection case a YAML syntax
        # error, which would pass this test without exercising the check at all.
        for bad in ('tenant"; DROP SCHEMA public; --', "Tenant_Mixed", "1tenant",
                    "a-b", "public.evil", ""):
            escaped = bad.replace("'", "''")
            path = write(VALID.replace("db_schema: tenant_test_feed",
                                       f"db_schema: '{escaped}'"))
            with self.assertRaises(config.ConfigError, msg=f"accepted {bad!r}"):
                config.load(path)

    def test_an_interval_that_breaches_the_self_imposed_ceiling_is_refused(self):
        """15 requests per 60s is the Stage 0 ceiling; a 1s interval needs 60."""
        path = write(VALID.replace("poll_interval_s: 5", "poll_interval_s: 1"))
        with self.assertRaises(config.ConfigError) as caught:
            config.load(path)
        self.assertIn("ceiling", str(caught.exception))

    def test_rate_limit_must_distinguish_documented_from_self_imposed(self):
        """The Gate 5 finding: they are different claims and HSL has only one."""
        path = write(VALID.replace(
            "rate_limit:\n  documented: null\n  self_imposed:\n    requests: 15\n"
            "    window_s: 60",
            "rate_limit:\n  self_imposed:\n    requests: 15\n    window_s: 60"))
        with self.assertRaises(config.ConfigError) as caught:
            config.load(path)
        self.assertIn("documented", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

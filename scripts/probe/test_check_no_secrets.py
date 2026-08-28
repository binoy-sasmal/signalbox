"""Adversarial tests for the structural credential gate.

Every test here is a credential the gate must catch. Confirming the gate is
quiet on clean files proves nothing on its own -- a gate that never fires and a
gate that cannot fire look identical from the outside. Each case asserts the
finding lands on the right file and line, so a rule that silently stops working
fails here rather than in production.

Two cases are regressions for holes that were real:
  - a credential inside an ALLOW-LISTED header value, which key-only
    validation waved through
  - the placeholder exemption widened into a bypass by substring matching

Stdlib only, so this runs in CI with no dependency install, like the gate.

    python -m unittest discover -s scripts/probe -p 'test_*.py'
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from check_no_secrets import scan  # noqa: E402

REAL_KEY = "sk-live-9f8e7d6c5b4a3210fedc"


class GateTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, name: str, *lines: str) -> Path:
        path = self.tmp / name
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def observation(self, name: str, *, response_headers=None, request_headers=None) -> Path:
        record = {
            "feed": "ch", "run": "run2", "seq": 1,
            "request_at": "2026-08-28T12:00:00+00:00",
            "status": 200,
            "request_headers": request_headers or {},
            "response_headers": response_headers or {"etag": '"abc123"'},
            "body_sha256": "a" * 64,
        }
        return self.write(name, json.dumps(record))

    def assertCaught(self, path: Path, line: int, fragment: str):
        findings, _ = scan([path])
        self.assertTrue(findings, f"gate did not fire on {path.name}")
        matching = [f for f in findings if f.line == line and fragment.lower() in f.message.lower()]
        self.assertTrue(
            matching,
            f"expected a finding on line {line} mentioning {fragment!r}; got: "
            + "; ".join(f"{f.line}: {f.message}" for f in findings),
        )
        return matching

    def assertClean(self, path: Path):
        findings, _ = scan([path])
        self.assertEqual(
            [], findings,
            "gate fired on a legitimate file: "
            + "; ".join(f"{f.line}: {f.message}" for f in findings),
        )


class TestQueryParameterInConfig(GateTestCase):
    """Rule: endpoints are stored split; no auth value in a query parameter."""

    def test_unredacted_key_in_query_param(self):
        path = self.write(
            "feeds.yaml",
            "run: run2",
            f'endpoint: "https://api.opentransportdata.ch/gtfsrt?apikey={REAL_KEY}"',
        )
        self.assertCaught(path, 2, "apikey")

    def test_unredacted_key_as_config_value(self):
        path = self.write("feeds.yaml", f"api_key: {REAL_KEY}")
        self.assertCaught(path, 1, "auth-shaped key")

    def test_correctly_split_endpoint_passes(self):
        self.assertClean(self.write(
            "good.yaml",
            'base_url: "https://api.opentransportdata.ch/gtfsrt"',
            "query:",
            '  apikey: "<redacted:auth_ref>"',
            "auth_ref: ch_opentransport_key",
        ))


class TestHeaderCapture(GateTestCase):
    """Rule: headers by allow-list, dropped at capture rather than redacted."""

    def test_api_key_request_header(self):
        path = self.observation("obs.jsonl", request_headers={
            "if-none-match": '"abc"', "x-api-key": REAL_KEY,
        })
        self.assertCaught(path, 1, "request_headers contains 'x-api-key'")

    def test_authorization_response_header(self):
        path = self.observation("obs.jsonl", response_headers={
            "etag": '"abc"', "authorization": f"Bearer {REAL_KEY}",
        })
        self.assertCaught(path, 1, "not in the capture allow-list")

    def test_allowed_headers_only_passes(self):
        self.assertClean(self.observation("obs.jsonl", response_headers={
            "etag": '"a7f3-62c9"',
            "cache-control": "max-age=10",
            "date": "Fri, 28 Aug 2026 12:00:00 GMT",
            "content-length": "51234",
        }))


class TestTokenInsideAllowedHeaderValue(GateTestCase):
    """Regression: an allow-listed KEY does not make its VALUE safe.

    Key-only validation passed these. A provider echoing a credential into
    Cache-Control or ETag would have reached git unnoticed.
    """

    def test_bare_assignment_in_cache_control(self):
        path = self.observation("obs.jsonl", response_headers={
            "cache-control": f"max-age=10, apikey={REAL_KEY}",
        })
        self.assertCaught(path, 1, "does not make its value safe")

    def test_query_style_token_in_etag(self):
        path = self.observation("obs.jsonl", response_headers={
            "etag": f'"abc?access_token={REAL_KEY}"',
        })
        self.assertCaught(path, 1, "does not make its value safe")

    def test_bearer_token_in_allowed_header(self):
        path = self.observation("obs.jsonl", response_headers={
            "cache-control": f"Bearer {REAL_KEY}",
        })
        self.assertCaught(path, 1, "bearer token")

    def test_ordinary_cache_control_passes(self):
        self.assertClean(self.observation("obs.jsonl", response_headers={
            "cache-control": "public, max-age=10, s-maxage=30",
        }))


class TestPlaceholderExemptionCannotBeWidened(GateTestCase):
    """Regression: the exemption is exact-match, never substring.

    Substring matching meant a real credential could be smuggled through by
    prefixing it with a placeholder. Both forms below were previously accepted.
    """

    # The next two lines must literally spell out an attack string, so they
    # carry the gate's explicit escape marker. It is greppable and auditable by
    # design -- `noqa: secret` should appear only here and never in a config,
    # manifest or observation log.
    def test_redaction_placeholder_prefix_does_not_bypass(self):
        path = self.write(
            "feeds.yaml",
            f'endpoint: "https://api.example.ch/rt?apikey=<redacted:auth_ref>{REAL_KEY}"',  # noqa: secret
        )
        self.assertCaught(path, 1, "apikey")

    def test_ellipsis_prefix_does_not_bypass(self):
        path = self.write(
            "feeds.yaml",
            f'endpoint: "https://api.example.ch/rt?apikey=...{REAL_KEY}"',  # noqa: secret
        )
        self.assertCaught(path, 1, "apikey")

    def test_placeholder_prefix_in_config_value_does_not_bypass(self):
        path = self.write("feeds.yaml", f"api_key: <redacted:auth_ref>{REAL_KEY}")
        self.assertCaught(path, 1, "auth-shaped key")

    def test_placeholder_prefix_in_header_value_does_not_bypass(self):
        path = self.observation("obs.jsonl", response_headers={
            "cache-control": f"apikey=<redacted:auth_ref>{REAL_KEY}",
        })
        self.assertCaught(path, 1, "does not make its value safe")

    def test_genuine_placeholders_still_exempt(self):
        """The exemption must survive: documentation has to stay writable."""
        self.assertClean(self.write(
            "README.md",
            "A resolved endpoint like `...?apikey=...` would leak a credential.",
            "Store it as `?apikey=<key>` instead, or `<redacted:auth_ref>`.",
            "Set `api_key: ${CH_API_KEY}` from the environment.",
            "auth_ref: ch_opentransport_key",
        ))


class TestEscapeMarkerIsConfined(GateTestCase):
    """The escape marker is enforced, not merely audited.

    It is honoured in this file alone. Anywhere else its presence is itself a
    finding, whatever it is suppressing -- otherwise the documented bypass sits
    in the open for the first time the gate fires inconveniently.
    """

    MARKER = "# " + "noqa: " + "secret"  # assembled so this line is not itself skipped

    def test_marker_suppressing_a_credential_is_rejected(self):
        path = self.write("feeds.yaml", f"api_key: {REAL_KEY}  {self.MARKER}")
        self.assertCaught(path, 1, "not permitted outside")

    def test_marker_suppressing_nothing_is_still_rejected(self):
        path = self.write("helper.py", f"timeout = 30  {self.MARKER}")
        self.assertCaught(path, 1, "not permitted outside")

    def test_marker_in_a_config_file_is_rejected(self):
        path = self.write("values.yaml", f"replicas: 1  {self.MARKER}")
        self.assertCaught(path, 1, "not permitted outside")


if __name__ == "__main__":
    unittest.main(verbosity=2)

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
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from check_no_secrets import is_scannable, scan, tracked_files  # noqa: E402

# The gate now applies its key = value rule to every scannable file, source
# included, so this fixture trips it. That is correct: it IS a
# credential-shaped literal under an auth-shaped name. The escape marker
# exists for exactly this -- the gate's own adversarial fixtures -- and is
# honoured only in this file.
REAL_KEY = "sk-live-9f8e7d6c5b4a3210fedc"  # noqa: secret
# Assembled rather than written out, the same way MARKER is below, so this
# file does not itself carry the literal the gate exists to catch.
AUTH_HEADER = "Authorization" + ": " + "Bearer " + REAL_KEY

# AWS's own published documentation example pair -- not a live credential.
# Present because the hole this suite now guards was found with a real-shaped
# AWS credentials file, and the fixture should keep that shape.
AWS_SECRET_FIXTURE = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"  # noqa: secret


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


class TestDataFilesAreNotFalsePositives(GateTestCase):
    """Regression: the gate must not cry wolf on its own evidence files.

    Both cases below blocked a real commit of run 1's analysis. A gate that
    fires on committed measurements teaches people to route around it, which
    costs more than the rule earns.
    """

    def test_auth_shaped_field_names_holding_measurements_pass(self):
        self.assertClean(self.write(
            "analysis.json",
            '  "median_churn_keyed_on_semantic_key": 0.1544,',
            '  "median_key_persistence_semantic": 0.998,',
            '  "median_key_persistence_entity_id": 0.97,',
        ))

    def test_json_trailing_comma_does_not_defeat_value_parsing(self):
        """`"auth": "none",` left `none",` after quote-stripping and was flagged."""
        self.assertClean(self.write(
            "run.json", '      "auth": "none",', '      "auth": null,'))

    def test_the_numeric_exemption_is_bounded(self):
        """A long run of digits could be a token, so the exemption stops."""
        path = self.write("cfg.yaml", "api_key: 90183726451092837465109")
        self.assertCaught(path, 1, "auth-shaped key")

    def test_a_real_key_next_to_an_auth_shaped_name_still_fails(self):
        path = self.write("analysis.json", f'  "median_key_persistence": "{REAL_KEY}",')
        self.assertCaught(path, 1, "auth-shaped key")


class TestNumericExemptionCannotBeWidened(GateTestCase):
    """Regression: the third exemption, held to the same standard as the first two.

    Both earlier exemptions turned out bypassable after the fact, so this one is
    attacked directly. It must mean "this value parses as a number", not "this
    value looks numeric" -- an earlier version used float(), which also accepts
    inf, nan, Infinity and 1_000_000.
    """

    def test_alphabetic_floats_are_not_exempt(self):
        for value in ("inf", "nan", "Infinity", "-inf"):
            with self.subTest(value=value):
                path = self.write("cfg.yaml", f"api_key: {value}")
                self.assertCaught(path, 1, "auth-shaped key")

    def test_underscore_separated_digits_are_not_exempt(self):
        path = self.write("cfg.yaml", "api_key: 1_000_000_000_0")
        self.assertCaught(path, 1, "auth-shaped key")

    def test_hex_fragment_is_not_exempt(self):
        for value in ("0x1A2B3C", "deadbeef", "1A2B3C4D"):
            with self.subTest(value=value):
                path = self.write("cfg.yaml", f"api_key: {value}")
                self.assertCaught(path, 1, "auth-shaped key")

    def test_base64_fragment_is_not_exempt(self):
        path = self.write("cfg.yaml", "api_key: c2VjcmV0Cg==")
        self.assertCaught(path, 1, "auth-shaped key")

    def test_long_digit_run_is_not_exempt(self):
        path = self.write("cfg.yaml", "api_key: 1234567890123456")
        self.assertCaught(path, 1, "auth-shaped key")

    def test_genuine_measurements_stay_exempt(self):
        self.assertClean(self.write(
            "analysis.yaml",
            "median_key_persistence_semantic: 0.998",
            "median_churn_keyed_on_semantic_key: 0.1544",
            "entities_key_count: 163819.5",
            "auth_latency_ms: -1e-5",
        ))


class TestJsonIsCheckedByType(GateTestCase):
    """JSON types are unambiguous, so the check parses rather than pattern-matches.

    A JSON number under an auth-shaped key cannot be a credential; a JSON string
    can be, regardless of length or shape.
    """

    def _json(self, name: str, payload) -> Path:
        return self.write(name, json.dumps(payload, indent=2))

    def test_numeric_values_under_auth_shaped_keys_pass(self):
        self.assertClean(self._json("analysis.json", {
            "feeds": [{
                "median_key_persistence_semantic": 0.998,
                "median_churn_keyed_on_semantic_key": 0.1544,
                "auth": None,
            }],
        }))

    def test_string_credential_under_an_auth_shaped_key_is_caught(self):
        path = self._json("analysis.json", {"feeds": [{"api_key": REAL_KEY}]})
        self.assertCaught(path, 4, "auth-shaped key")

    def test_a_numeric_string_is_still_a_string(self):
        """Quoted digits are a string in JSON; the numeric exemption must not apply."""
        path = self._json("run.json", {"subscription_key": "1234567890123456"})
        self.assertCaught(path, 2, "auth-shaped key")

    def test_nested_and_redacted_values_pass(self):
        self.assertClean(self._json("run.json", {
            "feeds": [{"query": {"apikey": "<redacted:auth_ref>"}, "auth_ref": "ch_key"}],
        }))


class TestExtensionlessFilesAreScanned(GateTestCase):
    """Suffix-based selection is not the same as covering every committed file.

    Path.suffix is empty for a dotfile and for an extensionless script, so
    `.gitignore`, `.gitattributes` and `.githooks/pre-commit` were tracked and
    unscanned while CLAUDE.md claimed the check covered every committed file.
    The last is a shell script -- a place a credential genuinely ends up.
    """

    def test_extensionless_shell_script_is_caught(self):
        path = self.write(
            "pre-commit",
            "#!/bin/sh",
            f"curl -H '{AUTH_HEADER}' https://x",
        )
        findings, checked = scan([path])
        self.assertEqual(checked, 1, "extensionless file was skipped, not scanned")
        self.assertTrue(findings, "credential in an extensionless script went unreported")

    def test_dotfile_is_caught(self):
        path = self.write(
            ".gitattributes",
            "* text=auto",
            f"# {AUTH_HEADER}",
        )
        findings, checked = scan([path])
        self.assertEqual(checked, 1)
        self.assertTrue(findings)

    def test_clean_extensionless_file_passes(self):
        self.assertClean(self.write(".gitignore", ".venv/", "__pycache__/"))

    def test_binary_without_a_suffix_is_skipped_not_crashed(self):
        path = self.tmp / "blob"
        path.write_bytes(b"\x00\x01\x02\xff\xfe")
        findings, checked = scan([path])
        self.assertEqual(checked, 0, "undecodable file should be skipped")
        self.assertEqual(findings, [])

    def test_suffixed_binary_is_still_excluded(self):
        # The extensionless path must not become a way in for suffixed files
        # that were deliberately out of scope.
        path = self.tmp / "payload.pb"
        path.write_text(AUTH_HEADER + "\n", encoding="utf-8")
        findings, checked = scan([path])
        self.assertEqual(checked, 0)
        self.assertEqual(findings, [])


class TestEveryTrackedFileIsInScope(unittest.TestCase):
    """The coverage claim itself, asserted against the real tree.

    CLAUDE.md says the structural check covers every committed file. Every
    other test in this file builds its own fixture, so not one of them can
    fail when a *newly tracked* file falls outside the scan set. Until this
    test the claim held by accident of which suffixes happened to be present,
    and `main()` printed the same reassuring line either way.

    `.rego` is the concrete case rather than a hypothetical one: Conftest is a
    settled decision in CLAUDE.md, so Stage 3 adds policy files under a suffix
    TEXT_SUFFIXES does not list. This test is what turns that from a silent
    hole into a red build on the commit that adds the first one.
    """

    def test_every_tracked_file_is_scannable(self):
        repo_root = Path(__file__).resolve().parents[2]
        previous = Path.cwd()
        os.chdir(repo_root)
        try:
            paths = tracked_files()
            # A tracked path with no file behind it is a deletion in the
            # working tree, not a coverage hole. scan() skips those too.
            unscanned = [p for p in paths if p.is_file() and not is_scannable(p)]
        except subprocess.CalledProcessError:
            self.skipTest("not a git repository")
        finally:
            os.chdir(previous)

        self.assertEqual(
            [], [str(p) for p in unscanned],
            "tracked file(s) outside the scan set while CLAUDE.md claims the "
            "check covers every committed file. Add the suffix to "
            "TEXT_SUFFIXES, or narrow the claim -- but do not leave the two "
            "disagreeing.",
        )


class TestCredentialsFileIsCaughtWithoutAnExtension(GateTestCase):
    """Regression for a hole that was open and measured, not hypothetical.

    is_scannable() was widened to admit extensionless files precisely because a
    credentials file has no extension. The key = value rule stayed gated on a
    suffix allow-list, so such a file was admitted, counted as scanned, and then
    exempted from the only rule that would have caught it. Measured 2026-08-29:
    an AWS credentials file passed with no extension and failed as `.ini` on
    identical bytes.

    The gate reported `passed (1 file(s) scanned, 0 skipped)` while holding an
    AWS key pair. Neither the pre-commit hook nor CI would have stopped the
    commit that added it.
    """

    def _aws_credentials(self, name: str) -> Path:
        return self.write(
            name,
            "[signalbox]",
            "aws_access_key_id = AKIAIOSFODNN7EXAMPLE",
            f"aws_secret_access_key = {AWS_SECRET_FIXTURE}",
        )

    def test_extensionless_credentials_file_is_caught(self):
        self.assertCaught(self._aws_credentials("credentials"), 3, "auth-shaped key")

    def test_identical_bytes_under_ini_are_still_caught(self):
        self.assertCaught(self._aws_credentials("creds.ini"), 3, "auth-shaped key")

    def test_the_suffix_is_not_what_decides(self):
        """The two above must agree. If they ever diverge, the gate is back."""
        bare, _ = scan([self._aws_credentials("credentials")])
        ini, _ = scan([self._aws_credentials("creds.ini")])
        self.assertEqual(
            [f.message for f in bare], [f.message for f in ini],
            "extensionless and .ini disagree, so file type is deciding whether "
            "the rule runs -- which is the defect this class exists for",
        )


class TestTheRulesRunOnEveryTrackedSuffix(GateTestCase):
    """`scanned` is not `checked`, and that gap is what hid the hole.

    TestEveryTrackedFileIsInScope asserts a tracked file is scanned. It cannot
    see a file that is scanned and then exempted from every rule that matters,
    which is exactly what happened to extensionless files. This asserts the
    rule actually fires, once per suffix present in the real tree, so a suffix
    arriving later that the rules do not reach fails here.
    """

    def _tracked_suffixes(self) -> list[str]:
        repo_root = Path(__file__).resolve().parents[2]
        previous = Path.cwd()
        os.chdir(repo_root)
        try:
            return sorted({path.suffix for path in tracked_files()})
        except subprocess.CalledProcessError:
            self.skipTest("not a git repository")
        finally:
            os.chdir(previous)

    def test_a_planted_credential_is_caught_under_every_tracked_suffix(self):
        uncaught = []
        for suffix in self._tracked_suffixes():
            name = f"planted{suffix}" if suffix else "credentials"
            if suffix == ".json":
                # Valid JSON is answered by check_json_types, not the line rule.
                path = self.write(name, json.dumps({"api_key": REAL_KEY}, indent=2))
            else:
                path = self.write(name, "[section]", f"api_key = {REAL_KEY}")
            findings, checked = scan([path])
            if checked != 1 or not findings:
                uncaught.append(f"{name} (scanned={checked}, findings={len(findings)})")

        self.assertEqual(
            [], uncaught,
            "a planted credential survived under a suffix that exists in this "
            "repo. The file may be scanned and still be exempt from every rule "
            "that matters -- see docs/limits.md.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

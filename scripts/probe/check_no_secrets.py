"""Structural check: no credential may reach a committed file.

This is not a general secret scanner. It is a structural assertion, which is
why it is worth having: every header key present in an observation log must be
a member of the capture allow-list, and every auth-shaped config key or URL
query parameter must hold the redaction placeholder. Those are exact
conditions, not heuristics, so they neither miss nor cry wolf.

Runs in two places, deliberately:
  - pre-commit, as fast feedback
  - CI, as enforcement

`git commit --no-verify` bypasses the hook. This project's own argument is
that a local gate is feedback while only the enforced gate is enforcement --
the same logic that puts Conftest in CI and Gatekeeper at admission applies to
us. CI is the gate that counts.

Stdlib only: the enforcement gate must run with no dependency install in
front of it.

Usage:
    python check_no_secrets.py                 # scan all git-tracked files (CI)
    python check_no_secrets.py FILE [FILE...]  # scan named files (pre-commit)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from allowlist import (  # noqa: E402
    REDACTION_PLACEHOLDER,
    REQUEST_HEADER_ALLOWLIST,
    RESPONSE_HEADER_ALLOWLIST,
    is_auth_param,
)

# The escape marker exists so the gate's own adversarial fixtures can contain
# attack strings. It is honoured in that one file and REJECTED everywhere else.
#
# Confirming by audit that the marker appears nowhere else is a point-in-time
# check, and this project's argument -- for Conftest, for Gatekeeper, and for
# this gate -- is that only an enforced check is enforcement. An unenforced
# escape hatch is a documented bypass sitting in the open for the first time
# the gate fires inconveniently.
# Assembled rather than written as one literal, so this file contains no usable
# marker of its own -- the rule below would otherwise reject its own definition,
# and exempting the gate's source would put an unenforced hole in the enforcer.
ESCAPE_MARKER = "noqa" + ": " + "secret"
ESCAPE_MARKER_ALLOWED_IN = "test_check_no_secrets.py"

# Upper bound on the numeric type-exemption; see is_not_a_credential.
# Keys naming a pointer to a secret rather than holding one. `auth_ref` is the
# name of a SOPS secret, not its value.
POINTER_SUFFIXES = ("_ref", "_file", "_path", "_name", "_id")

MAX_NUMERIC_EXEMPT_LEN = 12

# JSON's own number grammar. Deliberately NOT float(), which also accepts
# inf, nan, Infinity and 1_000_000 -- alphabetic and underscore-bearing
# strings that are not numbers in any serialisation format we handle.
JSON_NUMBER = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?")

TEXT_SUFFIXES = {
    ".json", ".jsonl", ".yaml", ".yml", ".md", ".toml", ".ini", ".cfg",
    ".tf", ".tfvars", ".hcl", ".py", ".sh", ".env", ".txt",
}

# Literal give-aways, checked anywhere in a committed text file. Both require a
# token-shaped value, so prose that merely names the header does not fire.
LITERAL_PATTERNS = [
    (re.compile(r"\bAuthorization\s*:\s*(?:Bearer|Basic|Token)?\s*([A-Za-z0-9._\-+/=]{12,})", re.I),
     "literal Authorization header with a token-shaped value"),
    (re.compile(r"\bBearer\s+([A-Za-z0-9._\-]{12,})"), "literal Bearer token"),
]

# Query parameters anywhere in a line, whether or not part of a complete URL.
#
# The value class must INCLUDE angle brackets. Excluding them truncated a value
# of the form `apikey=<redacted:auth_ref>` followed by a live key down to an
# empty string, which then read as a placeholder and waved the credential
# through -- the same bypass as substring matching in is_placeholder, one layer
# down. Delimiters that end a value in prose (quotes, backticks, whitespace)
# stay excluded so documentation examples do not capture trailing punctuation.
QUERY_PARAM = re.compile(r"""[?&]([A-Za-z0-9_.\-]+)=([^&\s"'`]*)""")

# Values that cannot be a credential: documentation placeholders and elisions.
# Without this the gate fires on its own docs, and a gate that cries wolf
# teaches people to reach for --no-verify.
# `{VAR}` is included alongside `${VAR}` and `{{VAR}}`: an f-string or format
# template is a placeholder in the same sense, and excluding it would force
# escape markers onto ordinary templating.
PLACEHOLDER_VALUE = re.compile(
    r"^(\.{2,}|<[^>]*>|\{\{.*\}\}|\{\w+\}|\$\{?\w+\}?|your[_-]?\w*|x{3,}|todo|changeme|placeholder)$",
    re.I,
)


# Assignments inside a header VALUE, e.g. "max-age=10, apikey=sk-live-...".
# Scoped to observation header values only. Applied repo-wide it would fire on
# `api_key = os.environ[...]` in ordinary code, and a gate that cries wolf
# teaches people to reach for --no-verify -- the failure mode we are avoiding.
BARE_ASSIGNMENT = re.compile(
    r"\b([A-Za-z0-9_.\-]*(?:key|token|secret|auth|password)[A-Za-z0-9_.\-]*)\s*=\s*([^\s;,&]+)",
    re.I,
)


def is_not_a_credential(value: str) -> bool:
    """Values whose type rules them out, whatever the key is called.

    Analysis output is full of auth-shaped field names holding measurements --
    `median_key_persistence_semantic`, `median_churn_keyed_on_semantic_key` --
    and a number is not a secret. Without this the gate fires on its own
    evidence files, and a gate that cries wolf on committed data teaches people
    to route around it.

    Strictly parse-based. An earlier version used `float()`, which is not the
    same question: it accepts `inf`, `nan`, `Infinity` and `1_000_000`, so
    alphabetic and underscore-bearing strings were being exempted by a check
    that was supposed to mean "this is a number". JSON's own number grammar is
    the right test, and the length bound is defence in depth behind it rather
    than the primary guard.
    """
    value = value.strip().rstrip(",").strip().strip("\"'")
    if value.lower() in {"null", "none", "true", "false", "~", "{}", "[]", "{", "["}:
        return True
    if not JSON_NUMBER.fullmatch(value):
        return False
    # A measurement is short (0.1544, 163819.5). A long run of digits could be a
    # numeric token, so the exemption stops before it becomes a way to carry one
    # past an auth-shaped key in a format we cannot type-check.
    return len(value) <= MAX_NUMERIC_EXEMPT_LEN


def walk_json(node, path: str = ""):
    """Yield (json_path, key, value) for every mapping entry."""
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else str(key)
            yield here, key, value
            yield from walk_json(value, here)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk_json(value, f"{path}[{index}]")


def check_json_types(path: Path, raw: str) -> list[Finding] | None:
    """Type-based auth-key check for JSON, where types are unambiguous.

    Parsing answers the question the line scanner can only approximate: a JSON
    number, boolean or null under an auth-shaped key cannot be a credential,
    because credentials travel as strings. Only string values are examined, so
    no length heuristic is needed here at all.
    """
    try:
        document = json.loads(raw)
    except json.JSONDecodeError:
        # Unparseable: return None so the caller falls back to the line
        # scanner. Returning [] here would mean a malformed .json file got no
        # auth-key check at all, which is precisely the file most worth checking.
        return None

    lines = raw.splitlines()
    findings: list[Finding] = []
    for json_path, key, value in walk_json(document):
        if not isinstance(key, str) or not is_auth_param(key) or not isinstance(value, str):
            continue
        # Same pointer-suffix exemption the line scanner applies. `auth_ref`
        # names a SOPS secret; it is the pointer, not the thing pointed at. The
        # two paths must agree, or a value's safety would depend on which file
        # format it happened to be written in.
        if key.lower().endswith(POINTER_SUFFIXES):
            continue
        if is_placeholder(value) or not value.strip():
            continue
        if value.lower() in {"null", "none", "true", "false"}:
            continue
        line = next((i for i, text in enumerate(lines, 1) if f'"{key}"' in text), 0)
        findings.append(Finding(
            path, line,
            f"auth-shaped key '{json_path}' holds a literal string value. Use a "
            f"SOPS-encrypted secret and an *_ref pointer, or '{REDACTION_PLACEHOLDER}'.",
        ))
    return findings


def is_placeholder(value: str) -> bool:
    """Exact match only.

    Substring matching here was a bypass: `<redacted:auth_ref>sk-live-realkey`
    and `...sk-live-realkey` both contained a placeholder and so were waved
    through with a live credential attached. A placeholder is the WHOLE value
    or it is not a placeholder. Regression-tested in test_check_no_secrets.py.
    """
    # Trailing JSON punctuation stripped first: `"auth": "none",` otherwise
    # leaves `none",` after quote-stripping and reads as a literal secret.
    value = value.strip().rstrip(",").strip().strip("\"'")
    if not value or value == REDACTION_PLACEHOLDER:
        return True
    return bool(PLACEHOLDER_VALUE.fullmatch(value))


class Finding:
    def __init__(self, path: Path, line: int, message: str) -> None:
        self.path, self.line, self.message = path, line, message

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"

    __repr__ = __str__


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True,
    )
    return [Path(line) for line in result.stdout.splitlines() if line.strip()]


def scan_header_value(path: Path, number: int, field: str, key: str, value) -> list[Finding]:
    """Look for a credential inside an allow-listed header's value."""
    if not isinstance(value, str):
        return []
    findings: list[Finding] = []

    for pattern, description in LITERAL_PATTERNS:
        match = pattern.search(value)
        if match and not is_placeholder(match.group(1)):
            findings.append(Finding(path, number, f"{field}['{key}'] value carries a {description}"))

    for name, candidate in QUERY_PARAM.findall(value) + BARE_ASSIGNMENT.findall(value):
        if (is_auth_param(name) and not is_placeholder(candidate)
                and not is_not_a_credential(candidate)):
            findings.append(Finding(
                path, number,
                f"{field}['{key}'] value carries auth-bearing '{name}=' with an unredacted "
                "value. An allow-listed header key does not make its value safe.",
            ))
            break
    return findings


def check_observation_log(path: Path) -> list[Finding]:
    """Exact allow-list membership. This is the real guard."""
    findings: list[Finding] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            findings.append(Finding(path, number, "observation log line is not valid JSON"))
            continue

        for field, allowlist in (("response_headers", RESPONSE_HEADER_ALLOWLIST),
                                 ("request_headers", REQUEST_HEADER_ALLOWLIST)):
            headers = record.get(field)
            if headers is None:
                continue
            if not isinstance(headers, dict):
                findings.append(Finding(path, number, f"{field} is not an object"))
                continue
            for key, value in headers.items():
                if key.lower() not in allowlist:
                    findings.append(Finding(
                        path, number,
                        f"{field} contains '{key}', which is not in the capture allow-list. "
                        "Headers must be dropped at capture time, not redacted afterwards.",
                    ))
                    continue
                # An allow-listed key does not make its value safe: a provider
                # can echo a credential inside an otherwise legitimate header.
                findings.extend(scan_header_value(path, number, field, key, value))

        for field in ("url", "full_url", "endpoint"):
            if field in record:
                findings.append(Finding(
                    path, number,
                    f"record contains '{field}'. Endpoints are stored split into "
                    "base_url + query; a joined URL can carry a query-parameter credential.",
                ))
    return findings


def check_text_file(path: Path, auth_key_rule: bool = True) -> list[Finding]:
    findings: list[Finding] = []
    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return findings

    for number, line in enumerate(content.splitlines(), start=1):
        if ESCAPE_MARKER in line:
            if path.name == ESCAPE_MARKER_ALLOWED_IN:
                continue  # honoured: this file must contain attack strings
            findings.append(Finding(
                path, number,
                f"'{ESCAPE_MARKER}' is not permitted outside {ESCAPE_MARKER_ALLOWED_IN}. "
                "The escape exists only so the gate's own adversarial fixtures can hold "
                "attack strings; anywhere else it is a bypass, whatever it is suppressing.",
            ))
            continue

        for pattern, description in LITERAL_PATTERNS:
            match = pattern.search(line)
            if match and not is_placeholder(match.group(1)):
                findings.append(Finding(path, number, description))

        for name, value in QUERY_PARAM.findall(line):
            if (is_auth_param(name) and not is_placeholder(value)
                    and not is_not_a_credential(value)):
                findings.append(Finding(
                    path, number,
                    f"query parameter '{name}' carries an unredacted value. Store "
                    "base_url + query map instead of a joined URL -- some transit APIs "
                    "authenticate by query parameter.",
                ))

        # key: value / key = value in config-shaped files. JSON is excluded:
        # check_json_types answers the same question by parsing, where types are
        # unambiguous, so having both would only let them disagree.
        match = re.match(r"""\s*["']?([A-Za-z0-9_.\-]+)["']?\s*[:=]\s*(.+?)\s*$""", line)
        if match and auth_key_rule and path.suffix in {".yaml", ".yml", ".json", ".toml",
                                                       ".ini", ".cfg", ".env", ".tfvars"}:
            name, value = match.group(1), match.group(2).strip().strip("\"'")
            if not is_auth_param(name) or not value:
                continue
            benign = (
                is_placeholder(value)
                or is_not_a_credential(value)
                or value.startswith(("$", "#"))
                or name.lower().endswith(POINTER_SUFFIXES)
            )
            if not benign:
                findings.append(Finding(
                    path, number,
                    f"auth-shaped key '{name}' holds a literal value. Use a SOPS-encrypted "
                    f"secret and an *_ref pointer, or '{REDACTION_PLACEHOLDER}'.",
                ))
    return findings


def is_scannable(path: Path) -> bool:
    """Whether a tracked file gets scanned.

    Suffix-based selection alone left three tracked files unscanned --
    `.gitignore`, `.gitattributes` and `.githooks/pre-commit` -- because
    Path.suffix is empty for a dotfile and for an extensionless script. The
    last of those is a shell script, which is exactly the kind of file a
    credential ends up in, and CLAUDE.md claims this check covers every
    committed file. The claim and the code have to agree; this closes the gap
    in the direction that keeps the stronger guarantee.

    An extensionless file is scanned when it decodes as UTF-8, which is how a
    binary without a suffix stays out without needing a second allow-list to
    maintain.
    """
    if path.suffix in TEXT_SUFFIXES:
        return True
    if path.suffix:
        return False
    try:
        path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return True


def scan(paths: list[Path]) -> tuple[list[Finding], int]:
    """Scan paths, returning findings and the number of files examined."""
    findings: list[Finding] = []
    checked = 0
    for path in paths:
        if not path.is_file() or not is_scannable(path):
            continue
        checked += 1
        auth_key_rule = True
        if path.suffix == ".jsonl":
            findings.extend(check_observation_log(path))
        elif path.suffix == ".json":
            try:
                typed = check_json_types(path, path.read_text(encoding="utf-8"))
            except OSError:
                typed = None
            if typed is not None:
                # Parsed cleanly, so types settle it and the line scanner's
                # approximation of the same rule stands down.
                findings.extend(typed)
                auth_key_rule = False
        findings.extend(check_text_file(path, auth_key_rule=auth_key_rule))
    return findings, checked


def main(argv: list[str]) -> int:
    if argv:
        paths = [Path(arg) for arg in argv]
    else:
        try:
            paths = tracked_files()
        except subprocess.CalledProcessError:
            print("not a git repository", file=sys.stderr)
            return 2

    findings, checked = scan(paths)

    if findings:
        print(f"Structural credential check FAILED ({len(findings)} finding(s)):\n", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        print(
            "\nThis check is structural, not heuristic: each finding is a real violation of the "
            "capture allow-list or the endpoint-splitting rule, not a guess.",
            file=sys.stderr,
        )
        return 1

    print(f"Structural credential check passed ({checked} file(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

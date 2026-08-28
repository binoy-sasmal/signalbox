"""Shared capture allow-list and redaction rules.

Imported by the poller, which enforces at capture time, and by
check_no_secrets.py, which enforces at commit and in CI. One definition, so the
two cannot drift: a checker that permits more than the capturer records is a
gate that passes exactly what it was built to catch.

Stdlib only, deliberately. The enforcement gate has to run in CI with no
dependency install in front of it.
"""

REDACTION_PLACEHOLDER = "<redacted:auth_ref>"

# Response headers worth keeping. Everything else is dropped at capture time
# rather than redacted afterwards -- a credential must have no field to land in.
RESPONSE_HEADER_ALLOWLIST = frozenset({
    "etag",
    "last-modified",
    "date",
    "content-type",
    "content-encoding",
    "content-length",
    "cache-control",
    "retry-after",
    "ratelimit-limit",
    "ratelimit-remaining",
    "ratelimit-reset",
    # Vendor X- forms are common enough that preflight explicitly looks for them.
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
})

# The only request headers we send that carry measurement meaning. Auth headers
# are never recorded.
REQUEST_HEADER_ALLOWLIST = frozenset({
    "if-none-match",
    "if-modified-since",
})

# Substrings that mark a config key or URL query parameter as auth-bearing.
# Deliberately broad: over-redacting a manifest costs nothing, under-redacting
# it puts a live key in git.
AUTH_PARAM_PATTERNS = (
    "apikey",
    "api_key",
    "api-key",
    "subscriptionkey",
    "subscription_key",
    "subscription-key",
    "access_token",
    "accesstoken",
    "token",
    "secret",
    "password",
    "passwd",
    "auth",
    "credential",
    "signature",
    "key",
)


def is_auth_param(name: str) -> bool:
    """True if a query parameter or config key name looks auth-bearing."""
    lowered = name.lower()
    return any(pattern in lowered for pattern in AUTH_PARAM_PATTERNS)


def redact_query(query: dict | None) -> dict:
    """Redact auth-bearing values from a query-parameter map.

    Endpoints are stored split into base_url + query and never as a joined URL,
    because some transit APIs authenticate by query parameter. A resolved
    endpoint like `...?apikey=<key>` would put a credential into the run
    manifest, which the header allow-list does not inspect.
    """
    if not query:
        return {}
    return {
        key: (REDACTION_PLACEHOLDER if is_auth_param(key) else value)
        for key, value in query.items()
    }


def filter_headers(headers, allowlist) -> dict:
    """Keep only allow-listed headers, lowercased.

    Takes any mapping with .items(); httpx header objects qualify.
    """
    return {
        key.lower(): value
        for key, value in headers.items()
        if key.lower() in allowlist
    }

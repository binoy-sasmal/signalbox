"""Tenant configuration.

`tenants/<name>.yaml` is the source of truth (PLAN.md section 3). At Gate 5 the
ingest service is its only consumer. Fields PLAN.md section 4 declares first-class
are loaded and validated even where nothing reads them yet -- a schema commitment
that is never checked is a schema commitment in name only.
"""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import yaml

#: Postgres identifiers are interpolated into DDL, so the shape is constrained
#: rather than quoted-and-hoped. Rejected values never reach a SQL string.
SCHEMA_NAME = re.compile(r"^[a-z][a-z0-9_]*$")

#: ADR 0010: drop-oldest is only correct when each snapshot supersedes the last.
SUPPORTED_INCREMENTALITY = "FULL_DATASET"


class ConfigError(ValueError):
    """A tenant file that cannot be run, with the reason in the message."""


@dataclasses.dataclass(frozen=True)
class Tenant:
    name: str
    base_url: str
    query: dict
    poll_interval_s: float
    db_schema: str
    incrementality: str
    header_timestamp_trust: str
    licence: str
    attribution: str
    auth_ref: str | None
    rate_limit: dict

    @property
    def self_imposed_rate(self) -> tuple[int, int]:
        limit = self.rate_limit["self_imposed"]
        return limit["requests"], limit["window_s"]


def _require(raw: dict, key: str, path: Path):
    if key not in raw:
        raise ConfigError(f"{path}: missing required field '{key}'")
    return raw[key]


def load(path: str | Path) -> Tenant:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level")

    for key in ("name", "base_url", "query", "poll_interval_s", "db_schema",
                "incrementality", "header_timestamp_trust", "licence",
                "attribution", "rate_limit"):
        _require(raw, key, path)

    if "auth_ref" not in raw:
        raise ConfigError(
            f"{path}: 'auth_ref' is required and may be null. Absent and null are "
            "different claims: null says we checked and the feed needs no key."
        )

    # A resolved URL is where a query-parameter credential lands in a committed
    # file. The split shape is enforced here as well as by the credential gate,
    # so a tenant file cannot be run in a shape the gate would reject.
    if "?" in raw["base_url"]:
        raise ConfigError(
            f"{path}: base_url carries a query string. Endpoints are stored split, "
            "as base_url plus a query map."
        )
    if not isinstance(raw["query"], dict):
        raise ConfigError(f"{path}: 'query' must be a mapping, not {type(raw['query']).__name__}")

    if raw["incrementality"] != SUPPORTED_INCREMENTALITY:
        # ADR 0010. Refuse rather than inherit a backpressure policy chosen for a
        # different feed shape: dropping a DIFFERENTIAL message loses state
        # permanently, and the current-state table is wrong for it besides.
        raise ConfigError(
            f"{path}: incrementality is {raw['incrementality']!r}. This service implements "
            f"{SUPPORTED_INCREMENTALITY} only -- ADR 0010's drop-oldest backpressure and "
            "ADR 0009's current-state table are both incorrect for a differential feed."
        )

    if not SCHEMA_NAME.match(raw["db_schema"]):
        raise ConfigError(
            f"{path}: db_schema {raw['db_schema']!r} is not a bare lowercase identifier. "
            "It is interpolated into DDL."
        )

    interval = raw["poll_interval_s"]
    if not isinstance(interval, (int, float)) or interval <= 0:
        raise ConfigError(f"{path}: poll_interval_s must be a positive number")

    rate = raw["rate_limit"]
    if not isinstance(rate, dict) or "self_imposed" not in rate or "documented" not in rate:
        raise ConfigError(
            f"{path}: rate_limit must carry both 'documented' and 'self_imposed'. "
            "They are different claims -- see the Gate 5 finding in docs/metrics.md."
        )

    requests, window_s = rate["self_imposed"]["requests"], rate["self_imposed"]["window_s"]
    achievable = window_s / interval
    if achievable > requests:
        raise ConfigError(
            f"{path}: poll_interval_s={interval} yields {achievable:.1f} requests per "
            f"{window_s}s, above the self-imposed ceiling of {requests}."
        )

    return Tenant(
        name=raw["name"],
        base_url=raw["base_url"],
        query=raw["query"],
        poll_interval_s=float(interval),
        db_schema=raw["db_schema"],
        incrementality=raw["incrementality"],
        header_timestamp_trust=raw["header_timestamp_trust"],
        licence=raw["licence"],
        attribution=raw["attribution"],
        auth_ref=raw["auth_ref"],
        rate_limit=rate,
    )

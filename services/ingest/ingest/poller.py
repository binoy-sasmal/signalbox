"""Fixed-rate, single-flight polling with conditional requests. ADR 0005.

Ticks fire on a fixed grid. A tick that arrives while a fetch is still in flight is
skipped and counted -- never queued (a burst is the opposite of what a fixed rate is
for) and never overlapped (that would break the single-flight property keeping our
request rate bounded).

The response-header allow-list is the Stage 0 rule, unchanged: headers are dropped at
capture time rather than redacted afterwards, so a credential-bearing header has no
field to land in.
"""
from __future__ import annotations

import dataclasses
import hashlib
import time

import httpx

#: PLAN.md section 6.5. Explicit allow-list, never a deny-list.
CAPTURED_HEADERS = (
    "etag", "last-modified", "date", "content-type", "content-encoding",
    "content-length", "cache-control", "retry-after",
)

#: OVapi's README asks consumers to identify themselves, gtfs.de is a volunteer
#: service, and 720 requests an hour should be attributable to a human who can be
#: emailed. Same contact as the Stage 0 probe.
USER_AGENT = (
    "signalbox-ingest/0.1 (Gate 5 ingest service; "
    "contact: binoysasmal@yahoo.com)"
)


@dataclasses.dataclass
class Fetch:
    """One HTTP request and what came back. No raw URL, ever."""
    requested_at: float
    responded_at: float | None = None
    status: int | None = None
    conditional_mode: str = "none"
    headers: dict = dataclasses.field(default_factory=dict)
    body: bytes | None = None
    body_sha256: str | None = None
    body_bytes: int = 0
    error: str | None = None

    @property
    def elapsed_ms(self) -> float | None:
        if self.responded_at is None:
            return None
        return (self.responded_at - self.requested_at) * 1000.0


class Poller:
    """Issues conditional GETs and remembers the validators the server gave us."""

    def __init__(self, base_url: str, query: dict, timeout: float = 30.0) -> None:
        self.base_url = base_url
        self.query = dict(query)
        self.etag: str | None = None
        self.last_modified: str | None = None
        self.client = httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"},
        )

    def _conditional_headers(self) -> tuple[dict, str]:
        """Validators for an ordinary poll.

        ADR 0005 carries the rule that a request whose purpose is to OBTAIN a body
        must not send validators. At Gate 5 there is exactly one request class and
        it is not that kind, so every poll here is conditional. A backfill or
        re-read path added later must not call this.
        """
        headers, modes = {}, []
        if self.etag:
            headers["If-None-Match"] = self.etag
            modes.append("if-none-match")
        if self.last_modified:
            headers["If-Modified-Since"] = self.last_modified
            modes.append("if-modified-since")
        return headers, "+".join(modes) if modes else "none"

    def fetch(self) -> Fetch:
        headers, mode = self._conditional_headers()
        record = Fetch(requested_at=time.time(), conditional_mode=mode)
        try:
            response = self.client.get(self.base_url, params=self.query, headers=headers)
        except httpx.HTTPError as exc:
            record.responded_at = time.time()
            record.error = f"{type(exc).__name__}: {exc}"
            return record

        record.responded_at = time.time()
        record.status = response.status_code
        record.headers = {
            name: value for name, value in response.headers.items()
            if name.lower() in CAPTURED_HEADERS
        }

        if response.status_code == 200:
            record.body = response.content
            record.body_bytes = len(response.content)
            record.body_sha256 = hashlib.sha256(response.content).hexdigest()

        # Validators are refreshed on any response that carries them, including a
        # 304 -- RFC 9110 allows a 304 to update them.
        if response.headers.get("etag"):
            self.etag = response.headers["etag"]
        if response.headers.get("last-modified"):
            self.last_modified = response.headers["last-modified"]

        return record

    def close(self) -> None:
        self.client.close()


class FixedRateTicker:
    """A fixed grid of tick times, skipping any tick already in the past.

    Separated from the poller so the skip accounting is testable without a network:
    given a clock and a set of work durations, the sequence of ticks and skips is a
    pure function.
    """

    def __init__(self, interval_s: float, start: float) -> None:
        self.interval_s = interval_s
        self.start = start
        self.tick_index = 0
        self.skipped = 0

    def next_tick(self, now: float) -> tuple[float, int]:
        """Return (when the next tick fires, how many ticks were skipped to get there)."""
        self.tick_index += 1
        target = self.start + self.tick_index * self.interval_s
        skipped_here = 0
        while target <= now:
            self.tick_index += 1
            self.skipped += 1
            skipped_here += 1
            target = self.start + self.tick_index * self.interval_s
        return target, skipped_here

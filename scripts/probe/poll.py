"""Stage 0 feed probe -- poller.

Captures evidence and performs no analysis whatsoever; see analyse.py.

The split is the most important decision in the probe. The header-timestamp
analysis will be wrong on the first pass, and re-running the analyser costs
seconds where re-running the poller costs polling budget we may not be able to
afford on a rate-limited feed.

This is a throwaway measurement instrument, not v0 of the ingest service. Its
goal is evidence capture under adversarial conditions; the ingest service's
goal is throughput. Write it to be deleted.

Usage:
    python poll.py config.run1.yaml
"""

from __future__ import annotations

import asyncio
import collections
import hashlib
import json
import random
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import yaml

from allowlist import (
    REQUEST_HEADER_ALLOWLIST,
    RESPONSE_HEADER_ALLOWLIST,
    filter_headers,
    redact_query,
)

# Every Nth request drops one conditional header so we can tell which validator
# the server actually honours, rather than only that it honours "one of them".
PROBE_IF_NONE_MATCH_ONLY = 20
PROBE_IF_MODIFIED_SINCE_ONLY = 21


class ClockRef:
    """Wall clock anchored once; every interval measured from a monotonic base.

    Durations are never computed by subtracting two datetime.now() calls -- on
    Windows in particular the wall clock can step underneath us.

    The NTP offset is recorded, not applied. We do not adjust our clock; the
    analyser corrects with the recorded offset so the correction stays visible
    and reversible.
    """

    NTP_SERVER = "pool.ntp.org"

    def __init__(self) -> None:
        self.t0_mono = time.monotonic()
        self.t0_wall = datetime.now(timezone.utc)
        self.offset_ms: float | None = None
        self.sync_failed = True
        self.synced_at_mono: float | None = None
        self.syncs: list[dict] = []

    def sync(self, label: str) -> None:
        """Query NTP. On failure record null and a flag -- never zero.

        UDP 123 is blocked on plenty of networks. A silent zero would be a
        fabricated measurement and would lend unearned precision to every lag
        figure derived from it.
        """
        try:
            import ntplib

            response = ntplib.NTPClient().request(self.NTP_SERVER, version=3, timeout=5)
            self.offset_ms = response.offset * 1000.0
            self.sync_failed = False
            self.synced_at_mono = time.monotonic()
            detail = None
        except Exception as exc:  # noqa: BLE001 -- any failure means "unknown"
            self.offset_ms = None
            self.sync_failed = True
            detail = f"{type(exc).__name__}: {exc}"

        self.syncs.append({
            "label": label,
            "at": self.wall(time.monotonic()).isoformat(),
            "offset_ms": self.offset_ms,
            "sync_failed": self.sync_failed,
            "detail": detail,
        })
        state = "failed" if self.sync_failed else f"offset {self.offset_ms:+.1f} ms"
        print(f"[clock] NTP sync ({label}): {state}")

    def wall(self, mono: float) -> datetime:
        return self.t0_wall + timedelta(seconds=mono - self.t0_mono)

    def sync_age_s(self, mono: float) -> float | None:
        if self.synced_at_mono is None:
            return None
        return mono - self.synced_at_mono


class SlidingWindowLimiter:
    """Sliding window, not fixed window.

    A fixed-window "N per minute" counter permits 2N requests in a moment
    across a window boundary, which trips a server enforcing a true sliding
    window. That is the classic bug, and the reason the CH feed gets 45s
    spacing rather than 30s when run 2 happens.

    halve() is one-way. For a probe we never ratchet back up: multiplicative
    decrease with no increase is simpler than AIMD and cannot walk us back into
    a limit we already hit.
    """

    def __init__(self, requests: int, window_s: float) -> None:
        self.capacity = requests
        self.window = window_s
        self.hits: collections.deque[float] = collections.deque()

    async def acquire(self) -> None:
        while True:
            now = time.monotonic()
            while self.hits and now - self.hits[0] >= self.window:
                self.hits.popleft()
            if len(self.hits) < self.capacity:
                self.hits.append(now)
                return
            await asyncio.sleep(self.window - (now - self.hits[0]) + 0.01)

    def halve(self) -> int:
        self.capacity = max(1, self.capacity // 2)
        return self.capacity


class ObservationWriter:
    """Single writer, flushed per line.

    If the laptop sleeps or the process is killed, everything captured up to
    that point survives. An hour of lost polling is expensive.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = path.open("a", encoding="utf-8")
        self.lock = asyncio.Lock()
        self.count = 0

    async def write(self, record: dict) -> None:
        async with self.lock:
            self.handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.handle.flush()
            self.count += 1

    def close(self) -> None:
        self.handle.close()


class FeedProbe:
    """One feed. Strictly sequential, so single-flight is structural.

    There is never more than one in-flight request per feed, because the loop
    awaits each response before scheduling the next. A timer-driven design
    could overlap requests on a slow response and quietly double our rate.
    """

    def __init__(self, cfg: dict, run_cfg: dict, clock: ClockRef,
                 writer: ObservationWriter, blobs_dir: Path) -> None:
        self.id = cfg["id"]
        self.cfg = cfg
        self.run_cfg = run_cfg
        self.clock = clock
        self.writer = writer
        self.blobs_dir = blobs_dir

        ceiling = cfg["self_imposed_ceiling"]
        self.limiter = SlidingWindowLimiter(ceiling["requests"], ceiling["window_s"])

        self.seq = 0
        self.etag: str | None = None
        self.last_modified: str | None = None
        self.consecutive_429 = 0
        self.stopped_reason: str | None = None
        self.status_counts: collections.Counter[str] = collections.Counter()
        # Actual bytes moved. OVapi is a 5.6 MB payload from a sponsored
        # volunteer service; what we cost them is a number we should know and
        # report, not an estimate.
        self.bytes_wire = 0
        self.bytes_decompressed = 0
        # Request start times, so the manifest can carry the interval we
        # actually achieved rather than the one we configured.
        self.request_starts: list[float] = []

    def _plan_request(self, probe_action: str) -> tuple[str, bool]:
        """Choose the method, and say whether this request exists for its body.

        HEAD mode: Last-Modified, ETag and Content-Length carry the cadence
        signal at zero body cost. gtfs.de ships ~40 MB uncompressed per GET, so
        tracking its ~29s regeneration by GET alone would move several GB an
        hour from a volunteer service. Periodic full GETs still feed the tests
        that need a body, and a Test C re-poll is always a GET because it is
        defined as comparing two.
        """
        method = self.cfg.get("method", "GET").upper()
        every_n = self.cfg.get("full_get_every_n")

        if probe_action.startswith("async_repoll"):
            return "GET", True
        if method == "HEAD" and every_n and (self.seq + 1) % every_n == 0:
            return "GET", True
        return method, False

    def _conditional_headers(self, wants_body: bool) -> tuple[dict, str]:
        """Rotate which validators we send, so we learn which one is honoured.

        Any request whose purpose is to OBTAIN A BODY is exempt: a 304 has
        none, so sending validators does not economise on such a request, it
        defeats it. That covers Test C re-polls and the periodic full GETs that
        punctuate HEAD mode.

        Both cases were observed failing. Run 1 lost Test C on two of three
        feeds because the re-polls returned 304. Run 1b's first scheduled GET
        returned 304 for the same reason -- in HEAD mode every HEAD refreshes
        the stored validator, so a GET asking for a body is certain to be told
        it already has one.
        """
        if wants_body:
            return {}, "none"

        send_inm = self.etag is not None
        send_ims = self.last_modified is not None

        if self.seq % PROBE_IF_NONE_MATCH_ONLY == 0:
            send_ims = False
        elif self.seq % PROBE_IF_MODIFIED_SINCE_ONLY == 0:
            send_inm = False

        headers = {}
        if send_inm:
            headers["If-None-Match"] = self.etag
        if send_ims:
            headers["If-Modified-Since"] = self.last_modified

        if send_inm and send_ims:
            mode = "if-none-match+if-modified-since"
        elif send_inm:
            mode = "if-none-match"
        elif send_ims:
            mode = "if-modified-since"
        else:
            mode = "none"
        return headers, mode

    async def fetch(self, client: httpx.AsyncClient, probe_action: str) -> dict:
        method, wants_body = self._plan_request(probe_action)
        conditional_headers, conditional_mode = self._conditional_headers(wants_body)

        # The joined URL is built here and never recorded. Endpoints reach the
        # manifest split into base_url + redacted query.
        url = self.cfg["base_url"]
        params = self.cfg.get("query") or None


        await self.limiter.acquire()

        self.seq += 1
        started = time.monotonic()
        self.request_starts.append(started)
        record: dict = {
            "feed": self.id,
            "run": self.run_cfg["run"],
            "seq": self.seq,
            "request_at": self.clock.wall(started).isoformat(),
            "conditional": conditional_mode,
            "probe_action": probe_action,
            "clock_offset_ms": self.clock.offset_ms,
            "clock_sync_failed": self.clock.sync_failed,
            "clock_sync_age_s": self.clock.sync_age_s(started),
            "method": method,
            "request_headers": filter_headers(conditional_headers, REQUEST_HEADER_ALLOWLIST),
        }

        try:
            response = await client.request(method, url, params=params, headers=conditional_headers)
            headers_at = time.monotonic()
            body = response.content
            body_at = time.monotonic()

            wire_bytes = getattr(response, "num_bytes_downloaded", None)
            if wire_bytes is None:
                content_length = response.headers.get("content-length")
                wire_bytes = int(content_length) if content_length else None

            record.update({
                "status": response.status_code,
                "http_version": response.http_version,
                "response_at": self.clock.wall(headers_at).isoformat(),
                "body_at": self.clock.wall(body_at).isoformat(),
                "ttfb_ms": round((headers_at - started) * 1000, 3),
                "elapsed_ms": round((body_at - started) * 1000, 3),
                "response_headers": filter_headers(response.headers, RESPONSE_HEADER_ALLOWLIST),
                "body_bytes_wire": wire_bytes,
                "body_bytes_decompressed": len(body) if body else 0,
                "error": None,
            })

            if body:
                digest = hashlib.sha256(body).hexdigest()
                record["body_sha256"] = digest
                blob = self.blobs_dir / f"{digest}.pb"
                if blob.exists():
                    # Already stored: identical bytes cost no extra disk, and
                    # identical-payload detection falls out for free.
                    record["blob_path"] = None
                else:
                    blob.write_bytes(body)
                    record["blob_path"] = f"blobs/{digest}.pb"
            else:
                record["body_sha256"] = None
                record["blob_path"] = None

            self.bytes_wire += wire_bytes or 0
            self.bytes_decompressed += len(body) if body else 0

            if response.status_code == 200:
                self.etag = response.headers.get("etag", self.etag)
                self.last_modified = response.headers.get("last-modified", self.last_modified)

            self.status_counts[str(response.status_code)] += 1

        except Exception as exc:  # noqa: BLE001 -- an error is an observation
            failed_at = time.monotonic()
            record.update({
                "status": None,
                "http_version": None,
                "response_at": None,
                "body_at": None,
                "ttfb_ms": None,
                "elapsed_ms": round((failed_at - started) * 1000, 3),
                "response_headers": {},
                "body_bytes_wire": None,
                "body_bytes_decompressed": None,
                "body_sha256": None,
                "blob_path": None,
                "error": {"class": _classify_error(exc), "detail": f"{type(exc).__name__}: {exc}"},
            })
            self.status_counts["error"] += 1

        await self.writer.write(record)
        return record

    def effective_interval(self) -> float | None:
        """Median achieved interval between request starts.

        The configured value is a sleep after completion. What we actually
        achieved is that plus the fetch duration, and cadence resolution
        depends on the achieved figure, not the configured one.
        """
        if len(self.request_starts) < 3:
            return None
        gaps = [b - a for a, b in zip(self.request_starts, self.request_starts[1:])]
        return round(statistics.median(gaps), 2)

    async def handle_limit_response(self, record: dict) -> bool:
        """Circuit breaker. Returns True if the feed should stop for the run.

        A 429 is evidence -- arguably the most valuable line in the run -- and
        it is already recorded in full by the time we get here. We never retry
        into a limit and we never chase one deliberately.
        """
        status = record.get("status")
        if status not in (403, 429):
            if status is not None and 200 <= status < 400:
                self.consecutive_429 = 0
            return False

        self.consecutive_429 += 1
        new_capacity = self.limiter.halve()
        threshold = self.run_cfg["backoff"]["consecutive_429_to_stop"]

        if status == 403 and self.cfg.get("auth") not in (None, "none"):
            self.stopped_reason = "403 on an authenticated feed"
            return True
        if self.consecutive_429 >= threshold:
            self.stopped_reason = f"{self.consecutive_429} consecutive rate-limit responses"
            return True

        retry_after = record.get("response_headers", {}).get("retry-after")
        if retry_after:
            try:
                delay = float(retry_after)
            except ValueError:
                delay = self.cfg["sleep_after_completion_s"] * 4
        else:
            base = self.cfg["sleep_after_completion_s"]
            delay = min(
                base * (2 ** self.consecutive_429),
                self.run_cfg["backoff"]["cap_seconds"],
            )
        delay *= 0.5 + random.random()  # full jitter

        print(f"[{self.id}] status {status}: backing off {delay:.0f}s, "
              f"ceiling now {new_capacity}/{self.limiter.window:.0f}s")
        await asyncio.sleep(delay)
        return False

    async def run(self, client: httpx.AsyncClient, deadline_mono: float,
                  kill_switch: Path) -> None:
        repoll_marks = list(self.run_cfg["async_repoll"]["at_minutes"]) if self.cfg.get("async_repoll") else []
        gap = self.run_cfg["async_repoll"]["gap_seconds"]

        while time.monotonic() < deadline_mono:
            if kill_switch.exists():
                self.stopped_reason = "kill switch file present"
                break

            elapsed_min = (time.monotonic() - self.clock.t0_mono) / 60.0
            if repoll_marks and elapsed_min >= repoll_marks[0]:
                repoll_marks.pop(0)
                # Test C: two off-grid requests a short gap apart. Both are
                # tagged so the analyser excludes them from the cadence
                # distribution they would otherwise corrupt.
                print(f"[{self.id}] async re-poll pair (Test C)")
                await self.fetch(client, "async_repoll_a")
                await asyncio.sleep(gap)
                record = await self.fetch(client, "async_repoll_b")
            else:
                record = await self.fetch(client, "scheduled")

            if await self.handle_limit_response(record):
                print(f"[{self.id}] stopping for the run: {self.stopped_reason}")
                break

            await asyncio.sleep(self.cfg["sleep_after_completion_s"])

        print(f"[{self.id}] done: {self.seq} requests, "
              f"{self.bytes_wire / 1e6:.1f} MB over the wire, "
              f"statuses {dict(self.status_counts)}")


ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def keep_awake(enable: bool) -> bool | None:
    """Ask Windows not to sleep while a run is in flight.

    The request lives only as long as this process and changes no system
    setting, so it needs no cleanup beyond releasing it. Without this a machine
    whose standby timeout is shorter than the run silently truncates it, and an
    hour of polite polling against volunteer-run feeds is wasted.

    Returns True if asserted, False if the call failed, None if not applicable.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        state = ES_CONTINUOUS | ES_SYSTEM_REQUIRED if enable else ES_CONTINUOUS
        return bool(ctypes.windll.kernel32.SetThreadExecutionState(state))
    except Exception:  # noqa: BLE001
        return False


def _classify_error(exc: Exception) -> str:
    if isinstance(exc, httpx.ConnectTimeout):
        return "connect_timeout"
    if isinstance(exc, httpx.ReadTimeout):
        return "read_timeout"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "connect"
    if isinstance(exc, httpx.TransportError):
        return "transport"
    return "other"


def validate(cfg: dict) -> None:
    """Refuse to start on anything that would produce dishonest evidence."""
    problems = []

    if "<contact>" in cfg.get("user_agent", ""):
        problems.append(
            "user_agent still contains the <contact> placeholder. gtfs.de is a free "
            "community service; set a real contact address before polling it."
        )

    seen_ids: set[str] = set()
    for feed in cfg["feeds"]:
        feed_id = feed["id"]

        # One endpoint, one feed id, one verdict. Two entries sharing an id
        # would interleave two message streams into a single observation set,
        # and every timestamp test assumes one feed is one message stream --
        # tripUpdates and vehiclePositions can stamp differently. The verdict
        # would be garbage and would look plausible.
        if feed_id in seen_ids:
            problems.append(
                f"duplicate feed id '{feed_id}'. Two endpoints must never share an id: "
                "their message streams would merge into one verdict."
            )
        seen_ids.add(feed_id)

        base_url = feed.get("base_url")
        if not base_url:
            problems.append(
                f"feed '{feed_id}' has no base_url. Resolve it at preflight from the "
                "provider's own documentation -- do not invent a plausible URL."
            )
        elif not isinstance(base_url, str):
            problems.append(
                f"feed '{feed_id}' has a non-string base_url. One feed polls exactly one "
                "endpoint; give each endpoint its own feed id instead."
            )
        if not feed.get("self_imposed_ceiling"):
            problems.append(f"feed '{feed_id}' has no self_imposed_ceiling.")

    if problems:
        print("Refusing to start:\n", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}\n", file=sys.stderr)
        sys.exit(2)


def write_manifest(path: Path, cfg: dict, clock: ClockRef, probes: list[FeedProbe],
                   status: str, observation_count: int) -> None:
    """Run manifest. Endpoints split and redacted -- never a joined URL."""
    manifest = {
        "run": cfg["run"],
        "status": status,
        "started_at": clock.t0_wall.isoformat(),
        "ended_at": clock.wall(time.monotonic()).isoformat(),
        "observation_count": observation_count,
        "user_agent": cfg["user_agent"],
        "clock": {
            "ntp_server": ClockRef.NTP_SERVER,
            "syncs": clock.syncs,
            "note": "Offsets are recorded, not applied. null means sync failed; never read as zero.",
        },
        "platform": {
            "python": sys.version,
            "platform": sys.platform,
            "sleep_suppressed": keep_awake(True),
        },
        "feeds": [
            {
                "id": probe.id,
                "base_url": probe.cfg["base_url"],
                "query": redact_query(probe.cfg.get("query")),
                "auth": probe.cfg.get("auth"),
                # Configured value is a sleep AFTER each request completes, so
                # the achieved interval is fetch duration + this, never this
                # alone. Run 1 configured 5s against gtfs.de and achieved ~22s,
                # because each 40 MB fetch took 12-27s. Both are recorded; the
                # measured one is what any cadence claim must be judged against.
                "sleep_after_completion_s": probe.cfg["sleep_after_completion_s"],
                "effective_interval_s": probe.effective_interval(),
                "documented_limit": probe.cfg.get("documented_limit"),
                "self_imposed_ceiling": probe.cfg["self_imposed_ceiling"],
                "requests_made": probe.seq,
                "bytes_wire_total": probe.bytes_wire,
                "bytes_decompressed_total": probe.bytes_decompressed,
                "status_counts": dict(probe.status_counts),
                "stopped_reason": probe.stopped_reason,
                "final_ceiling_requests": probe.limiter.capacity,
                "notes": probe.cfg.get("notes"),
            }
            for probe in probes
        ],
    }
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


async def main(config_path: Path) -> int:
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    validate(cfg)

    out_dir = Path(cfg["output_root"]) / cfg["run"]
    blobs_dir = out_dir / "blobs"
    blobs_dir.mkdir(parents=True, exist_ok=True)
    kill_switch = Path(cfg["kill_switch_file"])

    clock = ClockRef()
    clock.sync("start")

    writer = ObservationWriter(out_dir / "observations.jsonl")
    probes = [FeedProbe(feed, cfg, clock, writer, blobs_dir) for feed in cfg["feeds"]]
    manifest_path = out_dir / "run.json"
    write_manifest(manifest_path, cfg, clock, probes, "running", 0)

    duration_s = cfg["duration_minutes"] * 60
    deadline = clock.t0_mono + duration_s

    headers = {
        "User-Agent": cfg["user_agent"],
        "Accept-Encoding": cfg["accept_encoding"],
    }
    timeout = httpx.Timeout(cfg["timeouts"]["total_s"], connect=cfg["timeouts"]["connect_s"])

    print(f"[run] {cfg['run']}: {len(probes)} feeds for {cfg['duration_minutes']} min")
    print(f"[run] kill switch: create '{kill_switch}' to halt cleanly")

    awake = keep_awake(True)
    print(f"[run] sleep suppression: {'asserted' if awake else awake}")

    status = "complete"
    try:
        async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True) as client:
            mid = asyncio.create_task(_sync_at(clock, duration_s / 2))
            await asyncio.gather(*(probe.run(client, deadline, kill_switch) for probe in probes))
            mid.cancel()
    except KeyboardInterrupt:
        status = "interrupted"
        print("\n[run] interrupted; captured data is intact")
    finally:
        keep_awake(False)
        clock.sync("end")
        write_manifest(manifest_path, cfg, clock, probes, status, writer.count)
        writer.close()

    print(f"[run] {writer.count} observations -> {out_dir / 'observations.jsonl'}")
    print(f"[run] manifest -> {manifest_path}")
    return 0


async def _sync_at(clock: ClockRef, delay_s: float) -> None:
    try:
        await asyncio.sleep(delay_s)
        clock.sync("mid")
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    try:
        sys.exit(asyncio.run(main(Path(sys.argv[1]))))
    except KeyboardInterrupt:
        sys.exit(130)

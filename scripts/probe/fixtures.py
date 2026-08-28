"""SYNTHETIC fixture generator — produces feeds whose correct answers are known.

NOTHING HERE IS MEASURED. Every number this produces is manufactured to test
the analyser, and the run manifest it writes carries `"synthetic": true` so the
analyser labels its output unmistakably. `docs/metrics.md` holds measured
numbers only; nothing from here may ever be copied into it.

Six feeds, six known answers. The turnover cases exist because two earlier
versions of the id-stability measure were wrong in ways only they expose:

  fake_generation    header ts = real generation time; ids REGENERATE
  fake_echo          header ts = request time; ids stable
  fake_static        VBB-shaped: real stamping, near-empty unchanging content.
                     Test A must be marked unavailable, not misread as echo.
  turnover15_stable  stable ids, ~14% entity turnover  -> stable
  turnover40_stable  stable ids, 40% turnover. Jaccard persistence is 0.43,
                     BELOW the absolute 0.5 threshold an earlier version used,
                     which called perfectly stable ids "regenerating".
  turnover15_regen   regenerating ids at the same turnover as turnover15_stable.
                     Identical semantic persistence; only the ratio separates
                     them.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

from google.transit import gtfs_realtime_pb2

T0 = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)
CADENCE = 20
POLL = 5
DURATION = 600
REPOLL_AT = [120, 380]

SYNTHETIC_WARNING = (
    "SYNTHETIC FIXTURE DATA - NOT MEASURED. Generated to verify the analyser "
    "against known ground truth. Describes no real feed. Never copy into docs/metrics.md."
)


def build(gen_epoch: int, n_entities: int, changing: int,
          regenerate_ids: bool, turnover: int = 0, cadence: int = CADENCE):
    """turnover = entities entering and leaving per generation (sliding window).

    A stable-id feed with turnover fraction f has Jaccard persistence
    (1-f)/(1+f): 0.74 at f=0.15, 0.43 at f=0.40.
    """
    message = gtfs_realtime_pb2.FeedMessage()
    message.header.gtfs_realtime_version = "2.0"
    message.header.incrementality = gtfs_realtime_pb2.FeedHeader.FULL_DATASET
    message.header.timestamp = gen_epoch

    window_start = (gen_epoch // cadence) * turnover
    for offset in range(n_entities):
        index = window_start + offset
        entity = message.entity.add()
        entity.id = f"{gen_epoch}-{offset}" if regenerate_ids else f"ent-{index}"
        trip_update = entity.trip_update
        trip_update.trip.trip_id = f"trip-{index}"
        trip_update.trip.start_date = "20260828"
        if offset < changing:
            trip_update.timestamp = gen_epoch - 2
        stop_time = trip_update.stop_time_update.add()
        stop_time.stop_sequence = 1
        stop_time.arrival.delay = (gen_epoch // cadence) % 7 if offset < changing else 0
    return message


def emit(feed: str, mode: str, n_entities: int, changing: int, regenerate_ids: bool,
         records: list, blobs: Path, seq_start: int, turnover: int = 0,
         cadence: int = CADENCE, poll: int = POLL) -> int:
    seq = seq_start
    elapsed = 0.0
    repolls = list(REPOLL_AT)

    while elapsed < DURATION:
        actions = [("scheduled", elapsed)]
        if repolls and elapsed >= repolls[0]:
            repolls.pop(0)
            actions = [("async_repoll_a", elapsed), ("async_repoll_b", elapsed + 2)]

        for action, at in actions:
            requested = T0 + timedelta(seconds=at)
            gen_epoch = int((T0 + timedelta(seconds=(int(at) // cadence) * cadence)).timestamp())
            message = build(gen_epoch, n_entities, changing, regenerate_ids, turnover, cadence)
            if mode == "echo":
                message.header.timestamp = int(requested.timestamp())

            raw = message.SerializeToString()
            digest = hashlib.sha256(raw).hexdigest()
            blob = blobs / f"{digest}.pb"
            if not blob.exists():
                blob.write_bytes(raw)

            seq += 1
            records.append({
                "feed": feed, "run": "synthetic-fixture", "seq": seq,
                "request_at": requested.isoformat(),
                "response_at": (requested + timedelta(milliseconds=80)).isoformat(),
                "body_at": (requested + timedelta(milliseconds=100)).isoformat(),
                "ttfb_ms": 80.0, "elapsed_ms": 100.0,
                "status": 200, "http_version": "HTTP/2",
                "conditional": "if-none-match+if-modified-since" if seq > seq_start + 1 else "none",
                "probe_action": action,
                "clock_offset_ms": -8.0, "clock_sync_failed": False, "clock_sync_age_s": 120.0,
                "request_headers": {},
                "response_headers": {
                    "etag": f'"{digest[:12]}"',
                    "last-modified": format_datetime(
                        datetime.fromtimestamp(gen_epoch, timezone.utc), usegmt=True),
                    "date": format_datetime(requested, usegmt=True),
                    "content-type": "application/octet-stream",
                    "content-length": str(len(raw)),
                },
                "body_sha256": digest, "blob_path": f"blobs/{digest}.pb",
                "body_bytes_wire": len(raw), "body_bytes_decompressed": len(raw),
                "error": None,
            })
        elapsed += poll
    return seq


#: feed id -> (mode, entities, changing, regenerate_ids, turnover, cadence_s, poll_s)
#
# fast_cadence regenerates every 2s, which violates the preconditions of two
# tests at once and must make both stand down rather than vote:
#   Test B -- an integer-second timestamp gives a 2s sawtooth about two
#             quantisation levels, which has no characterisable shape.
#   Test C -- the 2s re-poll gap is not shorter than the cadence, so the pair
#             spans real generations and their honest advance is
#             indistinguishable from restamping. This produced a false `echo`
#             on hsl_vehiclepositions that outvoted two correct tests.
#
# undersampled_fast regenerates as fast as we poll, so its cadence cannot be
# resolved -- the deltas that come back are our sampling grid. It must be
# flagged regardless of the header-timestamp verdict, which is `generation`.
FEEDS = {
    "fake_generation":   ("generation", 50, 15, True, 0, 20, 5),
    "fake_echo":         ("echo", 50, 15, False, 0, 20, 5),
    "fake_static":       ("generation", 3, 0, False, 0, 20, 5),
    "turnover15_stable": ("generation", 50, 15, False, 7, 20, 5),
    "turnover40_stable": ("generation", 50, 15, False, 20, 20, 5),
    "turnover15_regen":  ("generation", 50, 15, True, 7, 20, 5),
    "undersampled_fast": ("generation", 50, 15, False, 0, 5, 5),
    "fast_cadence":      ("generation", 50, 15, False, 0, 2, 1),
}


def build_synthetic_run(root: Path) -> Path:
    """Write a complete synthetic run directory. Returns the run directory."""
    run_dir = root / "synthetic-fixture"
    blobs = run_dir / "blobs"
    blobs.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    seq = 0
    for feed, (mode, entities, changing, regenerate, turnover, cadence, poll) in FEEDS.items():
        seq = emit(feed, mode, entities, changing, regenerate, records, blobs, seq,
                   turnover, cadence, poll)

    (run_dir / "observations.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
    (run_dir / "run.json").write_text(json.dumps({
        "run": "synthetic-fixture",
        "synthetic": True,
        "warning": SYNTHETIC_WARNING,
        "status": "complete",
        "clock": {"ntp_server": None, "syncs": [], "note": SYNTHETIC_WARNING},
        "feeds": [{"id": feed, "sleep_after_completion_s": cfg[6], "effective_interval_s": cfg[6]}
                  for feed, cfg in FEEDS.items()],
    }, indent=2), encoding="utf-8")
    return run_dir


if __name__ == "__main__":
    import sys
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "runs")
    written = build_synthetic_run(target)
    print(f"{SYNTHETIC_WARNING}\nwritten -> {written}")

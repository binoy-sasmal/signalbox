"""The ingest run: poller thread, bounded queue, writer thread, run report.

Gate 5's verification is one hour against the live feed, recording parse failure
rate, duplicate rate and bytes saved by conditional requests. Those numbers come
out of the counters here and out of Postgres, and are compared against predictions
written down before the run.

No Prometheus client and no /metrics endpoint: observability is Gate 7's decision
and importing a metrics library now would pre-empt it. Counters plus a structured
JSON report, the same discipline as Stage 0's run.json.
"""
from __future__ import annotations

import argparse
import ctypes
import datetime
import json
import os
import statistics
import sys
import threading
import time

from . import config
from .churn import ChurnTracker
from .decode import decode
from .dropqueue import DEFAULT_DEPTH, DropOldestQueue
from .poller import FixedRateTicker, Poller
from .store import Store

#: Run 2 of the Stage 0 probe slept for 56 of 60 minutes and still reported
#: `complete`. Detecting that afterwards by inspection is not a control; refusing
#: to call the run complete is. Same threshold, same reason.
MIN_COVERAGE = 0.90

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

#: Every terminal outcome a fetch can reach, and which of them are failures.
#:
#: This taxonomy is explicit, and `dropped` is in the failure set, because ADR
#: 0010's rule turns on exactly that membership: a drop policy whose drops are not
#: failures launders errors out of the error budget, and the fastest route to a
#: green SLI 1 at Gate 8 becomes a more aggressive drop policy. Written as data so
#: a test can assert the membership rather than a comment claiming it.
OUTCOMES = (
    "persisted",        # decoded and written
    "not_modified",     # 304 -- a success, and the point of conditional requests
    "dropped",          # evicted from the bounded queue (ADR 0010)
    "transport_error",
    "write_failed",
    "decode_not_protobuf",
    "decode_parse_error",
    "decode_wrong_schema",
    "decode_empty_body",
    "decode_valid_but_empty",
)

FAILURE_OUTCOMES = frozenset({
    "dropped",
    "transport_error",
    "write_failed",
    "decode_not_protobuf",
    "decode_parse_error",
    "decode_wrong_schema",
    "decode_empty_body",
})

DROP_OUTCOME = "dropped"
DROP_REASON = "evicted from the bounded queue by a newer snapshot"


def is_failure(outcome: str) -> bool:
    """Does this outcome consume error budget? Gate 8's SLI 1 reads this."""
    return outcome in FAILURE_OUTCOMES


def record_drop(store, fetch_id: int) -> str:
    """Mark an evicted fetch as the pipeline failure it is. Returns the outcome."""
    store.finalise_fetch(
        fetch_id,
        outcome=DROP_OUTCOME,
        error=DROP_REASON,
        committed_at=datetime.datetime.now(datetime.timezone.utc),
    )
    return DROP_OUTCOME


def keep_awake(enable: bool) -> bool | None:
    """Ask Windows not to sleep. Recorded as REQUESTED, never as achieved.

    Stage 0 run 2 proved those are different things: the call succeeded and the
    machine suspended anyway. The coverage check is what actually protects the run.
    """
    if sys.platform != "win32":
        return None
    try:
        state = ES_CONTINUOUS | ES_SYSTEM_REQUIRED if enable else ES_CONTINUOUS
        return bool(ctypes.windll.kernel32.SetThreadExecutionState(state))
    except Exception:
        return None


class Counters:
    def __init__(self) -> None:
        self.ticks_fired = 0
        self.ticks_skipped = 0
        self.requests = 0
        self.status_counts: dict[str, int] = {}
        self.transport_errors = 0
        self.decode_classes: dict[str, int] = {}
        self.false_200 = 0
        self.bodies = 0
        self.body_bytes_total = 0
        self.entities_presented = 0
        self.entities_written = 0
        self.entities_suppressed = 0
        self.entities_without_identity = 0
        self.snapshots_persisted = 0
        self.write_failures = 0
        # The first snapshot writes every entity because the table is empty. It
        # is a real write and stays in the totals, but it is not comparable to a
        # churn figure, which is defined between consecutive snapshots.
        self.cold_start_presented = 0
        self.cold_start_written = 0
        self.request_starts: list[float] = []
        self.fetch_ms: list[float] = []
        self.body_sizes: list[int] = []

    def bump(self, mapping: dict, key) -> None:
        mapping[str(key)] = mapping.get(str(key), 0) + 1


def writer_loop(queue: DropOldestQueue, store: Store, counters: Counters,
                churn: ChurnTracker, stop: threading.Event) -> None:
    """Decode, dedup and persist. One thread, so writes are serialised by design."""
    while True:
        item = queue.get(timeout=0.5)
        if item is None:
            if stop.is_set() and len(queue) == 0:
                return
            continue

        fetch_id, body = item
        result = decode(body)
        counters.bump(counters.decode_classes, result.status)

        fields = {
            "decode_status": result.status,
            "header_timestamp": result.header_timestamp,
            "entity_count": len(result.entities),
        }
        try:
            if result.status == "ok":
                persisted = store.persist_entities(fetch_id, result.entities)
                churn.observe(persisted["by_semantic"], persisted["by_entity_id"])
                if counters.snapshots_persisted == 0:
                    counters.cold_start_presented = persisted["presented"]
                    counters.cold_start_written = persisted["written"]
                counters.entities_presented += persisted["presented"]
                counters.entities_written += persisted["written"]
                counters.entities_suppressed += persisted["suppressed"]
                counters.entities_without_identity += persisted["entities_without_identity"]
                counters.snapshots_persisted += 1
                fields["entities_written"] = persisted["written"]
                fields["entities_suppressed"] = persisted["suppressed"]
                fields["outcome"] = "persisted"
            else:
                fields["outcome"] = f"decode_{result.status}"
                fields["error"] = result.detail
            fields["committed_at"] = datetime.datetime.now(datetime.timezone.utc)
            store.finalise_fetch(fetch_id, **fields)
        except Exception as exc:  # a write that fails is a pipeline failure, counted
            counters.write_failures += 1
            store.conn.rollback()
            try:
                store.finalise_fetch(
                    fetch_id, outcome="write_failed", error=f"{type(exc).__name__}: {exc}",
                    committed_at=datetime.datetime.now(datetime.timezone.utc),
                )
            except Exception:
                pass


def assess_coverage(starts: list[float], duration_s: float, interval_s: float) -> dict:
    """Fraction of the intended window we were actually polling."""
    if len(starts) < 2:
        return {"coverage": 0.0, "reason": "fewer than two requests"}
    threshold = max(60.0, interval_s * 6)
    gaps = [b - a for a, b in zip(starts, starts[1:]) if b - a > threshold]
    lost = sum(gaps)
    covered = max(0.0, (starts[-1] - starts[0]) - lost)
    return {
        "coverage": round(covered / duration_s, 4) if duration_s else 0.0,
        "polling_seconds": round(covered, 1),
        "lost_seconds": round(lost, 1),
        "gap_threshold_s": threshold,
        "gap_count": len(gaps),
        "largest_gap_s": round(max(gaps), 1) if gaps else 0.0,
        "minimum_required": MIN_COVERAGE,
    }


def run(tenant, dsn: str, duration_s: float, depth: int, report_path: str) -> int:
    # One connection per thread, deliberately. A psycopg connection serialises
    # concurrent use but shares one transaction, so a commit from either thread
    # would commit the other's half-finished work.
    store = Store(dsn, tenant.db_schema)
    writer_store = Store(dsn, tenant.db_schema)
    poller = Poller(tenant.base_url, tenant.query)
    queue = DropOldestQueue(depth)
    counters = Counters()
    churn = ChurnTracker()
    stop = threading.Event()

    writer = threading.Thread(
        target=writer_loop, args=(queue, writer_store, counters, churn, stop),
        name="ingest-writer", daemon=True,
    )
    writer.start()

    awake = keep_awake(True)
    started_at = time.time()
    ticker = FixedRateTicker(tenant.poll_interval_s, started_at)
    previous_body_hash: str | None = None
    deadline = started_at + duration_s

    print(f"[run] tenant={tenant.name} interval={tenant.poll_interval_s}s "
          f"depth={depth} duration={duration_s:.0f}s")
    print(f"[run] sleep suppression requested={awake} "
          "(not a guarantee -- coverage is checked at the end)")

    try:
        while time.time() < deadline:
            counters.ticks_fired += 1
            record = poller.fetch()
            counters.requests += 1
            counters.request_starts.append(record.requested_at)
            if record.elapsed_ms is not None:
                counters.fetch_ms.append(record.elapsed_ms)

            if record.error:
                counters.transport_errors += 1
                outcome = "transport_error"
            elif record.status == 200:
                counters.bodies += 1
                counters.body_bytes_total += record.body_bytes
                counters.body_sizes.append(record.body_bytes)
                if previous_body_hash and record.body_sha256 == previous_body_hash:
                    counters.false_200 += 1
                previous_body_hash = record.body_sha256
                outcome = "queued"
            elif record.status == 304:
                outcome = "not_modified"
            else:
                outcome = f"unexpected_{record.status}"
            if record.status is not None:
                counters.bump(counters.status_counts, record.status)

            fetch_id = store.record_fetch({
                "requested_at": _utc(record.requested_at),
                "responded_at": _utc(record.responded_at),
                "status": record.status,
                "conditional_mode": record.conditional_mode,
                "etag": record.headers.get("etag"),
                "last_modified": record.headers.get("last-modified"),
                "body_sha256": record.body_sha256,
                "body_bytes": record.body_bytes or None,
                "outcome": outcome,
                "error": record.error,
            })

            if record.body is not None:
                evicted = queue.put((fetch_id, record.body))
                if evicted is not None:
                    # ADR 0010: a drop is a pipeline failure, not a silent success.
                    record_drop(store, evicted[0])
                    print(f"[run] DROPPED fetch {evicted[0]} -- queue full at depth {depth}")

            target, skipped = ticker.next_tick(time.time())
            counters.ticks_skipped += skipped
            if skipped:
                print(f"[run] skipped {skipped} tick(s): fetch outlasted the interval")
            sleep_for = target - time.time()
            if sleep_for > 0:
                time.sleep(min(sleep_for, max(0.0, deadline - time.time())))
    except KeyboardInterrupt:
        print("[run] interrupted")
    finally:
        ended_at = time.time()
        stop.set()
        queue.close()
        writer.join(timeout=120)
        poller.close()
        keep_awake(False)

    report = build_report(tenant, counters, churn, queue, started_at, ended_at,
                          duration_s, depth, awake)
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=1)
        handle.write("\n")
    store.close()
    writer_store.close()

    coverage = report["coverage"]["coverage"]
    print(f"[run] coverage {coverage:.1%} of the intended window")
    print(f"[run] report written to {report_path}")
    if coverage < MIN_COVERAGE:
        print(f"[run] DEGRADED -- coverage {coverage:.1%} below the {MIN_COVERAGE:.0%} "
              "minimum. No number from this run is usable.", file=sys.stderr)
        return 1
    return 0


def build_report(tenant, counters, churn, queue, started_at, ended_at,
                 duration_s, depth, awake) -> dict:
    elapsed = ended_at - started_at
    gaps = [b - a for a, b in zip(counters.request_starts, counters.request_starts[1:])]
    mean_body = statistics.mean(counters.body_sizes) if counters.body_sizes else 0

    # Bytes saved is only meaningful against a stated poll interval: at an interval
    # equal to the cadence the saving is ~0 by construction. The counterfactual is
    # every request returning a body of the mean observed size.
    counterfactual = counters.requests * mean_body

    return {
        "tenant": tenant.name,
        "gate": 5,
        "started_at": _iso(started_at),
        "ended_at": _iso(ended_at),
        "elapsed_s": round(elapsed, 1),
        "intended_duration_s": duration_s,
        "config": {
            "poll_interval_s": tenant.poll_interval_s,
            "queue_depth": depth,
            "db_schema": tenant.db_schema,
            "incrementality": tenant.incrementality,
            "scheduling": "fixed-rate, single-flight, skip missed ticks (ADR 0005)",
            "backpressure": "drop oldest (ADR 0010)",
        },
        "platform": {
            "python": sys.version,
            "platform": sys.platform,
            "sleep_suppression_requested": awake,
        },
        "coverage": assess_coverage(counters.request_starts, duration_s,
                                    tenant.poll_interval_s),
        "scheduling": {
            "ticks_fired": counters.ticks_fired,
            "ticks_skipped": counters.ticks_skipped,
            "skip_rate": _ratio(counters.ticks_skipped,
                                counters.ticks_fired + counters.ticks_skipped),
            "configured_interval_s": tenant.poll_interval_s,
            "achieved_interval_s": {
                "mean": _round(statistics.mean(gaps) if gaps else None, 3),
                "p50": _round(statistics.median(gaps) if gaps else None, 3),
                "min": _round(min(gaps) if gaps else None, 3),
                "max": _round(max(gaps) if gaps else None, 3),
            },
            "note": "Achieved is measured, never inferred from configuration (ADR 0005).",
        },
        "http": {
            "requests": counters.requests,
            "status_counts": counters.status_counts,
            "transport_errors": counters.transport_errors,
            "fetch_ms": _distribution(counters.fetch_ms),
        },
        "conditional_requests": {
            "bodies_returned": counters.bodies,
            "not_modified": counters.status_counts.get("304", 0),
            "not_modified_rate": _ratio(counters.status_counts.get("304", 0),
                                        counters.requests),
            "false_200": counters.false_200,
            "false_200_rate": _ratio(counters.false_200, counters.bodies),
            "mean_body_bytes": round(mean_body),
            "bytes_transferred": counters.body_bytes_total,
            "bytes_counterfactual_no_validators": round(counterfactual),
            "bytes_saved": round(counterfactual - counters.body_bytes_total),
            "bytes_saved_fraction": _ratio(counterfactual - counters.body_bytes_total,
                                           counterfactual),
            "note": ("Only meaningful against the stated poll interval: at an interval "
                     "equal to the cadence the saving is ~0 by construction."),
        },
        "parse": {
            "classes": counters.decode_classes,
            "failures": sum(count for name, count in counters.decode_classes.items()
                            if name not in ("ok",)),
            "failure_rate": _ratio(
                sum(count for name, count in counters.decode_classes.items()
                    if name not in ("ok",)),
                sum(counters.decode_classes.values()),
            ),
        },
        "dedup": {
            "entities_presented": counters.entities_presented,
            "entities_written": counters.entities_written,
            "entities_suppressed": counters.entities_suppressed,
            "suppression_rate": _ratio(counters.entities_suppressed,
                                       counters.entities_presented),
            "suppression_rate_steady_state": _ratio(
                counters.entities_suppressed,
                counters.entities_presented - counters.cold_start_presented),
            "cold_start_presented": counters.cold_start_presented,
            "cold_start_written": counters.cold_start_written,
            "entities_without_identity": counters.entities_without_identity,
            "snapshots_persisted": counters.snapshots_persisted,
            "churn_median_semantic": _round(
                statistics.median(churn.semantic) if churn.semantic else None, 4),
            "churn_median_entity_id": _round(
                statistics.median(churn.entity_id) if churn.entity_id else None, 4),
            "churn_comparisons": len(churn.semantic),
            "note": ("Both keyings are measured. Stage 0 found them capable of "
                     "disagreeing; a disagreement that stops being measured becomes "
                     "an assumption."),
        },
        "pipeline_outcomes": {
            "failures": queue.dropped + counters.transport_errors + counters.write_failures
                        + sum(count for name, count in counters.decode_classes.items()
                              if is_failure(f"decode_{name}")),
            "failure_outcomes": sorted(FAILURE_OUTCOMES),
            "note": ("Gate 8's SLI 1 reads this taxonomy. `dropped` is a failure by "
                     "ADR 0010, so a drop policy cannot launder errors out of the "
                     "error budget."),
        },
        "backpressure": {
            "queue_depth": depth,
            "dropped": queue.dropped,
            "high_water": queue.high_water,
            "write_failures": counters.write_failures,
            "note": ("Drops are pipeline failures, not silent successes (ADR 0010). "
                     "Expected zero here; a non-zero count is a finding."),
        },
    }


def _utc(epoch: float | None):
    if epoch is None:
        return None
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc)


def _iso(epoch: float) -> str:
    return _utc(epoch).isoformat()


def _ratio(numerator, denominator):
    if not denominator:
        return None
    return round(numerator / denominator, 4)


def _round(value, digits):
    return None if value is None else round(value, digits)


def _distribution(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "p50": round(statistics.median(ordered), 1),
        "p95": round(ordered[int(0.95 * (len(ordered) - 1))], 1),
        "max": round(max(ordered), 1),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Signalbox ingest service (Gate 5)")
    parser.add_argument("tenant", help="path to tenants/<name>.yaml")
    parser.add_argument("--duration-s", type=float, required=True)
    parser.add_argument("--report", required=True, help="where to write the JSON run report")
    parser.add_argument("--queue-depth", type=int, default=DEFAULT_DEPTH)
    args = parser.parse_args(argv[1:])

    dsn = os.environ.get("SIGNALBOX_DSN")
    if not dsn:
        print("SIGNALBOX_DSN is not set", file=sys.stderr)
        return 2

    tenant = config.load(args.tenant)
    return run(tenant, dsn, args.duration_s, args.queue_depth, args.report)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

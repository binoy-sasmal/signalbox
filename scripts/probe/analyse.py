"""Stage 0 feed probe -- analyser.

Runs offline over captured evidence. Everything here is re-runnable at zero
cost, which is why the poller stores raw payloads and raw allow-listed headers
rather than pre-computed summaries: we do not yet know every question we will
want to ask.

Usage:
    python analyse.py runs/run1
"""

from __future__ import annotations

import collections
import hashlib
import json
import platform
import statistics
import sys
import tracemalloc
from datetime import datetime
from pathlib import Path

import psutil
from google.transit import gtfs_realtime_pb2

# --- Test B thresholds -------------------------------------------------------
# Real generation time gives a sawtooth: lag grows as a snapshot ages and drops
# when a new one lands, so it is roughly uniform on [0, cadence] and
# stdev(lag)/cadence approaches 1/sqrt(12) = 0.289. Echoed serve time gives a
# flat band at roughly network RTT, so the ratio approaches zero.
# Clock offset is a constant bias and does not affect the ratio.
B_RATIO_GENERATION = 0.15
B_RATIO_ECHO = 0.05
# B has preconditions of its own, and both were violated by a live feed before
# they were checked. GTFS-RT header timestamps are integer seconds, so lag is
# quantised to 1s: on a 2s-cadence feed the sawtooth occupies about two levels
# and its shape is not characterisable at all. And the model puts lag in
# [0, cadence] -- a median lag ABOVE the cadence means we are measuring a
# producer's own pipeline delay, not the ageing of a snapshot, so the ratio
# describes nothing. Derived from the test, not tuned to a feed.
B_MIN_CADENCE_QUANTA = 5.0
HEADER_TIMESTAMP_RESOLUTION_S = 1.0

# --- Test C tolerance --------------------------------------------------------
# Timestamps differing by roughly the re-poll gap, and tracking our request
# times, is echo behaviour observed directly.
C_GAP_TOLERANCE_S = 1.0
# C compares two fetches of THE SAME snapshot, so the re-poll gap must be
# comfortably shorter than the cadence. On hsl_vehiclepositions -- 1-2s cadence,
# 2.4s gap -- the pair straddled real generations and C returned a false `echo`,
# outvoting two tests that were right. Same class as Test A on static content:
# when a test's discriminating assumption is violated it must stand down, not
# vote.
C_MAX_GAP_FRACTION_OF_CADENCE = 0.5

# --- Test D ------------------------------------------------------------------
D_MIN_ENTITY_TS_COVERAGE = 0.5
D_STAIRCASE_MIN_STEPS = 3

# --- Test E ------------------------------------------------------------------
# Relative, not absolute. An absolute tolerance threw away a discriminating
# result on gtfs.de in run 1: Last-Modified was 3.0s off the header timestamp
# and Date was 8.5s off -- a clear lean toward generation stamping -- but both
# exceeded a fixed 2s cut and the test returned unavailable. What matters is
# which reference is closer, and by how much.
E_SEPARATION_RATIO = 2.0
# Floor, by the same argument as the persistence denominator floor: when both
# references sit within a second of the header timestamp, the comparison is
# noise and the honest answer is unavailable, not a verdict off sub-second jitter.
E_NOISE_FLOOR_S = 1.0

# --- Nyquist guard -----------------------------------------------------------
# A cadence shorter than twice the interval we actually achieved cannot be
# resolved -- what comes back is our own sampling grid. Independent of the
# header-timestamp verdict: undersampling and echo stamping are different ways
# for a cadence figure to be meaningless.
NYQUIST_FACTOR = 2.0
GRID_TOLERANCE = 0.15
GRID_FRACTION = 0.8

# --- entity.id stability -----------------------------------------------------
# Verdict is taken on id_persistence / semantic_persistence, which is invariant
# to entity turnover. The floor exists because that ratio is unstable when both
# terms are small -- the far-apart-snapshot case that motivated it. Below the
# floor the answer is indeterminate, not a number. See ADR 0004.
ID_STABILITY_RATIO_STABLE = 0.8
ID_STABILITY_RATIO_REGENERATING = 0.2
ID_STABILITY_DENOMINATOR_FLOOR = 0.2


def parse_iso(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def load(run_dir: Path) -> tuple[dict, list[dict]]:
    manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    observations = [
        json.loads(line)
        for line in (run_dir / "observations.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return manifest, observations


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------

def classify_payload(raw: bytes) -> tuple[str, object]:
    """Return (classification, FeedMessage or None).

    Failure classes matter more than a failure rate: an HTML error page and a
    truncated protobuf are different upstream problems with different fixes.
    """
    head = raw[:512].lstrip().lower()
    if head.startswith(b"<") or b"<html" in head:
        return "not_protobuf_html", None
    if head.startswith(b"{"):
        return "not_protobuf_json", None

    message = gtfs_realtime_pb2.FeedMessage()
    try:
        message.ParseFromString(raw)
    except Exception:  # noqa: BLE001
        return "parse_error", None

    if not message.header.gtfs_realtime_version:
        # protobuf will happily accept bytes that decode to an empty message.
        return "decoded_but_no_header", None
    if not message.entity:
        return "valid_but_empty", message
    return "ok", message


def modulo_timestamp_hash(message) -> str:
    """Content hash with the header timestamp zeroed.

    Test A rests entirely on this: identical content under a differing header
    timestamp means the producer restamped an unchanged snapshot.
    """
    copy = gtfs_realtime_pb2.FeedMessage()
    copy.CopyFrom(message)
    copy.header.timestamp = 0
    return hashlib.sha256(copy.SerializeToString(deterministic=True)).hexdigest()


def entity_semantic_key(entity):
    """Semantic identity of an entity, independent of FeedEntity.id.

    FeedEntity.id is scoped to uniqueness *within a FeedMessage* for
    incrementality purposes. A compliant FULL_DATASET producer may regenerate
    it every snapshot, so churn keyed on it alone would report ~100% on a
    perfectly stable feed and produce a wrong "dedup is impossible" finding.
    """
    if entity.HasField("trip_update"):
        trip = entity.trip_update.trip
        return ("trip_update", trip.trip_id, trip.start_date)
    if entity.HasField("vehicle"):
        return ("vehicle", entity.vehicle.vehicle.id)
    if entity.HasField("alert"):
        return None  # no natural semantic key
    return None


def entity_payload(entity) -> bytes:
    """Entity bytes with id cleared.

    Both churn measures compare id-cleared payloads, so the *only* difference
    between them is the key. Otherwise regenerated ids would mark every entity
    modified under both measures and the two could never disagree -- which
    would destroy the comparison that is the entire point.
    """
    copy = gtfs_realtime_pb2.FeedEntity()
    copy.CopyFrom(entity)
    # Normalised to a constant rather than cleared: FeedEntity.id is a proto2
    # required field, so clearing it makes the message unserialisable.
    copy.id = ""
    return copy.SerializeToString(deterministic=True)


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------

class Snapshot:
    __slots__ = ("record", "message", "header_ts", "modulo_hash", "request_at",
                 "by_id", "by_semantic", "by_id_comparable", "entity_ts", "counts")

    def __init__(self, record: dict, message) -> None:
        self.record = record
        self.message = message
        self.header_ts = message.header.timestamp or None
        self.modulo_hash = modulo_timestamp_hash(message)
        self.request_at = parse_iso(record["request_at"])

        self.by_id: dict[str, bytes] = {}
        self.by_semantic: dict[tuple, bytes] = {}
        # The same semantically-keyable entities, keyed by id. Persistence is
        # compared over this set rather than by_id so both keyings cover an
        # identical entity population -- otherwise an alert-heavy feed, whose
        # alerts have no semantic key, would skew the comparison.
        self.by_id_comparable: dict[str, bytes] = {}
        self.entity_ts: list[int] = []
        self.counts: collections.Counter[str] = collections.Counter()

        for entity in message.entity:
            payload = entity_payload(entity)
            self.by_id[entity.id] = payload
            semantic = entity_semantic_key(entity)
            if semantic is not None:
                self.by_semantic[semantic] = payload
                self.by_id_comparable[entity.id] = payload

            if entity.HasField("trip_update"):
                self.counts["trip_update"] += 1
                if entity.trip_update.timestamp:
                    self.entity_ts.append(entity.trip_update.timestamp)
            elif entity.HasField("vehicle"):
                self.counts["vehicle_position"] += 1
                if entity.vehicle.timestamp:
                    self.entity_ts.append(entity.vehicle.timestamp)
            elif entity.HasField("alert"):
                self.counts["alert"] += 1


def churn(previous: dict, current: dict) -> float | None:
    """Fraction of keys added, removed, or whose payload changed."""
    union = set(previous) | set(current)
    if not union:
        return None
    added = len(set(current) - set(previous))
    removed = len(set(previous) - set(current))
    modified = sum(1 for key in set(previous) & set(current) if previous[key] != current[key])
    return (added + removed + modified) / len(union)


def key_persistence(previous: dict, current: dict) -> float | None:
    """Fraction of keys surviving between snapshots: |A n B| / |A u B|.

    Measured directly rather than inferred from churn disagreement. Most
    producers restamp every entity every snapshot, which saturates both churn
    measures at 100% and leaves the comparison blind to whether the *key* is
    stable -- which is the thing dedup actually depends on.

    Jaccard alone is NOT sufficient, because it conflates unstable ids with
    genuine entity turnover. For a stable-id feed where a fraction f of
    entities enters and leaves between snapshots, this returns (1-f)/(1+f):
    0.74 at f=0.15, but 0.43 at f=0.40. An absolute threshold would call the
    second one "regenerating ids" and be wrong. The verdict therefore uses the
    ratio against semantic persistence, which is invariant to turnover because
    turnover moves both keyings identically. See ADR 0004.
    """
    union = set(previous) | set(current)
    if not union:
        return None
    return len(set(previous) & set(current)) / len(union)


# ---------------------------------------------------------------------------
# The five timestamp tests
# ---------------------------------------------------------------------------

def test_a(snapshots: list[Snapshot], static: bool) -> dict:
    """Body-modulo-timestamp hashing.

    Unavailable on static or near-static content. A degraded producer that
    still regenerates on schedule but emits a near-empty snapshot yields
    identical content alongside a legitimately advancing generation timestamp
    -- the echo signature from the opposite cause.
    """
    if static:
        return {"verdict": "unavailable",
                "reason": "content static or near-static; Test A cannot discriminate here"}
    if len(snapshots) < 2:
        return {"verdict": "unavailable", "reason": "fewer than two decoded snapshots"}

    restamped = 0
    content_changed_ts_same = 0
    for previous, current in zip(snapshots, snapshots[1:]):
        same_content = previous.modulo_hash == current.modulo_hash
        same_ts = previous.header_ts == current.header_ts
        if same_content and not same_ts:
            restamped += 1
        if not same_content and same_ts:
            content_changed_ts_same += 1

    if restamped:
        return {"verdict": "echo", "restamped_pairs": restamped,
                "reason": "identical content served under a changed header timestamp"}
    return {"verdict": "generation", "restamped_pairs": 0,
            "content_changed_ts_same": content_changed_ts_same,
            "reason": "header timestamp changed only when content changed"}


def test_b(snapshots: list[Snapshot], cadence_s: float | None, offset_ms: float | None) -> dict:
    """Shape of lag over time: sawtooth versus flat band at RTT."""
    if cadence_s is None or cadence_s <= 0:
        return {"verdict": "unavailable", "reason": "no measurable cadence"}

    correction = (offset_ms or 0.0) / 1000.0
    lags = [
        (snapshot.request_at.timestamp() - correction) - snapshot.header_ts
        for snapshot in snapshots if snapshot.header_ts and snapshot.request_at
    ]
    if len(lags) < 10:
        return {"verdict": "unavailable", "reason": f"only {len(lags)} usable samples"}

    quanta = cadence_s / HEADER_TIMESTAMP_RESOLUTION_S
    if quanta < B_MIN_CADENCE_QUANTA:
        return {
            "verdict": "unavailable",
            "cadence_s": cadence_s,
            "cadence_quanta": round(quanta, 2),
            "reason": (
                f"cadence {cadence_s}s spans only {quanta:.1f} one-second timestamp levels "
                f"({B_MIN_CADENCE_QUANTA} required); a sawtooth quantised into that few levels "
                "has no characterisable shape"
            ),
        }

    median_lag = statistics.median(lags)
    if median_lag > cadence_s:
        return {
            "verdict": "unavailable",
            "lag_p50_s": round(median_lag, 3),
            "cadence_s": cadence_s,
            "reason": (
                f"median lag {median_lag:.2f}s exceeds the {cadence_s}s cadence, so lag is not "
                "confined to [0, cadence] as the sawtooth model requires -- this is the "
                "producer's own pipeline delay, not a snapshot ageing"
            ),
        }

    stdev = statistics.pstdev(lags)
    ratio = stdev / cadence_s
    result = {
        "lag_p50_s": round(statistics.median(lags), 3),
        "lag_max_s": round(max(lags), 3),
        "lag_stdev_s": round(stdev, 3),
        "stdev_over_cadence": round(ratio, 4),
        "cadence_s": cadence_s,
        "clock_corrected": offset_ms is not None,
        "thresholds": {"generation_above": B_RATIO_GENERATION, "echo_below": B_RATIO_ECHO},
    }
    if ratio >= B_RATIO_GENERATION:
        result["verdict"] = "generation"
    elif ratio <= B_RATIO_ECHO:
        result["verdict"] = "echo"
    else:
        result["verdict"] = "unavailable"
        result["reason"] = "ratio falls between thresholds; not discriminating"
    return result


def test_c(observations: list[dict], decoded: dict[int, Snapshot], gap_s: float,
           cadence_s: float | None = None) -> dict:
    """Asynchronous re-poll -- the deliberate perturbation.

    Unaffected by static content, so it stays authoritative on a degraded feed
    where Test A does not.
    """
    pairs = []
    by_seq = {obs["seq"]: obs for obs in observations}
    for obs in observations:
        if obs.get("probe_action") != "async_repoll_a":
            continue
        partner = by_seq.get(obs["seq"] + 1)
        if not partner or partner.get("probe_action") != "async_repoll_b":
            continue
        first, second = decoded.get(obs["seq"]), decoded.get(partner["seq"])
        if not first or not second or not first.header_ts or not second.header_ts:
            continue
        delta = second.header_ts - first.header_ts
        request_gap = (second.request_at - first.request_at).total_seconds()
        pairs.append({
            "header_ts_delta_s": delta,
            "request_gap_s": round(request_gap, 3),
            "tracks_request_time": abs(delta - request_gap) <= C_GAP_TOLERANCE_S and delta > 0,
        })

    if not pairs:
        return {"verdict": "unavailable", "reason": "no usable re-poll pairs", "pairs": []}

    # The test compares two fetches of the SAME snapshot. If the gap is not
    # comfortably shorter than the cadence, the pair straddles real generations
    # and their honest advance is indistinguishable from restamping.
    if cadence_s and pairs:
        observed_gap = max(p["request_gap_s"] for p in pairs)
        if observed_gap > cadence_s * C_MAX_GAP_FRACTION_OF_CADENCE:
            return {
                "verdict": "unavailable",
                "pairs": pairs,
                "observed_gap_s": observed_gap,
                "cadence_s": cadence_s,
                "reason": (
                    f"re-poll gap {observed_gap:.2f}s exceeds "
                    f"{C_MAX_GAP_FRACTION_OF_CADENCE:g}x the {cadence_s}s cadence, so the pair "
                    "spans real generations; any timestamp advance is expected and cannot be "
                    "read as restamping"
                ),
            }

    if any(pair["tracks_request_time"] for pair in pairs):
        return {"verdict": "echo", "pairs": pairs,
                "reason": "timestamps moved with our request times across a 2s gap"}
    if all(pair["header_ts_delta_s"] == 0 for pair in pairs):
        return {"verdict": "generation", "pairs": pairs, "sample_size": len(pairs),
                "reason": "same snapshot returned the same timestamp"}
    return {"verdict": "unavailable", "pairs": pairs,
            "reason": "timestamps changed but not in step with request time; a real "
                      "generation may have landed between the two fetches"}


def test_d(snapshots: list[Snapshot]) -> dict:
    """Header timestamp against entity timestamps.

    Echo shows a rising staircase of header_ts - max(entity_ts) across
    consecutive fetches of the same snapshot; real generation stays flat.
    """
    with_ts = [s for s in snapshots if s.entity_ts]
    total_entities = sum(len(s.by_id) for s in snapshots)
    covered = sum(len(s.entity_ts) for s in snapshots)
    coverage = covered / total_entities if total_entities else 0.0

    if coverage < D_MIN_ENTITY_TS_COVERAGE or not with_ts:
        return {"verdict": "unavailable", "entity_ts_coverage": round(coverage, 3),
                "reason": "entity timestamps absent or too sparse"}

    groups: dict[str, list[float]] = collections.defaultdict(list)
    for snapshot in with_ts:
        if snapshot.header_ts:
            groups[snapshot.modulo_hash].append(snapshot.header_ts - max(snapshot.entity_ts))

    staircases = 0
    flats = 0
    for deltas in groups.values():
        if len(deltas) < D_STAIRCASE_MIN_STEPS:
            continue
        if all(later > earlier for earlier, later in zip(deltas, deltas[1:])):
            staircases += 1
        else:
            flats += 1

    if staircases == 0 and flats == 0:
        return {"verdict": "unavailable", "entity_ts_coverage": round(coverage, 3),
                "reason": "no snapshot was re-served often enough to see a trend"}
    if staircases and not flats:
        return {"verdict": "echo", "entity_ts_coverage": round(coverage, 3),
                "rising_groups": staircases,
                "reason": "header timestamp drifts ahead of entity timestamps on a re-served snapshot"}
    if flats and not staircases:
        return {"verdict": "generation", "entity_ts_coverage": round(coverage, 3),
                "flat_groups": flats}
    return {"verdict": "unavailable", "entity_ts_coverage": round(coverage, 3),
            "rising_groups": staircases, "flat_groups": flats,
            "reason": "mixed behaviour across re-served snapshots"}


def test_e(snapshots: list[Snapshot]) -> dict:
    """Cross-check against HTTP Date and Last-Modified.

    Tracking Last-Modified supports real generation; tracking Date on every
    fetch is the echo signature seen from the HTTP layer.
    """
    from email.utils import parsedate_to_datetime

    date_deltas, lm_deltas = [], []
    for snapshot in snapshots:
        if not snapshot.header_ts:
            continue
        headers = snapshot.record.get("response_headers", {})
        for key, sink in (("date", date_deltas), ("last-modified", lm_deltas)):
            raw = headers.get(key)
            if not raw:
                continue
            try:
                sink.append(abs(parsedate_to_datetime(raw).timestamp() - snapshot.header_ts))
            except Exception:  # noqa: BLE001
                pass

    result = {
        "median_abs_delta_vs_date_s": round(statistics.median(date_deltas), 2) if date_deltas else None,
        "median_abs_delta_vs_last_modified_s": round(statistics.median(lm_deltas), 2) if lm_deltas else None,
    }
    result["separation_ratio_required"] = E_SEPARATION_RATIO
    result["noise_floor_s"] = E_NOISE_FLOOR_S

    if not date_deltas or not lm_deltas:
        result["verdict"] = "unavailable"
        result["reason"] = "one of the two references was absent"
        return result

    date_delta = result["median_abs_delta_vs_date_s"]
    lm_delta = result["median_abs_delta_vs_last_modified_s"]

    if date_delta < E_NOISE_FLOOR_S and lm_delta < E_NOISE_FLOOR_S:
        result["verdict"] = "unavailable"
        result["reason"] = (
            f"both references sit within {E_NOISE_FLOOR_S}s of the header timestamp; "
            "the comparison is sub-second noise, not a signal"
        )
    elif lm_delta * E_SEPARATION_RATIO <= date_delta:
        result["verdict"] = "generation"
        result["reason"] = "header timestamp tracks Last-Modified far more closely than Date"
    elif date_delta * E_SEPARATION_RATIO <= lm_delta:
        result["verdict"] = "echo"
        result["reason"] = "header timestamp tracks the server's send time"
    else:
        result["verdict"] = "unavailable"
        result["reason"] = (
            f"the two references are within {E_SEPARATION_RATIO}x of each other; "
            "neither is clearly closer"
        )
    return result


def nyquist_check(deltas: list[float], cadence_p50: float | None,
                  effective_interval: float | None) -> dict:
    """Can the observed cadence be resolved at the interval we achieved?

    Two independent signals. Either one makes the cadence figure our sampling
    grid rather than a property of the feed.
    """
    result = {
        "effective_interval_s": effective_interval,
        "nyquist_limit_s": round(effective_interval * NYQUIST_FACTOR, 2) if effective_interval else None,
    }
    if not deltas or cadence_p50 is None or not effective_interval:
        result["undersampled"] = None
        return result

    on_grid = [d / effective_interval for d in deltas]
    grid_fraction = sum(1 for m in on_grid if abs(m - round(m)) <= GRID_TOLERANCE) / len(on_grid)
    below_nyquist = cadence_p50 < effective_interval * NYQUIST_FACTOR

    result["grid_multiple_fraction"] = round(grid_fraction, 3)
    result["below_nyquist"] = below_nyquist

    # Nyquist is the sound criterion and the only trigger. Grid clustering is
    # reported as corroborating evidence but cannot fire on its own: a feed
    # sampled four times faster than it regenerates also lands every delta on
    # the grid, and there the cadence figure is correct. Treating clustering as
    # independent proof flags a feed we are resolving perfectly well.
    result["undersampled"] = bool(below_nyquist)
    if below_nyquist:
        result["reason"] = (
            f"observed cadence {cadence_p50}s is under {NYQUIST_FACTOR}x the achieved "
            f"interval {effective_interval}s, so what comes back is our sampling grid"
        )
        if grid_fraction >= GRID_FRACTION:
            result["reason"] += (
                f"; corroborated by {grid_fraction:.0%} of deltas landing on multiples "
                "of that interval"
            )
    return result


#: How much weight the verdict carries, by how many tests could speak to it.
STRENGTH_BY_COUNT = {0: "none", 1: "weak", 2: "moderate"}


def combine(votes: dict[str, str]) -> tuple[str, str, dict]:
    """Unanimity among available tests, or unknown -- with its evidence strength.

    Disagreement is not resolved with a narrative. The per-test votes are
    recorded so a human can look, and the tenant is marked unknown until one
    does.

    A verdict also carries how many tests were able to speak to it. Five tests
    agreeing and one test unopposed are both "unanimous", and reporting them
    identically would overstate the second. Evidence strength travels with the
    verdict, as the comparison gap travels with persistence.
    """
    available = {name: verdict for name, verdict in votes.items()
                 if verdict in ("generation", "echo")}
    strength = {
        "available_tests": len(available),
        "total_tests": len(votes),
        "label": STRENGTH_BY_COUNT.get(len(available), "strong"),
    }
    if not available:
        return "unknown", "no test was able to discriminate", strength
    distinct = set(available.values())
    if len(distinct) == 1:
        verdict = distinct.pop()
        return (verdict,
                f"unanimous across {len(available)} of {len(votes)} tests: "
                f"{', '.join(sorted(available))}",
                strength)
    disagreement = ", ".join(f"{name}={verdict}" for name, verdict in sorted(available.items()))
    return "unknown", f"available tests disagree ({disagreement}); not resolved by narrative", strength


# ---------------------------------------------------------------------------
# Per-feed analysis
# ---------------------------------------------------------------------------

def analyse_feed(feed_id: str, observations: list[dict], run_dir: Path,
                 manifest: dict, guard: dict) -> dict:
    blobs = run_dir / "blobs"
    feed_cfg = next((f for f in manifest["feeds"] if f["id"] == feed_id), {})

    status_counts = collections.Counter(
        str(obs["status"]) if obs["status"] is not None else "error" for obs in observations
    )

    # --- conditional requests ---
    with_validator = [o for o in observations if o.get("conditional") not in (None, "none")]
    not_modified = [o for o in with_validator if o["status"] == 304]
    honoured_by = collections.Counter(
        o["conditional"] for o in not_modified
    )
    false_200 = 0
    previous_hash = None
    for obs in observations:
        if obs["status"] == 200 and obs.get("body_sha256"):
            if previous_hash and obs["body_sha256"] == previous_hash and obs.get("conditional") != "none":
                false_200 += 1
            previous_hash = obs["body_sha256"]

    # --- decode every distinct payload once ---
    tracemalloc.start()
    process = psutil.Process()
    peak_rss = process.memory_info().rss
    single_decode_peak = 0

    cache: dict[str, tuple[str, object]] = {}
    decoded: dict[int, Snapshot] = {}
    parse_classes: collections.Counter[str] = collections.Counter()

    for obs in observations:
        digest = obs.get("body_sha256")
        if not digest:
            continue
        if digest not in cache:
            blob = blobs / f"{digest}.pb"
            if not blob.exists():
                parse_classes["blob_missing"] += 1
                continue
            raw = blob.read_bytes()
            tracemalloc.reset_peak()
            cache[digest] = classify_payload(raw)
            _, peak = tracemalloc.get_traced_memory()
            single_decode_peak = max(single_decode_peak, peak)
            peak_rss = max(peak_rss, process.memory_info().rss)

        classification, message = cache[digest]
        parse_classes[classification] += 1
        if message is not None and classification in ("ok", "valid_but_empty"):
            decoded[obs["seq"]] = Snapshot(obs, message)

    tracemalloc.stop()

    scheduled = [decoded[o["seq"]] for o in observations
                 if o.get("probe_action") == "scheduled" and o["seq"] in decoded]

    # --- cadence, from scheduled fetches only ---
    distinct_ts: list[int] = []
    for snapshot in scheduled:
        if snapshot.header_ts and (not distinct_ts or snapshot.header_ts != distinct_ts[-1]):
            distinct_ts.append(snapshot.header_ts)
    deltas = [b - a for a, b in zip(distinct_ts, distinct_ts[1:]) if b > a]
    # Measured from the observations themselves, so it reflects what we achieved
    # rather than what the config asked for. Configured value is a sleep after
    # completion, so a slow fetch silently widens the real interval.
    scheduled_times = sorted(
        parse_iso(o["request_at"]) for o in observations
        if o.get("probe_action") == "scheduled" and o.get("request_at")
    )
    request_gaps = [(b - a).total_seconds() for a, b in zip(scheduled_times, scheduled_times[1:])]
    effective_interval = round(statistics.median(request_gaps), 2) if len(request_gaps) >= 2 else None

    cadence = {
        "distinct_header_timestamps": len(distinct_ts),
        "delta_p50_s": statistics.median(deltas) if deltas else None,
        "delta_p95_s": (sorted(deltas)[int(len(deltas) * 0.95)] if len(deltas) >= 20 else None),
        "delta_min_s": min(deltas) if deltas else None,
        "delta_max_s": max(deltas) if deltas else None,
        "note": "async re-poll fetches excluded; they would corrupt this distribution",
    }
    # Independent cadence measure from Last-Modified, available on every
    # observation that carries the header including HEADs. For a feed too
    # expensive to GET at its true rate this is the only cadence we can afford
    # to measure honestly, and for the others it cross-checks the header-derived
    # figure at no extra cost.
    lm_times: list[float] = []
    for obs in observations:
        raw = obs.get("response_headers", {}).get("last-modified")
        if not raw:
            continue
        try:
            from email.utils import parsedate_to_datetime
            value = parsedate_to_datetime(raw).timestamp()
        except Exception:  # noqa: BLE001
            continue
        if not lm_times or value != lm_times[-1]:
            lm_times.append(value)
    lm_deltas = [b - a for a, b in zip(lm_times, lm_times[1:]) if b > a]
    last_modified_cadence = {
        "distinct_values": len(lm_times),
        "delta_p50_s": statistics.median(lm_deltas) if lm_deltas else None,
        "delta_min_s": min(lm_deltas) if lm_deltas else None,
        "delta_max_s": max(lm_deltas) if lm_deltas else None,
        "note": "Derived from Last-Modified, so HEAD requests contribute. Independent of "
                "FeedHeader.timestamp and of payload cost.",
    }
    # Sampled at the poll rate, not at the rate observations happen to carry the
    # header. Under conditional requests only a *changed* response returns
    # Last-Modified, so deriving the interval from those alone would equal the
    # cadence and trip the Nyquist guard on a feed we are sampling perfectly well.
    last_modified_cadence["sampling"] = nyquist_check(
        lm_deltas, last_modified_cadence["delta_p50_s"], effective_interval)

    cadence["sampling"] = nyquist_check(deltas, cadence["delta_p50_s"], effective_interval)
    if cadence["sampling"].get("undersampled"):
        cadence["unreliable"] = True
        cadence["note"] += (
            ". UNDERSAMPLED: " + cadence["sampling"]["reason"] +
            ". This figure is our sampling grid, not the feed's cadence. Do not record it "
            "as a feed property."
        )

    # --- entity counts and churn ---
    entity_counts = collections.Counter()
    for snapshot in scheduled:
        entity_counts.update(snapshot.counts)

    distinct_snapshots = []
    for snapshot in scheduled:
        if not distinct_snapshots or snapshot.modulo_hash != distinct_snapshots[-1].modulo_hash:
            distinct_snapshots.append(snapshot)

    churn_by_id, churn_by_semantic = [], []
    persist_by_id, persist_by_semantic = [], []
    comparison_gaps: list[float] = []
    for previous, current in zip(distinct_snapshots, distinct_snapshots[1:]):
        for previous_map, current_map, sink, function in (
            (previous.by_id, current.by_id, churn_by_id, churn),
            (previous.by_semantic, current.by_semantic, churn_by_semantic, churn),
            (previous.by_id_comparable, current.by_id_comparable, persist_by_id, key_persistence),
            (previous.by_semantic, current.by_semantic, persist_by_semantic, key_persistence),
        ):
            value = function(previous_map, current_map)
            if value is not None:
                sink.append(value)
        if previous.request_at and current.request_at:
            comparison_gaps.append((current.request_at - previous.request_at).total_seconds())

    median_id_churn = statistics.median(churn_by_id) if churn_by_id else None
    median_semantic_churn = statistics.median(churn_by_semantic) if churn_by_semantic else None
    median_id_persistence = statistics.median(persist_by_id) if persist_by_id else None
    median_semantic_persistence = statistics.median(persist_by_semantic) if persist_by_semantic else None
    entity_counts_per_snapshot = [len(s.by_id) for s in scheduled]
    median_entities = statistics.median(entity_counts_per_snapshot) if entity_counts_per_snapshot else 0

    def rounded(value):
        return round(value, 4) if value is not None else None

    churn_result = {
        "median_churn_keyed_on_entity_id": rounded(median_id_churn),
        "median_churn_keyed_on_semantic_key": rounded(median_semantic_churn),
        "median_key_persistence_entity_id": rounded(median_id_persistence),
        "median_key_persistence_semantic": rounded(median_semantic_persistence),
        "comparisons": len(churn_by_id),
        "note": "Churn answers how much write load a snapshot creates. Key persistence "
                "answers what dedup can key on, and is measured directly because a producer "
                "that restamps every entity saturates both churn figures and leaves their "
                "difference uninformative.",
    }
    if comparison_gaps:
        churn_result["comparison_gap_seconds"] = {
            "p50": round(statistics.median(comparison_gaps), 1),
            "min": round(min(comparison_gaps), 1),
            "max": round(max(comparison_gaps), 1),
            "note": "Wall-clock separation of the snapshots each verdict is computed from. "
                    "A verdict from snapshots minutes apart is weaker evidence than one from "
                    "seconds apart; metrics.md must carry this, not present them as equal.",
        }

    # Verdict on the ratio, not on an absolute persistence value: turnover moves
    # both keyings identically, so the ratio is invariant to it where a
    # threshold on id persistence alone is not.
    if median_id_persistence is not None and median_semantic_persistence is not None:
        churn_result["id_vs_semantic_persistence_ratio"] = (
            rounded(median_id_persistence / median_semantic_persistence)
            if median_semantic_persistence > 0 else None
        )
        churn_result["denominator_floor"] = ID_STABILITY_DENOMINATOR_FLOOR

        if median_semantic_persistence < ID_STABILITY_DENOMINATOR_FLOOR:
            # The ratio is unstable when both terms are small -- exactly the
            # far-apart-snapshot case that motivated using a ratio at all.
            churn_result["id_stability"] = "indeterminate"
            churn_result["finding"] = (
                f"Semantic persistence is {median_semantic_persistence:.1%}, below the "
                f"{ID_STABILITY_DENOMINATOR_FLOOR:.0%} floor: the entity population itself "
                "turns over almost completely between compared snapshots, so the ratio "
                "carries no signal. Id stability is indeterminate, not stable and not "
                "regenerating."
            )
        else:
            ratio = median_id_persistence / median_semantic_persistence
            if ratio >= ID_STABILITY_RATIO_STABLE:
                churn_result["id_stability"] = "stable"
                churn_result["finding"] = (
                    f"entity.id tracks the semantic key (ratio {ratio:.2f}); it is usable as a "
                    f"dedup key on this feed. Raw id persistence is {median_id_persistence:.1%}, "
                    "the remainder being genuine entity turnover rather than id instability."
                )
            elif ratio <= ID_STABILITY_RATIO_REGENERATING:
                churn_result["id_stability"] = "regenerating"
                churn_result["finding"] = (
                    f"FeedEntity.id is regenerated between snapshots (ratio {ratio:.2f}: id "
                    f"persistence {median_id_persistence:.1%} against semantic "
                    f"{median_semantic_persistence:.1%}). Dedup must key on the semantic key; "
                    "keying on entity.id would treat every snapshot as entirely new."
                )
            else:
                churn_result["id_stability"] = "indeterminate"
                churn_result["finding"] = (
                    f"Ratio {ratio:.2f} falls between thresholds -- consistent with partial id "
                    "regeneration across entity types. Not resolved by narrative; inspect "
                    "analysis.json before choosing a dedup key."
                )

    # --- static-content guard for Test A ---
    static = (
        median_entities < guard["min_median_entities"]
        or (median_semantic_churn is not None
            and median_semantic_churn < guard["min_median_semantic_churn"])
    )

    # --- the five tests ---
    offset_ms = next((o.get("clock_offset_ms") for o in observations
                      if o.get("clock_offset_ms") is not None), None)
    gap_s = 2.0
    votes_detail = {
        "A_body_modulo_timestamp": test_a(scheduled, static),
        "B_lag_shape": test_b(scheduled, cadence["delta_p50_s"], offset_ms),
        "C_async_repoll": test_c(observations, decoded, gap_s, cadence["delta_p50_s"]),
        "D_entity_timestamps": test_d(scheduled),
        "E_http_date_last_modified": test_e(scheduled),
    }
    verdict, rationale, strength = combine({k: v["verdict"] for k, v in votes_detail.items()})

    if verdict == "echo":
        # Cadence is derived from distinct header timestamps. On an echo feed
        # those advance once per fetch, so the figure measures our poll interval
        # and not their generation cadence. Say so rather than publishing a
        # number that looks like an upstream fact.
        cadence["unreliable"] = True
        cadence["note"] += (
            ". HEADER TIMESTAMP IS ECHOED: this cadence reflects our own poll interval, "
            "not upstream generation cadence. Do not record it as a feed property."
        )

    # --- gaps and downtime ---
    times = [parse_iso(o["request_at"]) for o in observations if o.get("request_at")]
    times.sort()
    poll_interval = effective_interval or feed_cfg.get("sleep_after_completion_s") or 5
    gaps = [
        {"from": a.isoformat(), "to": b.isoformat(), "seconds": round((b - a).total_seconds(), 1)}
        for a, b in zip(times, times[1:])
        if (b - a).total_seconds() > poll_interval * 3
    ]

    downtime_runs, current_run = [], 0
    for obs in observations:
        ok = obs["status"] is not None and 200 <= obs["status"] < 400
        if ok:
            if current_run:
                downtime_runs.append(current_run)
            current_run = 0
        else:
            current_run += 1
    if current_run:
        downtime_runs.append(current_run)

    wire = [o["body_bytes_wire"] for o in observations if o.get("body_bytes_wire")]
    decompressed = [o["body_bytes_decompressed"] for o in observations if o.get("body_bytes_decompressed")]

    return {
        "feed": feed_id,
        "requests": len(observations),
        "status_distribution": dict(status_counts),
        "methods": dict(collections.Counter(o.get("method", "GET") for o in observations)),
        "conditional_requests": {
            "sent_with_validator": len(with_validator),
            "returned_304": len(not_modified),
            "not_modified_rate": round(len(not_modified) / len(with_validator), 4) if with_validator else None,
            "honoured_by_mode": dict(honoured_by),
            "false_200_identical_body": false_200,
            "note": "false_200 = a 200 whose body hash equals the previous body's. The server "
                    "advertises validators it does not honour; Gate 5's bytes-saved claim rests here.",
        },
        "cadence": cadence,
        "last_modified_cadence": last_modified_cadence,
        "effective_interval_s": effective_interval,
        "payload_bytes": {
            "wire_p50": statistics.median(wire) if wire else None,
            "wire_p95": (sorted(wire)[int(len(wire) * 0.95)] if len(wire) >= 20 else None),
            "wire_max": max(wire) if wire else None,
            "wire_total": sum(wire) if wire else None,
            "decompressed_p50": statistics.median(decompressed) if decompressed else None,
            "decompressed_max": max(decompressed) if decompressed else None,
            "note": "decompressed = post-transport-decompression wire bytes. Protobuf 'decoded "
                    "size' is not a meaningful byte count and is not recorded.",
        },
        "entities": {
            "counts_total": dict(entity_counts),
            "median_per_snapshot": median_entities,
        },
        "parse": {
            "classes": dict(parse_classes),
            "failure_rate": round(
                sum(v for k, v in parse_classes.items() if k not in ("ok", "valid_but_empty"))
                / max(sum(parse_classes.values()), 1), 4),
            "gtfs_realtime_version": next(
                (s.message.header.gtfs_realtime_version for s in scheduled), None),
            "incrementality": next(
                (gtfs_realtime_pb2.FeedHeader.Incrementality.Name(s.message.header.incrementality)
                 for s in scheduled), None),
        },
        "churn": churn_result,
        "header_timestamp": {
            "verdict": verdict,
            "strength": strength,
            "rationale": rationale,
            "static_content_guard_triggered": static,
            "votes": {k: v["verdict"] for k, v in votes_detail.items()},
            "detail": votes_detail,
        },
        "availability": {
            "downtime_runs": downtime_runs,
            "longest_consecutive_failures": max(downtime_runs) if downtime_runs else 0,
            "note": "Observed within the run window only. An hour supports no availability "
                    "figure and none is reported.",
        },
        "capture_gaps": gaps,
        "memory": {
            "single_message_decode_peak_bytes": single_decode_peak,
            "process_peak_rss_bytes": peak_rss,
            "measured_on": f"{platform.python_implementation()} {platform.python_version()} / "
                           f"{platform.system()} {platform.machine()}",
            "note": "Indicative, not equal to an arm64 Linux container. Gate 5 sizing method: "
                    "single-message decode peak x queue depth x safety factor, corrected at "
                    "Gate 7 from container_memory_working_set_bytes. Re-run this inside a Linux "
                    "container so architecture is the only remaining confound.",
        },
    }


SYNTHETIC_BANNER = (
    "> ## ⚠ SYNTHETIC FIXTURE DATA — NOT MEASURED\n"
    "> These numbers were generated to verify the analyser against known ground truth.\n"
    "> They describe no real feed. **Never copy them into `docs/metrics.md`**, which holds\n"
    "> measured numbers only."
)


def markdown_table(results: list[dict], synthetic: bool = False) -> str:
    def percent(value):
        return f"{value:.1%}" if value is not None else "—"

    rows = []
    if synthetic:
        rows += [SYNTHETIC_BANNER, ""]
    rows += [
        "| Feed | Reqs | MB moved | Cadence p50 | 304 rate | False-200 | Entities | "
        "Persist id / sem | Ratio | entity.id | Cmp gap p50 | Header ts | Parse fail |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        churn_data = r["churn"]
        cadence = r["cadence"]
        cadence_cell = f"{cadence['delta_p50_s']} s" if cadence["delta_p50_s"] else "—"
        if cadence.get("unreliable"):
            cadence_cell += " ⚠"
        ratio = churn_data.get("id_vs_semantic_persistence_ratio")
        gap = churn_data.get("comparison_gap_seconds", {}).get("p50")
        total_bytes = r["payload_bytes"]["wire_total"]
        rows.append(
            f"| {r['feed']} | {r['requests']} | "
            f"{f'{total_bytes / 1e6:.1f}' if total_bytes else '—'} | {cadence_cell} | "
            f"{percent(r['conditional_requests']['not_modified_rate'])} | "
            f"{r['conditional_requests']['false_200_identical_body']} | "
            f"{r['entities']['median_per_snapshot']} | "
            f"{percent(churn_data['median_key_persistence_entity_id'])} / "
            f"{percent(churn_data['median_key_persistence_semantic'])} | "
            f"{f'{ratio:.2f}' if ratio is not None else '—'} | "
            f"{churn_data.get('id_stability', '—')} | "
            f"{f'{gap:.0f} s' if gap is not None else '—'} | "
            f"**{r['header_timestamp']['verdict']}**"
            + (f" ({st['label']} {st['available_tests']}/{st['total_tests']})"
               if (st := r['header_timestamp'].get('strength')) and st['label'] != 'strong'
               else "") + " | "
            f"{r['parse']['failure_rate']:.1%} |"
        )
    rows.append("")
    # Two distinct causes, and the legend must name both: an echoed header
    # timestamp and undersampling make the same figure meaningless for
    # different reasons, and saying only "echoed" mislabels a generation feed.
    rows.append("⚠ = cadence is not a feed property. Either the header timestamp is echoed, or we "
                "sampled below Nyquist and the figure is our own polling grid. The specific reason "
                "is in `cadence.sampling` and `cadence.note` in analysis.json.")
    rows.append("Cmp gap = wall-clock separation of the snapshots each id-stability verdict "
                "was computed from. Wider gaps are weaker evidence.")
    if synthetic:
        rows += ["", SYNTHETIC_BANNER]
    return "\n".join(rows)


def analyse_run(run_dir: Path) -> dict:
    manifest, observations = load(run_dir)
    guard = {"min_median_entities": 10, "min_median_semantic_churn": 0.05}

    by_feed: dict[str, list[dict]] = collections.defaultdict(list)
    for obs in observations:
        by_feed[obs["feed"]].append(obs)

    results = [
        analyse_feed(feed_id, sorted(obs, key=lambda o: o["seq"]), run_dir, manifest, guard)
        for feed_id, obs in sorted(by_feed.items())
    ]

    return {
        "run": manifest["run"],
        # Carried through from the run manifest so synthetic output can never be
        # mistaken for measured output, here or in six months.
        "synthetic": bool(manifest.get("synthetic")),
        "analysed_at": datetime.now().astimezone().isoformat(),
        "clock": manifest["clock"],
        "feeds": results,
    }


def main(run_dir: Path) -> int:
    # The table carries non-ASCII markers and is meant to be redirected into a
    # file. Windows defaults stdout to cp1252 when piped, which cannot encode
    # them and would crash on output rather than on anything analytical.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    output = analyse_run(run_dir)
    results = output["feeds"]

    out_path = run_dir / "analysis.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(markdown_table(results, synthetic=output["synthetic"]))
    print(f"\nFull analysis -> {out_path}")

    for result in results:
        header = result["header_timestamp"]
        print(f"\n[{result['feed']}] header timestamp: {header['verdict']} — {header['rationale']}")
        if header["static_content_guard_triggered"]:
            print("  Test A marked unavailable: content static or near-static.")
        if result["churn"].get("finding"):
            print(f"  churn: {result['churn']['finding']}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1])))

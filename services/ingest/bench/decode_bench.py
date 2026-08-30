"""Single-message protobuf decode cost, measured by RSS.

PLAN.md section 7 sizes the ingest pod's memory request as
`single-message decode peak x queue depth x safety factor`, from the Stage 0
probe, corrected at Gate 7 from container_memory_working_set_bytes.

Two things make this a rewrite rather than a re-run of the Stage 0 measurement:

1. **The Stage 0 field is unusable.** `single_message_decode_peak_bytes` in
   runs/run2/analysis.json is not a decode peak -- it reports 2.14 GB for VBB,
   whose bodies decompress to 9 MB. See runs/stage0-corrections/.

2. **tracemalloc cannot measure this at all.** The `upb` protobuf runtime
   allocates its message arena in C++, outside Python's allocator. Decoding a
   9.4 MB body moves RSS by 37 MB while tracemalloc reports 236 bytes. So the
   instrument here is RSS, deliberately, and tracemalloc is measured alongside
   only to keep that difference on the record rather than in a comment.

Run inside a Linux container so architecture is the only remaining confound
between this figure and the pod. That confound is real and is NOT closed here:
this runs on amd64 and the node is OCI Ampere A1 (arm64).
"""
from __future__ import annotations

import gc
import json
import os
import resource
import statistics
import sys
import tracemalloc

from google.transit import gtfs_realtime_pb2


def rss_bytes() -> int:
    """Current RSS. /proc is authoritative on Linux; ru_maxrss is a high-water
    mark and cannot come back down, so it is reported separately, not used as
    the per-decode measure."""
    with open("/proc/self/statm", encoding="ascii") as handle:
        pages = int(handle.read().split()[1])
    return pages * os.sysconf("SC_PAGE_SIZE")


def decode_once(raw: bytes):
    message = gtfs_realtime_pb2.FeedMessage()
    message.ParseFromString(raw)
    return message, len(message.entity)


def main(paths: list[str]) -> int:
    print("### environment ###")
    print(f"python:   {sys.version.split()[0]}")
    from google.protobuf.internal import api_implementation
    print(f"protobuf: {api_implementation.Type()} implementation")
    print(f"platform: {os.uname().sysname} {os.uname().machine}")
    print()
    print("ARCHITECTURE IS NOT CONTROLLED FOR. This is a Linux container, which")
    print("is what PLAN.md section 7 asks for, but the node is arm64 and this is")
    print(f"{os.uname().machine}. The remaining confound is named, not closed.")
    print()

    results = []
    for path in paths:
        raw = open(path, "rb").read()

        # Warm up: first decode in a process pays for descriptor pools and arena
        # setup, which is a one-time cost and not what the sizing term means.
        warm, _ = decode_once(raw)
        del warm
        gc.collect()

        samples = []
        for _ in range(5):
            gc.collect()
            before = rss_bytes()
            message, entities = decode_once(raw)
            after = rss_bytes()
            samples.append(after - before)
            del message
            gc.collect()

        # The same decode under tracemalloc, to keep the blindness on record.
        gc.collect()
        tracemalloc.start()
        tracemalloc.reset_peak()
        message, entities = decode_once(raw)
        _, traced_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        del message
        gc.collect()

        median = statistics.median(samples)
        results.append({
            "path": os.path.basename(path),
            "body_bytes": len(raw),
            "entities": entities,
            "rss_delta_median": median,
            "rss_delta_min": min(samples),
            "rss_delta_max": max(samples),
            "rss_per_body_byte": round(median / len(raw), 2),
            "tracemalloc_peak": traced_peak,
        })

    print("### single-message decode, RSS delta over 5 decodes ###")
    print()
    header = f"{'body bytes':>12} {'entities':>9} {'RSS median':>12} {'min':>12} {'max':>12} {'x body':>7} {'tracemalloc':>12}"
    print(header)
    for row in results:
        print(f"{row['body_bytes']:>12,} {row['entities']:>9,} "
              f"{row['rss_delta_median']:>12,} {row['rss_delta_min']:>12,} "
              f"{row['rss_delta_max']:>12,} {row['rss_per_body_byte']:>6.1f}x "
              f"{row['tracemalloc_peak']:>12,}")

    print()
    print(f"ru_maxrss (whole process high-water): {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024:,} bytes")
    print()

    worst = max(results, key=lambda r: r["rss_delta_median"])
    print("### the sizing term ###")
    print()
    print(f"single-message decode peak = {worst['rss_delta_median']:,} bytes "
          f"({worst['rss_delta_median']/1e6:.1f} MB)")
    print("  x queue depth 2                      (ADR 0010)")
    print("  x safety factor 2")
    print(f"  = {worst['rss_delta_median'] * 4:,} bytes "
          f"({worst['rss_delta_median'] * 4 / 1e6:.0f} MB) before the interpreter's own floor")
    print()
    print("This is an INPUT to a Gate 6 memory request, not the request itself,")
    print("and PLAN.md section 7 corrects it at Gate 7 from observed")
    print("container_memory_working_set_bytes. It does not include the")
    print("interpreter, httpx, psycopg or the current-state working set.")

    with open("/out/decode-bench.json", "w", encoding="utf-8") as handle:
        json.dump({"results": results, "machine": os.uname().machine,
                   "python": sys.version}, handle, indent=1)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

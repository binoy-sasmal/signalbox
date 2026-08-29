# Stage 0 corrections — three numbers that were wrong, and what they are now

**Nothing here re-polls a feed.** Every figure is recomputed from the observation
logs already committed under [`runs/run1/`](../run1/) and [`runs/run2/`](../run2/).
No network, no fixtures.

These were found while designing Gate 5, whose bytes-saved prediction is computed
directly from two of them. They are corrected **before** Gate 5 starts rather than
during it, so the gate builds on corrected figures instead of correcting them
mid-flight.

| File | What it establishes |
|---|---|
| `compression-and-304-floor.txt` | Both HSL endpoints are served **uncompressed**, so gtfs.de was not "the only probed feed that does not compress" once run 2 existed. And HSL's 304 rate, counted against the generation count rather than a median-gap ceiling, sits at the **floor** of possible bodies. |
| `decode-peak-not-a-decode-peak.txt` | `single_message_decode_peak_bytes` in `runs/run2/analysis.json` is **not a decode peak** and is not usable for Gate 5's memory sizing. What it is instead, demonstrated. |

## The shape all three share

None of them is a measurement that came out wrong. The observations were captured
correctly and are unchanged. In each case the **reading** of a correct capture was
wrong:

1. A claim whose scope was true when written and was never re-checked when run 2
   widened the population it quantified over.
2. A ratio computed against a summary statistic (the median inter-request gap) that
   the underlying distribution does not support, because 304s return in 125 ms and
   200s take 2.4 s.
3. An instrument pointed at memory it is structurally unable to see.

## Two things worth carrying forward

**`tracemalloc` cannot measure protobuf decode memory.** The `upb` runtime allocates
its message arena in C++, outside Python's allocator. The isolated control decodes a
9.4 MB VBB body and `tracemalloc` reports **236 bytes** while RSS moves 37 MB. Gate 5's
memory benchmark must therefore be an **RSS measurement**, not a `tracemalloc` one —
which is a method constraint PLAN section 7's container requirement did not state, and
now does not have to be rediscovered inside the benchmark.

**The first version of the decode-peak control was wrong**, and its being wrong is what
produced the answer. It assumed retained `FeedMessage` objects explained the figure; the
control showed `tracemalloc` cannot see them, which forced the search to what it *can*
see — the per-entity `bytes` objects `Snapshot` retains. The capture keeps the disproof
rather than presenting only the conclusion.

## A note on dates

`captured_at` in both files reads `2026-08-29T22:34Z`. The documents these corrections
land in are dated **2026-08-30**, which is the local date (Europe/Berlin, UTC+2) at that
instant. Same moment, two calendars; recorded here so the difference is not read as a
backdated artefact.

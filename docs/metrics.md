# Measured numbers

Every figure here was observed. Nothing is estimated, and nothing derived from a synthetic fixture
appears in this file. Where a number is unreliable it says so and why, rather than being omitted or
quietly presented as sound.

---

## Stage 0 — feed probe

### Run 1 — 2026-08-28, keyless feeds

**Stopped at ~16 minutes of a planned 60.** Not a failure: gtfs.de was moving 1.2 GB in that window
and heading for ~4.5 GB across the hour from a free community service, and its server had already
disconnected us twice. Halting was the correct call and the data is intact. 207 observations.

Poller: three feeds, conditional requests from the second fetch, single-flight per feed, sliding-window
rate ceiling. Clock offset recorded, not applied.

| Feed | Requests | Wire | 304 rate | Entities (median) | `entity.id` | Header timestamp | Parse failures |
|---|---|---|---|---|---|---|---|
| gtfs_de | 54 | 1206.5 MB | 41.5% | 163,819 | stable | **generation** | 0% |
| vbb | 137 | 101.2 MB | 64.0% | 9,027 | stable | **generation** | 0% |
| ovapi_tripupdates | 16 | 30.8 MB | 0.0% | 13,834 | stable | **generation** | 0% |

**All three feeds carry a real generation timestamp.** The `feed_freshness` SLI (ADR 0002) is
therefore meaningful for all three. No feed needed the `echo` fallback.

#### Cadence — two of three figures are not feed properties

| Feed | Configured interval | **Achieved** | Observed cadence | Nyquist limit | Resolvable? |
|---|---|---|---|---|---|
| gtfs_de | 5s | **17.8s** | 30s | 35.6s | **no** |
| vbb | 5s | 5.12s | 16s (p95 31s) | 10.2s | yes |
| ovapi_tripupdates | 60s | 62.0s | 60s | 124s | **no** |

The configured interval is a sleep *after* each request completes, so a slow fetch widens the real
one: gtfs.de was configured at 5s and achieved 17.8s because each 40 MB fetch took 12–27s. Only
VBB's cadence was sampled fast enough to be a property of the feed. The other two are our sampling
grid and are **not** recorded as feed cadences.

**gtfs.de's cadence was resolved separately in run 1b**, by HEAD, at 10s sampling — see below.

#### Payload and transport

| Feed | Wire per fetch | Decompressed | `Content-Encoding` |
|---|---|---|---|
| gtfs_de | **38.0 – 54.3 MB** (p50 42.0 MB, n=123) | same | **none** |
| vbb | 2.03 MB | 9.39 MB | gzip |
| ovapi_tripupdates | 1.93 MB | 5.74 MB | gzip |

**gtfs.de does not compress.** `Accept-Encoding: gzip, deflate` was sent on every request and no
`Content-Encoding` came back. At the ratios the other two feeds show, it is shipping roughly 4×
more than it needs to.

> **CORRECTED 2026-08-30.** This paragraph read *"gtfs.de is the **only** probed feed that does not
> compress"*. That was true of the three feeds in run 1 and **false from run 2 onward**, where both
> HSL endpoints also returned no `Content-Encoding`. The capture was never wrong — a uniqueness
> claim was simply not re-checked when the population it quantified over grew. Full counts, both
> runs, every observation:
> [`runs/stage0-corrections/`](../runs/stage0-corrections/compression-and-304-floor.txt).
> The gtfs.de exclusion arithmetic below is unaffected: it rests on 42 MB per fetch, not on being
> alone in that.

#### Clock

NTP offset **−1.01s** at run start, −0.97s at end. The machine clock is a full second out. Every
lag figure derived from a header timestamp carries that correction; it is recorded, not applied, so
it stays visible. HTTP `Date` alone, at 1-second resolution, could not have detected a 1-second bias.

---

### Run 1b — 2026-08-28, gtfs.de by HEAD, full hour

Run 1 could not resolve gtfs.de's cadence at any affordable GET rate. Run 1b sampled `Last-Modified`
by HEAD every 10s, punctuated by a small number of full GETs for the tests that need a payload.

**59.9 minutes, 351 requests, 201.5 MB.** 342 HEAD, 9 GET. 120 generations observed.

| | |
|---|---|
| **Cadence (Last-Modified)** | **p50 30.0s**, p95 34s, min 25s, max 36s, stdev 2.0s, n=119 |
| Sampling | 10.09s achieved interval, Nyquist limit 20.18s → **resolvable, not flagged** |
| Payload | 38.0 – 54.3 MB, p50 42.0 MB (n=123 `Content-Length` observations) |
| 304 rate | 65.9% |
| Entities | 178,942 median |
| Header timestamp | **generation** — Tests C and E, both available |
| Parse failures | 0% |

Three things this run confirmed beyond the cadence:

- **Test C worked.** Run 1 lost it on this feed because the re-polls returned 304; with validators
  suppressed on body-seeking requests, the pair returned two payloads and voted `generation`. The
  fix is verified against the feed that exposed the bug.
- **A real NTP failure was recorded correctly.** The end-of-run sync failed and the manifest holds
  `offset_ms: null, sync_failed: true` — not zero. The rule earned its place on live data rather
  than in a test.
- **Sleep-after-completion only bites when fetches are slow.** Configured 10s achieved 10.09s here,
  against 5s achieving 17.8s in GET mode. Recorded in ADR 0005.

---

### HSL (FI) — resolved 2026-08-28, **no API key required**

Checked before committing to a registration, and it reorders the critical path.

`api.digitransit.fi` **does require registration and a `digitransit-subscription-key`** — but its
GTFS-RT endpoints are **deprecated**: *"GTFS-RT APIs (service alerts and trip updates) hosted at
api.digitransit.fi have been deprecated."* The replacement is a different host, `realtime.hsl.fi`,
and its documentation states no authentication requirement.

Verified empirically with one zero-body HEAD per endpoint — all 200, no auth challenge:

| Endpoint | `Content-Length` | Documented cadence | Validators |
|---|---|---|---|
| `https://realtime.hsl.fi/realtime/trip-updates/v2/hsl` | **1.27 MB** | 15s | ETag + Last-Modified |
| `https://realtime.hsl.fi/realtime/vehicle-positions/v2/hsl` | 122 KB | 1s | ETag + Last-Modified |
| `https://realtime.hsl.fi/realtime/service-alerts/v2/hsl` | 51 KB | 5 min | ETag + Last-Modified |

`Content-Type: application/x-protobuf`, `Cache-Control: max-age=5` (1s for vehicle positions), HEAD
supported. Trip updates are **33× smaller than gtfs.de's 42 MB**, so this feed is affordable to
sample at a rate that actually resolves a 15s cadence — the thing gtfs.de made impossible.

*Sources:* [Digitransit realtime APIs](https://digitransit.fi/en/developers/apis/5-realtime-api/)
for the deprecation, [HSL GTFS-RT feeds](https://hsldevcom.github.io/gtfs_rt/) for the endpoints and
cadences. *Checked:* 2026-08-28.

**Licence: `CC-BY-4.0`, verified 2026-08-28** from HSL's Terms of Use, read in a browser after the
page returned HTTP 403 to automated fetch:

> *"All data sets and APIs (with the exception of the Journey Planner OSM data listed below) are
> licensed under Creative Commons BY 4.0 International Licence (as of 1 September 2015). When using
> the data, please cite the Licensee and the time when HSL delivered the data (e.g. © HSL 2016)."*

**Attribution: `© HSL <year of delivery>`.** The worked example fixes this at year granularity, so
there is **no per-row obligation** — we already retain a fetch timestamp per observation and that
more than satisfies it.

**The ODbL exception does not reach GTFS-RT.** It is scoped to *"the Journey Planner's data geometry
and address data based on OpenStreetMap"*, applying *"to part of the routing, geocoding and map API
data"* — the journey-planner APIs. Trip updates and vehicle positions are HSL's own operational
data. The other carve-out, city bike OD data owned by City Bike Finland, is unrelated to us.

**Schema note: this attribution string is not static.** `© HSL 2026` goes stale at year end. Every
other `attribution` value recorded so far is a fixed string, so the field has been treated as a
literal. At least one real tenant needs it to be a template. Flagged for the Stage 2 schema, not
solved here.

---

### Run 2 — 2026-08-28, **VOID**

Four keyless endpoints, one hour. **Discarded: 6.3% coverage.**

The machine slept for **56.2 minutes of the 60-minute window**, leaving 3.8 minutes of actual
polling across 165 observations. Sleep suppression had reported itself asserted;
`SetThreadExecutionState` prevents idle sleep but not lid-close, hibernate or modern-standby
suspension, and something in that family took the process out.

**The more serious part is that the poller called it `complete`.** It had gap detection in the
analyser, but nothing at the run level that could refuse to declare success — so a run that was 94%
hole produced a manifest saying it had finished normally, and exited zero. That is the failure this
project exists to prevent, appearing in the instrument rather than in a gate.

Fixed: the poller now measures what fraction of the intended window it was actually polling, marks a
run `degraded` below 90%, prints why, and exits non-zero. Sleep suppression is recorded as
*requested* rather than *achieved*, because run 2 proved those are different things. Regression
tests cover the run 2 shape, a healthy run, and ordinary scheduling jitter that must **not** read as
a suspension.

No numbers from this run appear anywhere in this file.

---

### Run 2 — 2026-08-28, four keyless endpoints, full hour

**59.9 minutes, 2705 observations, 890 MB, coverage 99.9% with zero gaps.** The first run to pass
the coverage check that run 2's void attempt caused to exist.

| Feed | Reqs | Cadence | 304 | False-200 | Entities | Header timestamp | Parse fail |
|---|---|---|---|---|---|---|---|
| `vbb` | 562 | **29.0s** | 70.0% | 0 | 8,309 | generation `[moderate, 2/5]` | 0% |
| `hsl_tripupdates` | 590 | **15.0s** | 58.6% | 3 | 1,261 | generation `[moderate, 2/5]` | 0% |
| `ovapi_tripupdates` | 61 | 60s ⚠ (resolved in 2b) | n/a¹ | 0 | 10,932 | generation `[strong, 4/5]` | 0% |
| `hsl_vehiclepositions` | 1492 | 2.0s ⚠ | n/a¹ | 0 | 849 | generation `[weak, 1/5]` | 0% |

¹ Sampled at or slower than the cadence, so the 304 ceiling is near zero and the observed rate is
uninterpretable — not impossible, but too close to zero to distinguish server behaviour from
sampling. See the correction below. OVapi's was resolved in run 2b; `hsl_vehiclepositions`' remains
unmeasured.

Achieved intervals tracked their configured values throughout (5.16s / 61.79s / 5.17s / 2.39s), so
none of these cadence figures is distorted by slow fetches the way gtfs.de's was.

#### CORRECTED: OVapi *does* honour conditional requests — and the first answer was a confound

**An earlier version of this file recorded the opposite, with a Gate 5 consequence attached. It was
wrong, and the way it was wrong is the more useful finding.**

Runs 1 and 2 polled OVapi at ~62s and saw **0 of 77 responses return 304**, every request carrying
both validators. That looked conclusive. Run 2b polled the same endpoint at 10s and saw **123 of 149
return 304 — 82.6%**.

The cadence is exactly 60s. Polling at ~62s means every request lands after a new generation, so
**a 304 was never possible**: the server had genuinely new content to send every time we asked. The
test had no opportunity to fire, and its silence was read as a result.

**A 304 rate is only interpretable when we poll more than once per generation.** Each generation
yields exactly one 200 and the rest 304s, so the ceiling is `1 − interval/cadence`. Every
interpretable measurement we hold sits just under its ceiling:

| Feed | Sampling | Cadence | Polls/gen | Ceiling | Observed | Interpretable |
|---|---|---|---|---|---|---|
| `ovapi` (run 2b) | 10.09s | 60.0s | 5.95 | 83.2% | **83.1%** | yes |
| `vbb` | 5.16s | 29.0s | 5.62 | 82.2% | 70.0% | yes |
| `hsl_tripupdates` | 5.17s | 15.0s | 2.90 | 65.5% | 58.6% | yes |
| `ovapi` (runs 1–2) | 61.79s | 60.0s | **0.97** | **≈0%** | 0.0% | **no — confounded** |
| `hsl_vehiclepositions` | 2.39s | ~2.0s (1–8s) | **0.84** | **≈0%** | 0.2% | **no — confounded** |

**Precisely: the two confounded rows are near-zero-ceiling, not impossible.** At 0.97 polls per
generation the sampling interval is only marginally longer than the cadence, so interval jitter can
still occasionally place two polls inside one generation. `hsl_vehiclepositions` demonstrates it:
its cadence varies between 1s and 8s, any generation outlasting 2.39s offers a 304 opportunity, and
it **did in fact return 3** of them. Our own data falsifies "impossible" for that row. The correct
statement is that the ceiling is close enough to zero that an observed rate cannot separate a server
ignoring validators from one never given the chance.

**`hsl_vehiclepositions`' conditional behaviour is therefore unmeasured**, not measured-as-zero. Same
host as `hsl_tripupdates`, which honours validators at 58.6%, so it probably does too — but probably
is not measured, and this file holds measured numbers.

**The generalisation.** This is Nyquist again, applied to a second quantity: *sampling at or near the
cadence destroys the information you are trying to collect*. The analyser already refuses to report
a cadence below Nyquist — but it happily reported a 304 rate from a sampling regime in which no 304
could ever occur, and produced a confident, actionable, wrong conclusion from 77 observations.
Volume of evidence is no defence when the measurement was structurally incapable of the answer.

**No Gate 5 consequence stands.** The earlier claim that OVapi offers no conditional-request savings
was false; at adequate sampling it saves as much as any other feed here.

#### The false-200 check fires on real data

`hsl_tripupdates` returned **3 false-200s** — a 200 carrying a body byte-identical to its
predecessor, despite the request carrying validators the server otherwise honours 58.6% of the time.

Small, and not itself a problem at that rate. Worth recording because it demonstrates the check is
**live rather than dead code**: a server that honours validators most of the time can still return a
redundant body, and Gate 5's bytes-saved claim would silently overstate itself without measuring
this. A 304 rate alone would have looked clean.

#### CORRECTED: HSL's conditional-request behaviour is at its floor, not at 89% of a ceiling

**Corrected 2026-08-30, while designing Gate 5.** The Gate 0 table below reads HSL's 58.6% against
a 65.5% ceiling, which invites the reading that it honours validators about 89% of the time. That
ceiling came from `1 − interval/cadence` with the interval taken as the **median** inter-request
gap. The distribution does not support a median: 304s return in 125 ms and 200s take 2.4 s, so the
median (5.17 s) sits on the 304 mode while the mean is 6.15 s.

Counted a way that needs no interval statistic at all, and is therefore not sensitive to which one
you pick — **a server honouring validators perfectly must still send one body per generation**:

| | |
|---|---|
| Window | 3,596 s |
| Cadence | 15.0 s, stdev **0.00 s** over 241 distinct stamps |
| Generations, and so the floor on bodies | **239.7** |
| + false-200s | 3 |
| + requests sent with no validator | 5 |
| **= predicted 200s** | **247.7** |
| **observed 200s** | **247** |
| residual | **−0.7** |

**Every avoidable body was avoided.** The only bodies beyond the floor are the 3 measured false-200s
and the 5 unconditional requests, and they account for the excess to within one response.

Two things this does *not* say. It is not a new measurement — the observations are unchanged and
Gate 0's verdict is unaffected, since criterion 3 asks that conditional-request behaviour be
*characterised*. And it does not transfer to the other feeds: the floor assumes one cadence across
the window, which holds for HSL (stdev 0.00 s) and not for VBB, whose 29.0 s is a p50 over a
degraded feed. **The control table in the capture shows VBB with a residual of 48 and explicitly
declines to read it.**
[`runs/stage0-corrections/compression-and-304-floor.txt`](../runs/stage0-corrections/compression-and-304-floor.txt).

#### HSL is served uncompressed — 1.075 MB per body, every time

`Accept-Encoding: gzip, deflate` was sent on all 590 requests and **no `Content-Encoding` came
back** on any of them; `body_bytes_wire` equals `body_bytes_decompressed` equals `Content-Length`
across all 247 bodies. Same for `hsl_vehiclepositions`. VBB (4.38×) and OVapi (2.77×) do compress.

| Feed | Bodies | Wire | Decompressed | Ratio | `Content-Encoding` |
|---|---|---|---|---|---|
| `hsl_tripupdates` | 247 | 265.6 MB | 265.6 MB | **1.00** | **none** |
| `hsl_vehiclepositions` | 1,489 | 152.4 MB | 152.4 MB | **1.00** | **none** |
| `vbb` | 172 | 353.9 MB | 1,549.0 MB | 4.38 | gzip |
| `ovapi_tripupdates` | 61 | 118.3 MB | 328.2 MB | 2.77 | gzip |

Per body, HSL trip updates: **mean 1,075,427 B, p50 1,077,198 B, range 992,845 – 1,169,988 B**.

This is a Gate 5 input, not trivia. Gate 5's bytes-saved prediction is computed from the wire
figure, and a reader who assumed HSL gzips like the other two would recompute it roughly 4× too
small. It also corrects the uniqueness claim in the run 1 section above.

#### The recorded decode-peak field is **not usable**, and this is what it measured

`runs/run2/analysis.json` carries `memory.single_message_decode_peak_bytes` per feed, and PLAN
section 7 names it as the input to Gate 5's memory sizing. **It is not a decode peak. Do not size
anything from it.** It is left in the run artefact rather than deleted — the artefact records what
the run produced — and is recorded here as unusable with the reason.

| Feed | Recorded "single message" peak | Actual decompressed body (p50) |
|---|---|---|
| `vbb` | **2,143,237,596** | 9,006,580 |
| `hsl_vehiclepositions` | 639,931,120 | 102,290 |
| `ovapi_tripupdates` | 589,118,703 | 5,380,383 |
| `hsl_tripupdates` | 331,021,092 | 1,077,198 |

Two defects compound, both demonstrated in
[`runs/stage0-corrections/decode-peak-not-a-decode-peak.txt`](../runs/stage0-corrections/decode-peak-not-a-decode-peak.txt):

1. **`tracemalloc` cannot see a protobuf decode at all.** The `upb` runtime allocates its message
   arena in C++, outside Python's allocator. The isolated control decodes a 9.4 MB VBB body and
   `tracemalloc` reports **236 bytes** while RSS moves **37 MB**.
2. **What it does see is cumulative.** `get_traced_memory()` is process-wide and `reset_peak()`
   lowers the peak only to the *current* total, which already holds every per-entity `bytes` object
   retained by earlier iterations. Replaying the analyser's loop reproduces the growth: 9.4 MB after
   one decode, 1.0 GB after 100, 1.66 GB after 169 — against the 2.14 GB recorded.

**The method constraint that follows, for Gate 5:** the decode benchmark must measure **RSS**, not
`tracemalloc`. PLAN section 7 already requires it to run inside a Linux container so architecture is
the only remaining confound; this adds that the instrument itself has to change. Indicative
single-decode RSS deltas from the control, CPython 3.12.5 / Windows AMD64 — **indicative only, and
not a sizing input**: HSL trip updates 6.8 MB for a 1.17 MB body, VBB 37.2 MB for 9.4 MB, OVapi
25.6 MB for 5.5 MB.

#### Evidence strength varies sharply between feeds

The same verdict, `generation`, rests on very different amounts of evidence:
`ovapi` on four tests, `vbb` and `hsl_tripupdates` on two, and `hsl_vehiclepositions` on **one**.

`hsl_vehiclepositions` is the weak case for a structural reason, not a data-quality one: at a 2s
cadence, three of the five tests have preconditions that a feed that fast cannot satisfy. Test D has
no entity timestamps to work with, Test B needs a cadence spanning more than two one-second
quantisation levels, and Test C needs a re-poll gap shorter than the cadence. Recording it as
`generation [weak, 1/5]` rather than plain `generation` is the honest form — see ADR 0004 §8.

---

### Run 2b — 2026-08-29, OVapi cadence by HEAD

Run 2 left OVapi's cadence below Nyquist and therefore unresolved, which put Gate 0 on an
interpretation. This run removed the question rather than arguing it.

**24.9 minutes, 149 requests, 0.00 MB over the wire, coverage 99.9%.** HEAD only — no bodies at all.

| | |
|---|---|
| **Cadence** | **60.0s exactly** — p50 60, min 60, max 60, **stdev 0.00s**, n=25 |
| Sampling | 10.09s achieved, Nyquist limit 20.18s → **resolvable, not flagged** |
| Conditional requests | **82.6% 304** (123 of 149), against a theoretical ceiling of 83% |
| Cost | zero body bytes |

OVapi is metronomic: twenty-five consecutive 60-second intervals with no variance whatsoever. That
is a stronger cadence result than any other feed here, and it cost nothing.

It also corrected a wrong finding — see below.

---

## Stage 1 — platform floor

### OCI Always Free allowance — re-verified 2026-08-29 at Gate 2

`PLAN.md` section 3 records the June 2026 halving and instructs re-verification at
provisioning, calling it "the number most likely to move under us again". Checked
against Oracle's primary page on 2026-08-29, at the start of Gate 2.

**Result: unchanged.** All three figures match what `PLAN.md` already records, verbatim.

| Resource | Allowance, quoted | Matches PLAN? |
|---|---|---|
| `VM.Standard.A1.Flex` | "the first 1,500 OCPU hours and 9,000 GB hours per month" — "For Always Free tenancies, this is equivalent to 2 OCPUs and 12 GB of memory" | yes |
| Block Volume | "a total of 200 GB of Block Volume storage, and five volume backups" — "apply to both boot volumes and block volumes combined" | yes |
| Object Storage (Always-Free-only) | "20 GB of combined Standard tier, Infrequent Access tier, and Archive tier data"; "50,000 Object Storage API requests per month" | yes |

*Source:* [Oracle — Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).
*Checked:* 2026-08-29.

**The arithmetic worth carrying.** 1,500 OCPU-hours ÷ 730 hours = **2.05 OCPU**, and
9,000 GB-hours ÷ 730 = **12.3 GB**. The monthly allowance is sized for exactly one
2-OCPU / 12 GB instance running continuously, with no room for a second. The single-node
limitation in [`limits.md`](limits.md) is therefore not a simplification we chose — it is
what the allowance pays for. A second node means either halving the first or leaving the
free tier.

Still unverified at this point, both flagged in `PLAN.md` section 3 and neither observable
before provisioning:

- **A1 capacity in Frankfurt.** Community reports say it provisions quickly where US
  regions do not. No primary source. Folklore until observed.
- **Idle reclamation** (below 10% CPU *and* 10% network over 7 days). Source not recorded.
  To be verified by observation, or the claim dropped.

### Findings

#### Documented cadence is unverified in either direction — and so is a short measurement

Three legs, and the argument needs all three.

| Feed | Documented | Measured | By |
|---|---|---|---|
| gtfs.de | 10s | **30s** | 119 intervals, 60 min |
| HSL trip updates | 15s | **15.0s** | 590 requests, 60 min |
| VBB | — | **16s → 29s** | our own 16-min run, then our own 60-min run |

**gtfs.de is wrong by 3×.** *"Er wird alle 10 Sekunden aktualisiert"*, and it delivers 30s with a
stdev of 2.0s. Not erratic — reliably three times slower than advertised, which is worse, because
erratic would have been noticed.

**HSL is exactly right.** Documented 15s, measured 15.0s. So the claim is *not* "vendor
documentation is wrong". It is that documented cadence is **unverified in either direction**, which
is a different and more useful statement: you cannot tell the accurate ones from the inaccurate ones
without measuring, so the cost of measuring is the price of knowing which case you are in.

**And our own short run was also wrong.** Run 1 measured VBB's cadence at 16s from 137 requests over
16 minutes. Run 2 measured 29s from 562 requests over a full hour. **We were off by nearly 2× using
our own instrument**, for the same reason gtfs.de's documentation is off: insufficient observation.
A measurement is not automatically better than a document; it is better when it has adequate
duration behind it, and worse when it does not.

That third leg is what makes this defensible rather than self-serving. Without it the finding reads
as "vendors are careless and we are rigorous". With it, it reads as "sampling duration determines
whether any cadence figure — theirs or ours — can be trusted", which is the claim that actually
transfers.

**Consequences**, recorded in ADR 0002:

- Provisional SLO targets come from measured cadence per tenant, never from a documented figure.
- A cadence measured over a short window is provisional too. VBB's 29s supersedes its 16s, and any
  figure gets re-derived over a full window before an SLO is calibrated to it.
- Measuring is cheap where the feed supports HEAD: a full hour of `Last-Modified` sampling cost
  201.5 MB against 1.2 GB of GETs that could not resolve the same number.

#### OVapi's licence stays `unresolved`, on purpose

Use is explicitly permitted — *"You are free to use this data"* — but there is no SPDX identifier and
no attribution string for general use. **No enquiry was sent to the operator and none is planned.**

The reasoning, having re-examined it rather than carrying the action forward as settled:

- **Nothing is unmet.** Attribution obligations bind on redistribution or public display. We do
  neither: payload blobs are gitignored and what is committed is hashes, sizes and headers.
- **OVapi is not load-bearing.** Once HSL proved keyless, Gate 0 closes on vbb and the two HSL
  endpoints without it.
- **`unresolved` is worth more than an answer.** It gives Stage 3's compliance gate a genuine tenant
  to reject, rather than a field every tenant passes by construction. Resolving it would remove the
  only real test subject that gate has.
- **It costs a volunteer service nothing.** The README asks consumers to identify themselves by
  User-Agent, which we do. It does not ask to be emailed.

Revisit only if OVapi is onboarded *and* something triggers the attribution obligation — or later,
deliberately, if Stage 3 should demonstrate the full cycle: gate blocks, licence resolves, gate
passes.

#### gtfs.de is characterised and **excluded as a tenant**, on measured resource grounds

Not a gap in the probe. A documented rejection with arithmetic behind it.

- **Bandwidth.** 42 MB uncompressed per fetch (p50; up to 54.3 MB) against a measured 30s cadence.
  Tracking it at a 2× oversample is 240 fetches/hour ≈ **10.1 GB/hour**; merely keeping up, 120
  fetches/hour ≈ **5.0 GB/hour**. Continuous and unattended, from a sponsored volunteer service.
- **Slowing down does not rescue it.** At 5-minute polling the traffic is still ~363 GB/month, *and*
  freshness becomes meaningless against a 30s upstream. Both properties fail together.
- **Storage and write load.** 178,942 entities per snapshot, twice a minute, into a single Postgres
  instance shared with every other tenant on a 12 GB node.
- **Licence is clean** — CC BY-SA 4.0, attribution `gtfs.de`, checked 2026-08-28 — so the exclusion
  is purely a resource decision, not a legal one.

Recorded in PLAN.md section 9 as a limit **discovered by measurement**, not assumed. (`docs/limits.md`
does not exist yet; PLAN.md section 9 is its source text and carries this.)

#### VBB's 304 rate is inflated by its own degradation

64% of VBB responses were 304. **This is not a clean "bytes saved by conditional requests" figure
and must not be quoted as one.** VBB has been degraded since 2026-06-04, and a frozen upstream
honours conditional requests trivially — there is nothing to change. Its semantic churn was **1.7%**,
below the 5% static-content floor, which is the same fact seen from the other side. A conditional-request
saving figure has to come from a healthy feed.

#### VBB's static-content guard fired on live data

Test A was correctly marked **unavailable** for VBB: 9,027 entities but only 1.7% semantic churn.
Near-identical content alongside a legitimately advancing timestamp is Test A's echo signature
arriving from the opposite cause, and reading it would have risked a false `echo` verdict on a feed
that stamps honestly. The other tests carried the verdict. The guard was built against a fixture and
then earned its place on a real degraded feed.

#### Test D was unavailable on all three feeds — and that has a Stage 1 consequence

Entity-timestamp coverage: **0.0 on gtfs_de, 0.0 on ovapi_tripupdates**, 1.0 on vbb (where no
snapshot was re-served often enough to see a trend).

ADR 0002's fallback for an `echo` feed is to use `max(entity timestamp)` as the freshness reference.
**For these producers that fallback does not exist.** A future feed that returns `echo` *and*
publishes no entity timestamps would have **no freshness reference at all** — not a degraded one, none.
Such a tenant cannot carry `feed_freshness` under any definition and must be excluded from it
outright. This needs to be explicit before Gate 8, not discovered there.

#### Conditional request behaviour

| Feed | Sent with validator | 304 | False-200 |
|---|---|---|---|
| gtfs_de | 52 | 41.5% | 0 |
| vbb | 136 | 64.0% | 0 |
| ovapi_tripupdates | 15 | **0.0%** | **1** |

OVapi returned no 304s in 16 requests and one 200 whose body was byte-identical to its predecessor.
Suggestive of validators not being honoured, but 16 requests is too few to conclude. Unresolved;
carry into the next run.

---

### Gate 0 — **PASSED**, 2026-08-29

Against the three "usable for ingest" criteria in PLAN.md section 6.6, which is now the sole
definition — section 6.7 defers to it rather than restating it, after the two diverged (ADR 0004 §9).

| Feed | 1. Parses reliably | 2. Update behaviour | 3. Conditional requests | **Ingest** | Header timestamp | **Freshness SLO** |
|---|---|---|---|---|---|---|
| `vbb` | 0% failures | **29.0s measured** | 70.0% 304, 0 false-200 | **yes** | generation `[moderate, 2/5]` | yes |
| `hsl_tripupdates` | 0% failures | **15.0s measured** | 58.6% 304, 3 false-200 | **yes** | generation `[moderate, 2/5]` | yes |
| `ovapi_tripupdates` | 0% failures | **60.0s measured** (2b) | 82.6% 304 (2b) | **yes** | generation `[strong, 4/5]` | yes |
| `hsl_vehiclepositions` | 0% failures | ~2s, undersampled — reason recorded | **unmeasured** (confounded) | not counted | generation `[weak, 1/5]` | — |
| `gtfs_de` | 0% failures | 30.0s measured | 41.5% 304 | **excluded on resource grounds** | generation | n/a |

**Three feeds meet all three criteria, and all three have a genuinely measured cadence.** The gate
passes under either the strict or the permissive reading of the original wording, so no
interpretation was required — which was the point of running 2b rather than arguing the case.

All three also carry `header_timestamp_trust: generation`, so `feed_freshness` (ADR 0002) is
applicable to each, with evidence strength recorded alongside the verdict.

**Deliberately not counted toward the gate:**

- **`hsl_vehiclepositions`** clears criteria 1 and 2 but its conditional-request behaviour is
  confounded by sampling, so criterion 3 is unmeasured. It is a usable *feed* — 1492 requests, 0%
  parse failures, and the only high-frequency workload characterised — but it does not clear the bar
  as written, and three feeds already do. Resolving it needs a run sampling faster than ~1s.
- **`gtfs_de`** is fully characterised and would clear every criterion, but is excluded as a tenant
  on measured resource grounds. A feed we will not run is not evidence that we can run three.

**What the gate does not claim.** Nothing here has been ingested, stored or served. Gate 0 asked
whether at least three feeds are usable and what their behaviour is, and that question is answered.
Whether the ingest service can actually keep up with them is Gate 5.

## Stage 1 — Gate 5, ingest service

### Predictions, written and committed BEFORE the run — 2026-08-30

**These are predictions, not thresholds.** Each is an extrapolation from Stage 0
measurements, with its provenance named. A run that comes back away from one of these is a
**finding to investigate, not a failure to fix by adjusting the number**. The predicted and
the observed value are both kept, permanently, side by side. A prediction quietly edited to
match a result is the failure this whole discipline exists to prevent.

Written before the run for the same reason PLAN.md section 6.6 defined "usable" before any
feed had been probed: so that nothing can be interpreted into passing afterwards.

| # | Quantity | Prediction | Provenance |
|---|---|---|---|
| 1 | **Parse failure rate** | **0%** | 247 of 247 HSL bodies decoded in Stage 0 run 2, zero failures. Classified by nature (`not_protobuf` / `parse_error` / `wrong_schema` / `empty_body` / `valid_but_empty`), never collapsed into one rate. |
| 2 | **Snapshot duplicate rate** (false-200s) | **~1.2%** of bodies | 3 of 247 in run 2. |
| 3 | **Entity suppression rate**, steady state | **~71%** | 1 − 0.2879 median churn, recomputed on 240 consecutive run-2 snapshots under the corrected key. **Not the 75% first derived** — see the correction below. |
| 4 | **Bytes saved by conditional requests**, at a 5s poll interval | **~66%** — about 250 MB transferred against a 776 MB counterfactual | 720 ticks/hour; a 15.0s cadence admits 240 generations, so ~240 bodies plus ~3 false-200s. Mean body 1,075,427 B, uncompressed. |
| 5 | **Ticks skipped** | **~2 per hour (~0.3%)**, none losing more than one tick | 2 of 247 body-returning fetches exceeded 5s in run 2, none exceeded 5.5s. At ~240 bodies/hour that is 240 × 0.0081 ≈ 1.9. Poisson at λ=1.9 puts 0–5 inside an ordinary hour; **above that, fetch latency has changed**, which is the thing worth knowing. |
| 6 | **Snapshots dropped** | **0** | A 2.4s fetch and ~1,300 entities against a 5s interval and depth 2. Non-zero is itself a finding. |
| 7 | **Achieved poll interval** | **5.0s**, mean and median | Fixed-rate scheduling (ADR 0005). Under the probe's sleep-after-completion the same configuration gave a 5.17s median and a 6.15s mean. |

**Prediction 4 is only meaningful against its stated poll interval**, and the interval is
part of the claim rather than a hidden knob — the same treatment ADR 0002 gives the poll
interval in `feed_freshness`. At a 15s interval against a 15s cadence the saving would be
~0 by construction.

#### The suppression prediction was corrected before the run, not after

The first prediction was **75%**, from `median_churn_keyed_on_semantic_key: 0.250` in
`runs/run2/analysis.json`. Building the service found that number to be an artefact.

**HSL publishes no `trip_id` at all** — 0 of 1,348 entities in every snapshot checked. It
identifies trips by GTFS-RT's other permitted form, `route_id` + `direction_id` +
`start_date` + `start_time`. The Stage 0 analyser's semantic key is `(trip_id, start_date)`,
so on this feed it collapses an entire snapshot into **one key per start_date — four keys for
1,348 entities.**

Every figure computed on that key inherits the collapse:

| Keying | Distinct keys | Median churn | What it means |
|---|---|---|---|
| `(trip_id, start_date)` — Stage 0's | **4** | 0.2500 | one of four date-buckets changed |
| `(route_id, direction_id, start_date, start_time)` | **1,348** | **0.2879** | ~29% of trips changed |
| `FeedEntity.id` | 1,348 | **0.2879** | identical to the corrected key |

The tell was always in the data: the old key's churn has a **p95 of 0.75** — three of four
buckets — which is not a shape a real key over 1,348 entities produces. Recomputed over 240
consecutive run-2 snapshots; see `runs/gate5/`.

**Two consequences beyond the prediction.**

The corrected semantic key and `FeedEntity.id` agree to four decimal places on this feed, so
**the two keyings do not disagree here at all** — which is a cleaner result than Stage 0
recorded, and reached for a different reason.

And ADR 0004 section 4's `id_vs_semantic_persistence_ratio`, the statistic that declares
`entity.id` stable, was computed for HSL as a ratio **against a denominator over four keys**.
Its verdict of `stable` is corroborated by the corrected numbers above, but the evidence that
produced it was degenerate. The other three feeds are unaffected: VBB, OVapi and
`hsl_vehiclepositions` all populate the fields their keys use. **This is a defect in the key,
not in the ratio method.**

### Observed, 2026-08-30 — the hour run

**719 requests, 08:07:18–09:07:18 UTC, coverage 99.9%, exit 0.** Every prediction is kept
as written; nothing below edits row 1–7 of the table above. Evidence:
[`runs/gate5/hour-run-report.json`](../runs/gate5/hour-run-report.json),
[`hour-run-database.txt`](../runs/gate5/hour-run-database.txt) (read back independently
from Postgres, not from the JSON the run itself wrote),
[`hour-run-console.txt`](../runs/gate5/hour-run-console.txt).

| # | Quantity | Predicted | Observed | |
|---|---|---|---|---|
| 1 | Parse failure rate | 0% | **0%** (0/241) | match |
| 2 | Snapshot duplicate rate (false-200) | ~1.2% | **0%** (0/241) | **diverges — see below** |
| 3 | Entity suppression, steady state | ~71% (71.21%) | **71.95%** | match |
| 4 | Bytes saved, at 5s interval | ~66% (66.26%) | **66.48%** | match |
| 5 | Ticks skipped | ~2 (Poisson λ=1.9, range 0–5) | **1** | within range |
| 6 | Snapshots dropped | 0 | **0** | match |
| 7 | Achieved poll interval | 5.0s mean/median | **5.007s mean, 5.0s p50** (max 10.0s, the one skip) | match |

#### Row 2 — a real divergence, recorded unresolved

**Predicted ~1.2% false-200s (3 of 247, from Stage 0 run 2). Observed 0 of 241.** Zero is a
different claim from "fewer than expected", and it is stated as unresolved rather than
explained, per the rule this file has followed since Stage 0: a plausible story is not
evidence.

Candidate mechanisms, none asserted:

- **HSL's behaviour genuinely changed** between 2026-08-28 (Stage 0) and 2026-08-30 (Gate 5)
  — different time of day, different load, a server-side change. Nothing here measures that;
  it is a hypothesis, not a finding.
- **The interval changed what is observable.** Stage 0 ran at a 5.17s achieved interval
  (sleep-after-completion); Gate 5 ran fixed-rate at 5.0s. A false-200 requires the server to
  regenerate identical content between two polls that both land inside one generation window,
  so a tighter interval could plausibly narrow that window — but this is arithmetic about a
  mechanism, not a measurement of one, and 5.17s vs 5.0s is a small difference to hang a
  causal claim on.
- **3-in-an-hour may have always been inside the noise** for a rate this low. 3/247 has wide
  uncertainty at that sample size; 0/241 is not obviously incompatible with a true rate of
  ~1%. Distinguishing "the rate changed" from "the rate was never precisely 1.2%" needs more
  than two one-hour samples.

**What would resolve it:** repeat one-hour runs at different times of day, holding the
interval fixed, so the number of samples grows rather than the number of untested hypotheses.
Not done here — this run answers Gate 5's own verification criterion regardless of which
mechanism, if any, explains row 2.

#### Body size moved 30% between Stage 0 and Gate 5 — the same lesson as VBB, from a new angle

**Predicted 1,075,427 B mean body (Stage 0 run 2). Observed 749,170 B mean body — 30%
smaller.** Prediction 4's percentage landed close anyway (66.26% predicted, 66.48% observed)
because it is a *ratio* — bytes-saved-over-counterfactual is close to scale-invariant in body
size, so a right answer arrived through a metric insensitive to the thing that actually moved.
The absolute bytes did not land close: **172 MB transferred**, not the ~250 MB the prediction
arithmetic implied from Stage 0's body size.

**This is Stage 0's single-hour-duration finding again, from a new direction.** Section
"Documented cadence is unverified in either direction" above records that VBB's own cadence
moved from 16s (a 16-minute sample) to 29s (a 60-minute sample) — Stage 0's own instrument,
under-sampled, disagreeing with itself. This is the same limitation seen in a different
variable: **Stage 0 measured HSL's payload size from one hour on one day, and that hour never
saw HSL's payload vary by time of day.** A single-hour Stage 0 sample cannot distinguish "this
is what the feed sends" from "this is what the feed sent between 15:16 and 16:17 on
2026-08-28." Nothing here says which explanation is right — only that 30% is too large a gap
to file as noise, and too small a sample (two one-hour windows) to explain.

Not a Gate 5 defect: the pipeline handled the smaller payload correctly, and every downstream
number (suppression, bytes-saved-fraction) is internally consistent with what actually arrived.
It is a limit on what Stage 0's evidence duration can support, discovered by a second gate
built on top of it — which is exactly the shape the cadence finding predicted would recur.

#### The key-collapse guard held under an hour of live traffic, not just Stage 0 snapshots

**1,745 distinct trips over the run. 1,745 distinct primary keys. Zero collisions.**
`assert_key_is_a_key()` (ADR 0004 §8, instance 9) never fired, because the key never needed
refusing — confirmed by reading the primary key back out of Postgres independently
(`runs/gate5/hour-run-database.txt`, section 7), not by trusting the run's own counters.

This is the corrected key — `route_id`+`direction_id`+`start_date`+`start_time` — verified
against real traffic accumulated over an hour, where the collapsed key would have shown at
most a handful of distinct values regardless of how many trips actually ran. It is the ninth
guard dimension named in ADR 0004 §8, confirmed on data no fixture produced.

## Still unmeasured

- **`hsl_vehiclepositions` conditional-request behaviour** — needs sampling faster than its cadence
  to be measurable; at 2.39s against a 1–8s cadence the 304 ceiling is near zero (3 were observed
  out of 1492, so opportunities exist but are far too rare to read anything from).
- **`hsl_vehiclepositions` cadence** — resolving a 1s cadence needs sustained 2+ requests/second,
  which is not a reasonable ask of a public API. "Updates at least every 2s" is what the data
  supports.
- **opentransportdata.swiss (CH)** — needs an API key. Not blocking; a fourth tenant whose value is
  that it forces real per-tenant secret handling and a real rate limiter for Stage 2 and Stage 3.
- **OVapi licence** — deliberately `unresolved`; see the finding above.
- Ingest memory sizing: single-message decode peak × queue depth × safety factor, to be measured in
  a Linux container so architecture is the only remaining confound. **The Stage 0 field that was
  meant to supply the first term does not** — see *The recorded decode-peak field is not usable*,
  above — so this term has no value at all yet, rather than a rough one. It must be measured by
  **RSS**, not `tracemalloc`.
- Everything from Stage 1 onward: rebuild drill time, onboarding manual-step count, Prometheus
  series per tenant, SLO attainment.

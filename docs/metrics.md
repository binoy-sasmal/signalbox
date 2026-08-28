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

**gtfs.de is the only probed feed that does not compress.** `Accept-Encoding: gzip, deflate` was
sent on every request and no `Content-Encoding` came back. At the ratios the other two feeds show,
it is shipping roughly 4× more than it needs to.

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

### Findings

#### Vendor documentation was wrong about cadence by 3×, and this generalises

**gtfs.de documents 10-second updates and delivers 30.** Measured across a full hour by HEAD against
`Last-Modified`, 119 intervals: **p50 30.0s, p95 34s, min 25s, max 36s, stdev 2.0s**. The documented
figure is unambiguous — *"Er wird alle 10 Sekunden aktualisiert"* — and it is off by a factor of
three. The feed is not erratic; it is reliably three times slower than advertised, which is worse,
because an erratic feed would have been noticed.

This is the single most transferable finding in Stage 0, and it is **not** about the feed we are
dropping. It applies to every tenant we will ever onboard:

- **An SLO target set from vendor documentation would have been wrong before a single datapoint
  arrived.** A freshness objective calibrated to a 10s upstream, against a feed that regenerates
  every 30s, would burn its error budget continuously while nothing was broken.
- **It would have been wrong in the safe-looking direction.** Documentation understating cadence
  makes a system look worse than it is; overstating it makes an alert threshold too loose to fire.
  Neither is detectable without measuring.
- **The measurement was nearly free.** A full hour of HEAD sampling cost **201.5 MB**, essentially
  all of it the handful of deliberate full GETs; the HEADs themselves moved no body bytes at all.
  The GET-based approach spent **1.2 GB in 16 minutes** and still could not resolve the cadence,
  because 17.8s sampling cannot see a 30s period. Cheaper *and* correct, which is not the usual
  trade.

Consequence, recorded in ADR 0002: **provisional SLO targets are set from measured cadence per
tenant, never from a provider's stated figure**, and the measured value is re-derived at onboarding
rather than assumed to hold. The plan already said targets recalibrate after two weeks of real data;
this says the *starting* target may not come from documentation either.

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

### Gate 0 status — **not passed**

Against the criteria in PLAN.md section 6.6, written before any of these numbers existed:

| Feed | Parses reliably | Update behaviour characterised | Conditional requests characterised | **Usable for ingest** | `generation`? | **Usable for freshness SLO** |
|---|---|---|---|---|---|---|
| vbb | yes (0%) | yes — cadence resolvable | yes, with the degradation caveat | **yes** | yes | **yes** |
| ovapi_tripupdates | yes (0%) | partial — undersampled, reason recorded | **no** — 16 requests, unresolved | **not yet** | yes | pending |
| gtfs_de | yes (0%) | yes — 30s by HEAD, n=119 | yes | characterised, **excluded on resource grounds** | yes | n/a |

**One feed clears the ingest bar.** Gate 0 requires three. The third and fourth come from run 2 with
the CH and FI keys; registration is a day or two, not a blocker. No fourth keyless feed will be
reached for to make the number up.

---

## Still unmeasured

- Run 2: opentransportdata.swiss (CH) and HSL (FI) — both need API keys.
- OVapi conditional-request behaviour over a full hour.
- Ingest memory sizing: single-message decode peak × queue depth × safety factor, to be measured in
  a Linux container so architecture is the only remaining confound.
- Everything from Stage 1 onward: rebuild drill time, onboarding manual-step count, Prometheus
  series per tenant, SLO attainment.

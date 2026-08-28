# Stage 0 feed probe

A throwaway measurement instrument, not v0 of the ingest service. It optimises
for evidence capture under adversarial conditions; the ingest service optimises
for throughput. Written to be deleted.

## Layout

| File | Role |
|---|---|
| `config.run1.yaml` | Per-feed schedule and limits. Run 1 = the three keyless feeds. |
| `poll.py` | Online. Captures evidence, analyses nothing. |
| `analyse.py` | Offline. Re-runnable at zero cost over captured evidence. |
| `allowlist.py` | Capture allow-list and redaction, shared by poller and checker. |
| `check_no_secrets.py` | Structural credential check. Pre-commit *and* CI. |

The poller/analyser split is the point: the header-timestamp analysis will be
wrong on the first pass, and re-running the analyser costs seconds where
re-running the poller costs polling budget.

## Before the first run

1. **Resolve `ovapi`'s `base_url`** from the provider's own documentation. It is
   `null` in the config and the poller refuses to start until it is set.
   Inventing a plausible URL is exactly what rule 6 forbids.
2. **Set a real contact in `user_agent`.** The poller refuses to start while the
   `<contact>` placeholder is present. gtfs.de is a free community service and
   720 requests an hour should be attributable to a contactable human.
3. **Capture licence and attribution manually** for each feed — licence page URL,
   SPDX identifier where one applies, attribution string verbatim, date checked.
   Not measurable by polling.
4. **Stop the machine sleeping** for the hour. Gaps are detected and reported
   from the `request_at` series rather than silently averaged across, but a gap
   is still lost evidence.

## Running

```sh
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -r scripts/probe/requirements.txt

# one hour, three feeds
.venv/Scripts/python.exe scripts/probe/poll.py scripts/probe/config.run1.yaml

# offline, re-runnable
.venv/Scripts/python.exe scripts/probe/analyse.py runs/run1
```

Create a file named `STOP` in the working directory to halt all polling cleanly
with captured data intact. Ctrl-C also flushes cleanly.

Enable the local hook once per clone:

```sh
git config core.hooksPath .githooks
```

## Safety properties

These are the parts worth reading before changing anything.

- **Single-flight per feed is structural**, not enforced by a check: each feed is
  a sequential loop that awaits its response before scheduling the next request.
  A timer-driven design could overlap requests on a slow response and silently
  double our rate.
- **The limiter is a sliding window, not a fixed window.** A fixed-window
  "N per minute" counter permits 2N requests in a moment across a window
  boundary, which trips a server enforcing a true sliding window.
- **Retries consume rate budget.** There is no immediate-retry path anywhere.
- **`halve()` is one-way.** Multiplicative decrease with no increase; a probe
  should never walk back into a limit it already hit.
- **No deliberate rate-limit provocation, on any feed.** A 429 is recorded in
  full if it arrives, but we do not chase one. VBB is degraded, so provoking it
  would perturb an upstream that is not behaving normally.
- **NTP offset is recorded, not applied**, and a failed sync records `null` with
  a flag — never `0`. A silent zero would be a fabricated measurement lending
  unearned precision to every derived lag figure.

## Credential hygiene

Two mechanisms, both live from run 1 even though run 1 has no keyed feed —
retrofitting them once a key exists is how the leak happens.

1. **Headers by allow-list.** Anything not named in `allowlist.py` is dropped at
   capture time, never redacted afterwards. `Authorization` and `*api-key*`
   headers have no field to land in.
2. **Endpoints stored split** — `base_url` plus a query map, with auth-bearing
   parameters written as `<redacted:auth_ref>`. Never a joined URL, because
   some transit APIs authenticate by query parameter and a resolved
   `...?apikey=...` would put a live key in the run manifest, which the header
   allow-list does not inspect.

`check_no_secrets.py` asserts both across **every committed file**, and runs in
CI as well as pre-commit: `--no-verify` bypasses a local hook, and a local gate
is feedback while only the enforced gate is enforcement.

## Reading the header-timestamp verdict

`generation`, `echo`, or `unknown`, per feed. It decides whether Gate 8's
`feed_freshness` SLI means anything for that tenant (ADR 0002).

- **Test A is unavailable on static or near-static content.** A degraded
  producer that still regenerates on schedule but emits a near-empty snapshot
  yields identical content alongside a legitimately advancing timestamp — Test
  A's echo signature from the opposite cause. The analyser detects the condition
  and marks the test unavailable rather than misreading it. This applies to VBB.
- **Test C is unaffected by static content** and carries the verdict there.
- **Disagreement between available tests records `unknown`.** It is not resolved
  with a narrative. Per-test votes are in `analysis.json` for a human to read.

Churn is reported twice — keyed on `FeedEntity.id` and on the semantic key —
because `FeedEntity.id` is scoped to uniqueness *within a FeedMessage* and a
compliant `FULL_DATASET` producer may regenerate it every snapshot. Keying on
it alone would report ~100% churn on a stable feed. **Disagreement between the
two is the finding**, and it is what tells us what dedup must key on.

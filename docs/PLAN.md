# Signalbox — Project Plan

> **Signalbox** — a multi-tenant control plane for public realtime transit feeds, where
> onboarding a new data source is one merged pull request.

**Status:** planning complete, Stage 0 not started
**Owner:** Binoy
**Last updated:** 2026-08-28

---

## 1. What this is

Signalbox is a multi-tenant control plane for ingesting public realtime transit data feeds,
where each upstream data source is an isolated tenant.

**Headline capability:** onboarding a new tenant is one merged pull request. A contributor adds
a tenant definition file; the platform provisions an isolated ingest pipeline, storage, resource
quotas, dashboards and alerts, with no human touching a cluster.

**Naming rule:** the word is **tenant**, never "region", in code, docs, variable names and
commit messages. Tenants here are logical and all run on one node in Frankfurt. Calling them
regions would assert a geographic distribution this system does not have.

**Why it exists:** to close a specific infrastructure gap with one coherent, defensible system
rather than a pile of disconnected tutorials. Prior experience is applied GenAI and backend
(Python, FastAPI, Docker, GitHub Actions, PostgreSQL, deploying onto a managed Kubernetes
runtime). No prior experience with Terraform, Ansible, Prometheus, Grafana, OpenTelemetry,
Helm, ArgoCD, or a policy engine, and no experience operating a cluster below a managed
platform layer.

**The project must be defensible in a technical interview.** That constraint outranks speed.

---

## 2. Working agreement (read this before writing anything)

These rules exist because the goal is understanding, not a finished repo.

1. **Explain before you build.** For any real decision, state the options, the tradeoff, and
   your recommendation. Wait for a decision. Do not write config and explain it afterwards.
2. **One gate at a time.** The plan below has numbered gates. Complete and verify one gate,
   then stop and report. Do not scaffold ahead into later stages.
3. **No manual cluster changes, ever.** No `kubectl apply`, no `kubectl edit`, no console
   clicking. Everything reaches the cluster through git and ArgoCD. `kubectl get`, `describe`
   and `logs` for inspection are fine.
4. **Verification is falsifiable.** A gate is passed when a specific test produces a specific
   observed result, not when the config looks correct. If a gate cannot be verified, say so
   and stop.
5. **Write an ADR for each real decision** in `docs/decisions/NNNN-title.md`. Context, options
   considered, decision, consequences. Short is fine.
6. **Never invent upstream behaviour.** Feed cadence, rate limits, header semantics and licence
   terms come from the Stage 0 probe results, not from assumption.
7. **Record measured numbers in `docs/metrics.md`** as they are observed. This file is the
   evidence base for interview claims.
8. **No secrets in git in plaintext.** SOPS + age only. If something can't be encrypted, it
   doesn't get committed.
9. **Pin every version.** k3s, chart versions, container digests, provider versions, action SHAs.
10. **Be honest about limits.** Do not describe this system as more than it is. See section 9.

---

## 3. Decisions already made

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Feed set | Multi-country | Independent upstreams with genuinely different failure behaviour and jurisdictions. German operators alone do not provide enough independent open feeds. |
| 2 | Cloud | **Oracle Cloud Infrastructure Always Free**, Frankfurt | Zero cost, and more cloud surface to learn than a flat VPS: VCN, subnets, route tables, gateways, security lists, NSGs, IAM compartments and policies, block volumes, object storage. Fallback: Hetzner CX32 (~€7/mo) if capacity blocks us. |
| 3 | Terraform state | AWS S3, native S3 locking | Cheapest truthful AWS exposure. Costs cents. No DynamoDB lock table needed. |
| 4 | Secrets | SOPS + age | No runtime component, git-native audit trail, free. |
| 5 | Policy engine | **OPA / Rego** — Conftest in CI, Gatekeeper at admission | Forced by requirement: the CI gate validates a *Terraform plan*, which is not a Kubernetes object, so Kyverno cannot do it. One policy language for both gates. Rego also transfers beyond Kubernetes. |
| 6 | Stage 4 (AI triage agent) | **Deferred** until Stage 3 is solid | Lowest marginal learning value for this author; agentic AI is already an existing strength. Do not start it early. |

### Architectural boundary (non-negotiable)

The most common way this design goes wrong is two reconcilers fighting over the same objects.

- **Terraform owns cloud resources only.** Compute, network, volumes, IAM, DNS, object storage,
  and any per-tenant *cloud-side* resources. Terraform must never create in-cluster Kubernetes
  objects.
- **ArgoCD owns everything inside the cluster.** Namespaces, NetworkPolicies, ResourceQuotas,
  RBAC, Deployments, ServiceMonitors, PrometheusRules, dashboards.
- **One tenant definition is the single source of truth** (`tenants/<name>.yaml`), consumed by
  both: Terraform reads it for cloud-side resources, an ArgoCD **ApplicationSet with a git file
  generator** reads it to render one Helm release per tenant.

If asked in interview "why Terraform for cluster objects when you have ArgoCD?", the answer is
that we did not do that, and here is the boundary. The failure it avoids is not a crash: two
reconcilers over one object produce a **silent flapping loop**. ArgoCD self-heals what Terraform
just applied, the next `plan` reports drift, `apply` reverts it, ArgoCD reverts back. Nothing
errors, and both tools report healthy at different instants.

#### The one carve-out: Ansible at bootstrap

ArgoCD cannot install itself. Ansible may create in-cluster Kubernetes objects **exactly once, at
node bootstrap, and only the objects ArgoCD needs in order to begin managing itself.** After that
point Ansible never touches the cluster again. Every other in-cluster object, at every other time,
arrives through ArgoCD.

There are **three irreducible bootstrap steps, not one.** Name all three in the Gate 4 writeup and
in `docs/limits.md`:

1. **k3s install** — Ansible, pinned version. Nothing else can create the cluster.
2. **ArgoCD install** — Ansible, pinned chart version. The app-of-apps then assumes ownership of
   ArgoCD's own configuration, so this step is never repeated on subsequent runs.
3. **age private key delivery** — the SOPS decryption key must exist in-cluster as a Secret before
   ArgoCD can render any encrypted manifest. Terraform is forbidden from creating it, git cannot
   hold it, and ArgoCD cannot bootstrap it because it needs the key in order to do so. Ansible
   places it from the operator's local keyring.

Step 3 is the chicken-and-egg described in section 9. It is documented, not eliminated.

#### Objects that are neither cloud nor Kubernetes

Postgres schemas and roles live inside Postgres — not in the OCI API and not in the Kubernetes API
— so the boundary above does not assign them an owner, and a Job running SQL would be a third
reconciler with no drift detection. Resolved in
`docs/decisions/0003-postgres-object-ownership.md`: a Postgres operator with declarative CRDs
turns them into Kubernetes API objects, which places them under ArgoCD's existing ownership
without inventing a new exception.

#### What applies Terraform when a tenant PR merges

"Onboarding is one merged pull request" requires a defined apply path for the Terraform half.
ArgoCD covers the in-cluster half unprompted; Terraform has no equivalent trigger, and there is an
ordering dependency between the two consumers of `tenants/<name>.yaml` that must be specified
rather than raced. Recorded in `docs/decisions/0001-terraform-apply-path.md`.
**Status: proposed, not yet settled.**

### Cloud caveats to engineer around (OCI Always Free)

Every claim below carries its source and the date it was checked. **A claim with no source is not
a claim** — it is marked unverified and must not be relied on.

- **Allowance halved to 2 OCPUs / 12 GB** — 1,500 OCPU-hours and 9,000 GB-hours per month for
  `VM.Standard.A1.Flex`, which Oracle states is "equivalent to 2 OCPUs and 12 GB of memory".
  Effective **15 June 2026** with no public announcement; instances over the new limit were
  subject to termination from **18 August 2026**, a date that has now passed. 12 GB remains
  sufficient for this build, and since nothing is provisioned yet we simply provision within the
  limit from the start.
  *Source:* [Oracle — Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
  (primary; exact wording confirmed) and [InfoQ, July 2026](https://www.infoq.com/news/2026/07/oracle-cloud-free-tier-limits/)
  for the absence of an announcement. *Checked:* 2026-08-28.
  **Re-verify at provisioning (Gate 2).** This is the number most likely to move under us again.
- **Storage allowances.** Block volume: 200 GB total plus 5 volume backups. Object storage on an
  Always-Free-only tenancy: **20 GB combined across all tiers and 50,000 API requests per month.**
  The object storage figure is a hard constraint on any per-tenant bucket design in Stage 2 and
  feeds directly into ADR 0001.
  *Source:* same Oracle page as above. *Checked:* 2026-08-28.
- **ARM only.** All images must be arm64 or multi-arch (`docker buildx`, manifest lists).
- **No SLA and no change notification.** The June 2026 change is the proof. If Oracle changes
  something under us, write the postmortem; it is real incident material.
- A1 capacity is regional; Frankfurt is said to provision quickly where US regions often do not.
  *Source:* community reports, no primary source. **Unverified — treat as folklore until we
  observe it ourselves at Gate 2.**
- Oracle may reclaim instances idle below 10% CPU **and** 10% network over 7 days.
  *Source:* not recorded. **Unverified — supply the source or we verify at Gate 2 and record what
  we actually observe.** Either way, verify our workload stays clear rather than assuming it does.

### AWS account caveat

- Accounts created on or after **15 July 2025** no longer receive the 12-month free trial; they
  choose a **Free plan** or a **Paid plan** at signup. The Free plan ends when credits run out or
  after six months, followed by a 90-day grace period, after which **the account is closed and its
  resources are erased** — which would take our Terraform state with it. **Select the Paid plan.**
  It receives the same credits.
  *Source:* [AWS Free Tier Terms](https://aws.amazon.com/free/terms) and
  [AWS Billing — Explore AWS services with AWS Free Tier](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier.html).
  *Checked:* 2026-08-28.
- **Do not join an AWS Organization.** Joining an Organization, or a Control Tower landing zone,
  expires Free Tier credits **immediately** and makes the account ineligible to earn more. The
  join flow gives no warning and sends no email, so this is silent and irreversible.
  *Source:* [AWS Billing — Explore AWS services with AWS Free Tier](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier.html).
  *Checked:* 2026-08-28.
- Set an **AWS Budgets alarm at $1** on day one.

---

## 4. Tenant set (to be confirmed by the Stage 0 probe)

| Tenant | Jurisdiction | Auth | Known characteristics |
|---|---|---|---|
| VBB (Berlin/Brandenburg) | DE | none | `https://production.gtfsrt.vbb.de/data` — 60 req/min, ETag supported, CC-BY 4.0. **Known degraded since 2026-06-04**, upstream data source problem, no restoration estimate. |
| gtfs.de national | DE | none | `https://realtime.gtfs.de/realtime-free.pb` — 10-second updates, CC BY-SA 4.0, TripUpdates + ServiceAlerts. Aggregate feed, not a single operator. |
| opentransportdata.swiss | CH | **API key** | 2 queries/minute, sliding window. The most valuable tenant despite being the most awkward: forces real per-tenant secret handling and a real rate limiter. |
| OVapi | NL | none | `https://gtfs.ovapi.nl/nl/tripUpdates.pb` — endpoint confirmed 2026-08-28, 5.6 MB payload. Four separate endpoints exist (tripUpdates, vehiclePositions, alerts, trainUpdates); each is its own feed with its own verdict. **Licence and attribution `unresolved`** — see below. |
| HSL Helsinki | FI | **none** — verified 2026-08-28 | `https://realtime.hsl.fi/realtime/trip-updates/v2/hsl` — 1.27 MB, documented 15s, ETag + Last-Modified, HEAD supported. `api.digitransit.fi` *does* require a subscription key, but its GTFS-RT endpoints are deprecated and the replacement host needs none. Licence CC BY 4.0 **indicated, not verified** — hsl.fi returns 403 to automated fetch. |

Consequence for the tenant schema. These are **first-class fields from day one**, not retrofitted.
Every one of them is load-bearing for a later gate, and a gate cannot check a field that does not
exist:

| Field | Why it cannot wait |
|---|---|
| `rate_limit` | CH is 2 req/min. A poller without a per-tenant limiter cannot onboard it at all. |
| `auth_ref` | CH, and probably FI, need a key. Points at a SOPS-encrypted secret — never at a value. |
| `licence` | Stage 3's compliance gate rejects a tenant whose config contradicts its declared licence. |
| `attribution` | CC-BY and CC-BY-SA both oblige us to carry and display an attribution string. A licence obligation, not metadata. |
| `header_timestamp_trust` | `generation` / `echo` / `unknown`, set from the Stage 0 probe. Gate 8's `feed_freshness` SLO applies **only** to tenants marked `generation`. Without this field that SLO is silently meaningless for some tenants. |
| `incrementality` | `FULL_DATASET` vs `DIFFERENTIAL` changes the ingest design outright. Measured at Stage 0. |

**OVapi licence is `unresolved`, deliberately recorded as such.** Use is explicitly permitted by the
[OVapi README](http://gtfs.ovapi.nl/README) — *"You are free to use this data, but there is no
service level agreement (best-effort) nor are you allowed to say you represent or impersonate any of
the transit agencies listed here"* — but there is no SPDX identifier and no required attribution
string for general use. The README's citation block is scoped to a scientific usage policy, and
[Mobility Database](https://mobilitydatabase.org/feeds/gtfs_rt/mdb-1645) points at a different terms
URL. Checked 2026-08-28. **No enquiry was sent to `ovinfo@ovapi.nl` and none is planned.** Permission
to use is explicit, we neither redistribute nor display the data, and an unresolved licence gives
Stage 3's compliance gate a real tenant to reject rather than a field every tenant passes by
construction. Reasoning in `docs/metrics.md`. Revisit only if OVapi is onboarded *and* something
triggers the attribution obligation.

**This is better Stage 3 material than a clean answer would have been.** A compliance gate that
rejects any tenant whose `licence` is `unresolved` is the gate doing real work, rather than
validating a field that was populated for every tenant by construction. Carried into section 11.

The README also *requires* consumers to send a descriptive `User-Agent`, use conditional requests,
and accept gzip — which is independent confirmation that the probe's instrumentation rules are the
expected etiquette rather than our own invention.

---

## 5. Repository layout

```
signalbox/
├── CLAUDE.md                    # always-loaded context for Claude Code
├── README.md
├── docs/
│   ├── PLAN.md                  # this file
│   ├── metrics.md               # measured numbers, updated as we go
│   ├── limits.md                # honest statement of what this is not
│   ├── decisions/               # ADRs, NNNN-title.md
│   └── runbooks/
├── infra/
│   ├── terraform/
│   │   ├── bootstrap/           # AWS S3 state backend (chicken-and-egg: local state here)
│   │   ├── platform/            # OCI: VCN, subnets, NSGs, IAM, compute, volumes
│   │   └── modules/tenant/      # per-tenant cloud-side resources (Stage 2)
│   └── ansible/
│       ├── inventory/
│       └── roles/
├── tenants/                     # SOURCE OF TRUTH — one YAML per tenant
├── services/
│   └── ingest/                  # Python ingest service
├── charts/
│   └── ingest/                  # Helm chart
├── clusters/
│   └── prod/                    # ArgoCD app-of-apps, ApplicationSets
├── policy/
│   ├── ci/                      # Conftest Rego (Terraform plan, manifests, tenant defs)
│   └── admission/               # Gatekeeper ConstraintTemplates + Constraints
├── scripts/
│   └── probe/                   # Stage 0 feed probe
└── .github/workflows/
```

---

## 6. Stage 0 — feed feasibility spike

**Do this before writing any Terraform.** If two of the five feeds turn out unusable, the tenant
schema changes shape, and everything downstream changes with it.

The probe is a **throwaway measurement instrument, not v0 of the ingest service.** Its goal is
evidence capture under adversarial conditions; the ingest service's goal is throughput. Conflating
them produces a slow probe and an ingest service with the wrong bones. Write it to be deleted.

### 6.1 Structure — two separable halves

**Poller** (online): one task per feed, each with its own schedule and its own rate limiter,
writing raw evidence to disk and performing **no analysis whatsoever**.

**Analyser** (offline): runs over the captured evidence afterwards and produces the results table.

This split is the most important decision in the probe. The header-timestamp analysis will be
wrong on the first pass; this way we re-run the analyser in seconds rather than re-spending polling
budget we may not be able to afford on a rate-limited feed.

### 6.2 Two runs, because key acquisition must not block Gate 0

- **Run 1 — keyless feeds only** (DE ×2, NL). Starts immediately.
- **Run 2 — CH and FI**, once keys exist. Registration lead time is unknown and must not gate
  Stage 1.

Each run is one hour at full cadence, followed by a longer low-rate soak (12–24 h) for cadence
stability and downtime observation. The soak costs wall-clock and nothing else, and **does not
block Gate 0.**

### 6.3 What it records

- HTTP status distribution; whether auth is required and **in what form** — 401 with
  `WWW-Authenticate`, 200 with an error body, or query-parameter rejection. "Needs a key" is not
  enough detail to build a poller against.
- ETag / Last-Modified support, whether a conditional request actually returns 304, and the
  **false-200 rate**: a 200 whose body hash equals the previous body's hash means the server
  advertises validators it does not honour. Gate 5's "bytes saved by conditional requests" claim
  rests on that distinction.
- Observed update cadence — not a count of distinct `FeedHeader.timestamp` values but the
  **distribution of deltas** between consecutive distinct values (p50/p95/min/max). "10-second
  updates" with a p95 of 47 s is the finding.
- **Header timestamp trust** — whether the timestamp reflects real generation time or merely
  echoes serve time. Five independent tests; see 6.4. This decides whether the `feed_freshness`
  SLI means anything for that tenant.
- Payload size, plus `Content-Encoding`; total bytes/hour, which sizes both the ingest service and
  the archive. Two figures, both byte counts: **`body_bytes_wire`** (what crossed the network) and
  **`body_bytes_decompressed`** (after transport decompression). Protobuf "decoded size" is not a
  meaningful byte count and is not recorded — storage is sized from the decompressed wire figure.
- Entity counts by type (TripUpdate / VehiclePosition / Alert), and whether the mix is stable.
- Parse failure rate and the **nature** of failures: not-protobuf (an HTML error page — check
  leading bytes), truncated, wrong schema, valid but empty `entity`. Record
  `gtfs_realtime_version` and **`incrementality`** — a `DIFFERENTIAL` feed invalidates the
  assumptions most consumers make and would change the ingest design outright.
- **Entity churn between consecutive snapshots** — how many entities actually change. This sizes
  the write load and decides whether dedup is worth building at all. **Computed twice, on two
  different keys**, because `FeedEntity.id` is scoped to uniqueness *within a FeedMessage* for
  incrementality purposes: a compliant `FULL_DATASET` producer may regenerate it every snapshot.
  Keying churn on it alone would report ~100% churn on a perfectly stable feed and yield a wrong
  "dedup is impossible" finding.
  1. On `FeedEntity.id`.
  2. On the **semantic key** — `trip_id` + `start_date` for TripUpdate, `vehicle.id` for
     VehiclePosition.

  **Disagreement between the two is itself the finding**, and it is the one that tells us what dedup
  must key on. Report both numbers, never one.
- **The probe's own peak memory while decoding.** The only real number we will have for the ingest
  pod's memory request at Gate 5. Recorded as both single-message decode peak and whole-process peak
  RSS, with the platform it was measured on, since a figure from CPython on Windows is indicative of
  an arm64 Linux container rather than equal to it.
- Licence and required attribution string. Not measurable by polling: recorded manually per feed
  as licence page URL, SPDX identifier where one applies, the attribution string **verbatim**, and
  date checked.
- Downtime observed during the window, as runs of consecutive errors with durations. Labelled
  "observed in a 1 h window" — **an hour supports no availability claim and no such number reaches
  `docs/metrics.md`.**

Three instrumentation rules that are easy to get quietly wrong:

- **A descriptive `User-Agent` identifying the probe, with a contact address**, plus an explicit
  `Accept-Encoding`. gtfs.de is a free community service; 720 requests an hour should be
  attributable to a human who can be emailed. Anonymous polling of a volunteer-run feed is rude and
  gets IP ranges blocked.
- **If NTP sync fails** — UDP 123 is blocked on plenty of networks — record `clock_offset_ms` as
  `null` with a `sync_failed` flag. **Never report 0.** A silent zero is a fabricated measurement
  and would put an unearned precision on every lag figure derived from it.
- **Async re-poll requests are tagged** and excluded from the cadence distribution, since two
  deliberate 2-second-apart fetches would otherwise corrupt the statistic they exist to help
  interpret.

**No deliberate rate-limit provocation, on any feed.** 429 evidence is welcome if it arrives and is
recorded in full, but we do not chase it. VBB is already degraded, so provoking it would perturb an
upstream that is not behaving normally, and CH holds a revocable key we cannot afford to lose.

### 6.4 Header timestamp: generation time or echoed fetch time

Some producers stamp `FeedHeader.timestamp` at serve time rather than generation time. If so, the
freshness SLI measures nothing but our own poll offset plus RTT — it could never show upstream
staleness, and "what would this SLI look like if the upstream froze?" answers "it would look fine".

Five independent tests, all offline. No single one is conclusive; the verdict is the combination.
**Run A and C first** — they are the fastest to disambiguate.

- **A — body-modulo-timestamp hashing.** Hash each decoded FeedMessage with the header timestamp
  field zeroed. Two fetches with identical modulo-timestamp hashes but differing header timestamps
  means the producer restamped an unchanged snapshot: serve-time stamping. This test is why raw
  payloads are stored.
  **Test A is not authoritative on any feed whose content is static or near-static.** A degraded
  producer that still regenerates on schedule but emits a near-empty snapshot produces identical
  content alongside a legitimately advancing generation timestamp — Test A's echo signature from the
  opposite cause. Detect the condition mechanically (low entity count, low churn) and **mark Test A
  unavailable rather than reading it.** This applies to VBB, which has been degraded since
  2026-06-04.
- **C — asynchronous re-poll.** Twice per run, on keyless feeds only, issue two requests ~2 s apart
  off the normal grid. Same snapshot should carry the same timestamp; timestamps that differ by
  ~2 s and track our request times are echo behaviour, directly observed. Costs two requests.
  **Unaffected by static content**, so it remains authoritative on a degraded feed where Test A does
  not — it is the primary test for VBB.
- **B — shape of lag over time.** `request_at − header_timestamp`, clock-corrected. Real generation
  gives a **sawtooth** spanning roughly [0, cadence]; echo gives a **flat narrow band at
  approximately RTT**. Quantify as `stddev(lag) / observed_cadence`, and check whether lag ever
  exceeds the observed cadence — real timestamps sometimes do, an echo essentially cannot.
- **D — header vs entity timestamps.** Plot `header_ts − max(entity_ts)` across consecutive fetches
  of the same snapshot: a **rising staircase** is the echo signature, a flat small value is real
  generation. Record entity-timestamp coverage, since some producers omit them and the test is then
  unavailable.
- **E — cross-check against HTTP `Date` and `Last-Modified`.** Tracking `Last-Modified` supports
  real generation; tracking `Date` on every fetch is the echo signature seen from the HTTP layer.

**Verdict per feed, exactly one of:**

- `generation` — the `feed_freshness` SLI is meaningful for this tenant.
- `echo` — **meaningless**; exclude the tenant from the freshness SLO, or fall back to
  `max(entity timestamp)` where coverage allows.
- `unknown` — tests unavailable, or **available tests disagree**. No entity timestamps, too few
  distinct payloads, undersampled under a rate limit, or a conflict between tests. **Record
  `unknown`; do not guess, and do not resolve a conflict with a narrative.** Per-test votes are
  recorded alongside the verdict so a human can look. For CH at 45 s polling this is a likely and
  acceptable outcome.

Note for CH specifically: at 2 req/min we are below Nyquist for any cadence under ~90 s. Their true
generation cadence is **not measurable under the rate limit**, and `docs/metrics.md` says exactly
that rather than carrying a guess.

### 6.5 Credential hygiene in probe output

The observation log and the run manifest are committed to git, and the CH and FI feeds authenticate
with keys.

**Headers: explicit allow-list only** — `ETag`, `Last-Modified`, `Date`, `Content-Type`,
`Content-Encoding`, `Content-Length`, `Cache-Control`, `RateLimit-*`, `Retry-After`. Everything else
is dropped at capture time, never redacted afterwards. `Authorization` and any `*api-key*` /
`*subscription-key*` header has no field to land in.

**Endpoints are stored split, never as a raw URL.** Some transit APIs authenticate by *query
parameter* rather than header, so a resolved endpoint like `...?apikey=...` would put a live
credential into the run manifest — a file the header allow-list does not inspect. Store `base_url`
plus a query-parameter map, with any auth-bearing parameter replaced by `<redacted:auth_ref>`. This
mechanism exists from run 1, before any keyed feed is onboarded, because retrofitting it after a key
exists is how the leak happens.

**The structural check covers every committed file, not only the JSONL**, and it is a structural
assertion rather than a secret-scanner: every header key present must be a member of the allow-list,
and every auth-shaped config key or URL parameter must hold the redaction placeholder. An entropy
heuristic is a backstop for non-JSONL files, not the primary guard.

**The check runs in CI, not only pre-commit.** `--no-verify` bypasses a local hook, and this
project's own argument is that a local gate is fast feedback while only the enforced gate is
enforcement. That argument applies to us exactly as it applies to Conftest and Gatekeeper.

Payload blobs are gitignored; the observation JSONL and the run manifest are committed.

### 6.6 What "usable" means — written before the numbers exist

Defined now, deliberately, so the threshold cannot be adjusted to fit whatever the run returns.

**Usable for ingest** — this is what Gate 0's "at least three feeds" counts:

1. **Parses reliably.** Parse failure rate below 1% across the run, *and* no systematic failure
   class. A feed returning HTML error pages 0.5% of the time is a different and worse problem than
   0.5% truncated bodies, and the rate alone hides that.
2. **Update behaviour characterised.** Either a cadence delta distribution is derivable, or it is
   established *why* one is not — echoed stamping, or undersampling under a rate limit. The bar is
   knowing what we have, not getting a number. An echo feed can still be ingested.
3. **Conditional requests characterised.** We know whether validators are honoured, including the
   false-200 rate. Gate 5's bytes-saved claim depends on this being measured rather than assumed.

**Usable for the freshness SLO** — additionally:

4. **`header_timestamp_trust` is `generation`.**

**A feed can clear the first bar without the second, and that is a normal outcome, not a failure.**
Such a feed is onboarded as a tenant and excluded from `feed_freshness` per ADR 0002. **The
exclusion is recorded in `tenants/<name>.yaml` at onboarding, never inferred later** — an SLO that
silently omits a tenant is worse than one that visibly excludes it.

VBB is the live case: degraded since 2026-06-04, and Test A is unavailable on static content, so
`unknown` is a plausible verdict. It can still be usable for ingest, and would then be a tenant with
no freshness SLO.

### 6.7 Deliverables

1. `docs/metrics.md` — per-feed results table covering everything in 6.3, plus the header-timestamp
   verdict and an explicit ± clock uncertainty on every lag figure.
2. An ADR on probe methodology and the header-timestamp verdict method — it determines whether an
   SLI is valid, which makes it a real decision.
3. A tenant-schema implications note confirming or amending the section 4 field list.

**Gate 0:** at least three feeds confirmed usable, with measured cadence, ETag behaviour and a
header-timestamp verdict recorded for each. Run 1's three keyless feeds can satisfy this alone.

---

## 7. Stage 1 — platform floor

Each gate is a falsifiable test. Complete, verify, report, then continue.

**Gate 1 — Repo layout and remote state.**
Directory structure created. `infra/terraform/bootstrap/` provisions the S3 state bucket with
local state; `infra/terraform/platform/` uses it as a backend.
*Verify:* `terraform init` from a fresh clone with no local state succeeds.

**Gate 2 — Terraform: cloud floor.**
OCI VCN, subnet, internet gateway, route table, network security group, compute instance
(A1.Flex, Frankfurt), block volume. No Kubernetes resources.
*Verify:* `destroy` then `apply` produces a working SSH-able node. Twice. With no manual step.

**Gate 3 — Ansible: node bootstrap.**
Hardening, sysctl, unattended-upgrades, pinned k3s version, node labels (including a residency
label), kubeconfig fetch.
*Verify:* second consecutive run reports **zero changed tasks**. That idempotence proof is the
artefact, not the playbook.

**Gate 4 — ArgoCD, self-managed.**
Bootstrap ArgoCD, then app-of-apps so ArgoCD's own configuration comes from git. Document **all
three** irreducible bootstrap steps honestly — k3s install, ArgoCD install, age key delivery — as
enumerated in the architectural boundary section, not the one step this plan originally claimed.
*Verify:* change ArgoCD's own Helm values in git; confirm it reconciles itself with no kubectl.

**Gate 5 — Ingest service, one tenant, one feed.**
**The feed is gtfs.de or HSL — explicitly not VBB.** VBB has been degraded since 2026-06-04, and
building the ingest service against a broken upstream makes every parse failure ambiguous: you
cannot tell your own bug from theirs. Gate 5's feed must be the most boring and highest-cadence one
available, so that anything that breaks is provably ours. VBB is onboarded later, *because* it is
degraded — it is excellent alerting material once alerting exists.

Python service: poller with ETag / If-Modified-Since, protobuf decode, dedup, persist to
Postgres, bounded queue. **Record an explicit decision on backpressure behaviour** when the
queue fills — drop oldest, drop newest, or block and let lag grow. Each is defensible; silence
is not.

**Memory sizing method, stated now rather than improvised later:** single-message decode peak ×
queue depth × safety factor, taken from the Stage 0 probe, then corrected at Gate 7 from observed
`container_memory_working_set_bytes`. Run the decode benchmark **inside a Linux container** so that
architecture is the only remaining confound between the measurement and the pod.
*Verify:* run locally against the live feed for one hour. Record parse failure rate, duplicate
rate, and bytes saved by conditional requests.

**Gate 6 — Helm chart, deployed by ArgoCD.**
Multi-arch image built in CI, pushed to GHCR, digest written into values by CI.
*Verify:* bump the digest in git; confirm the new pod runs, with no kubectl.

**Gate 7 — Observability.**
Decide explicitly rather than drifting: OpenTelemetry SDK for traces, Prometheus client for
metrics scraped directly, is simpler and more honest than routing metrics through a collector we
do not yet need. If a collector is used, be able to state what it buys us.
**Cardinality rule: never label metrics with `trip_id`, `stop_id` or `vehicle_id`.** Label by
tenant, entity type, and outcome. Prometheus on 12 GB dies quickly otherwise.

That rule is the obvious half. **Also decide explicitly, at this gate:** histogram bucket counts
(latency histograms multiply by tenants × entity types × outcomes, and that is what actually kills
a small Prometheus — not the banned high-cardinality IDs, which are simply never added), scrape
interval, and retention. All three are storage decisions with no default that is right by accident.
*Verify:* metric appears in Prometheus with the expected label set; run a cardinality check and
record series count per tenant, chosen retention and scrape interval in `docs/metrics.md`.

**Gate 8 — SLIs, SLOs, burn-rate alerting.**
Four SLIs with distinct fault domains. The lag SLI is deliberately **split in two and honestly
named**, because a single end-to-end lag SLI is partly self-referential: our poll interval sets both
its floor and its ceiling, so tightening the interval "improves" the SLO. Full reasoning in
`docs/decisions/0002-sli-split.md`.

1. **Ingest pipeline success rate** — our fault domain. **Carries the error budget.**
2. **`pipeline_latency`** — fetch-completion → row committed. Our fault domain. **Carries the error
   budget.** Not gameable by poll interval, and free of clock skew entirely, since both endpoints
   are our own clock.
3. **`feed_freshness`** — `FeedHeader.timestamp` → row committed. Shared fault domain. **The poll
   interval is a stated parameter of the SLO definition, written down, not a hidden knob**; changing
   it means restating the SLO. Applies **only** to tenants whose `header_timestamp_trust` is
   `generation`.
4. **Upstream availability** — their fault domain. Measured and dashboarded, **never budgeted**.

Caveat to state openly, and now confined to SLI 3 alone: `feed_freshness` compares a
producer-declared timestamp against our clock, so it carries clock skew and any upstream
misreporting of generation time. The Stage 0 probe tells us which feeds misreport, and the node's
own NTP offset is exported as a metric so the caveat has a number behind it rather than being a
disclaimer.

**Exclusion is a mechanical predicate, not a human declaration.** Exclude windows where upstream
availability is zero for the *entire* window, as a recording rule. No hand-declared outages — an
exclusion someone can invoke by hand makes the SLO unfalsifiable, which is worse than a lower
number. Known and accepted limitation: the predicate cannot distinguish "upstream down" from "our
own egress broken", and it does not exclude partial upstream degradation. Both are acceptable
because SLIs 1 and 2 carry the budget and catch our own faults regardless.

Set SLO targets *provisionally* and recalibrate after two weeks of real data. Do not invent
targets before a baseline exists.

Implement **multiwindow, multi-burn-rate alerts** (SRE workbook pattern: fast burn 1h/5m, slow
burn 6h/30m), not static thresholds. Route to ntfy.sh or Telegram.
*Verify:* **two different failure injections** — kill the pod, and separately **point the tenant at
a blackhole endpoint via its own `tenants/<name>.yaml`**. Confirm the correct alert fires within
the predicted window and resolves. They should page differently.

The blackhole injection replaces an egress NetworkPolicy, which would inject the wrong fault: a
naive egress deny also blocks DNS, so the alert fires for "DNS broken" rather than "feed
unreachable", and `ipBlock` takes CIDRs while these feeds are CDN-fronted with moving IPs. The
blackhole route has the same fault domain and the additional benefit of proving that the tenant file
really is the source of truth. NetworkPolicy enforcement is still tested — as a pod-to-pod check in
Stage 2, where it belongs, since that is the claim it actually underpins.

**Gate 9 — Rebuild drill.**
Destroy everything. Rebuild from git. Time it. Write down every manual step that could not be
avoided and why.
*Verify:* system green again; manual-step list short and explained.

**Stage 1 is done** when the environment can be destroyed, rebuilt from git, and a real feed is
flowing with alerting proven by injection. Not before.

---

## 8. Metrics to track (`docs/metrics.md`)

Measured, not asserted. These are the evidence base for interview claims.

- Number of **manual infrastructure steps** to onboard a tenant (target: zero). **Credential
  acquisition is excluded and counted separately** — registering with opentransportdata.swiss,
  obtaining a key and SOPS-encrypting it into the repo is a human step by any honest accounting,
  and a "zero manual steps" claim that quietly swallows it is the kind of gap an interviewer probes.
- Number of **credential-acquisition steps** per tenant (0 for keyless feeds, non-zero for CH/FI)
- Wall-clock from **PR merge to first datapoint queryable and dashboard live**
- Lines of config a contributor writes per tenant
- Percentage of merges reaching the cluster with **zero human action**
- **Rebuild drill time** — destroy to green
- Policy rules enforced, split by gate (CI vs admission)
- Tenants running
- SLO attainment and error budget consumption
- MTTR on real incidents (upstream outages count; VBB is currently degraded and will generate them)
- Prometheus series count per tenant

Note: "onboarding effort before vs after" is deliberately **not** the headline metric, because
the "before" number is self-selected and an interviewer knows it. The rebuild drill and the
manual-step count are harder to game.

---

## 9. Honest limits (`docs/limits.md` — write this early, keep it accurate)

State these before anyone asks:

- **Single node.** No HA, no meaningful PodDisruptionBudget semantics, no etcd operations, no
  control-plane upgrade story, no node drain under load.
- **Tenants are logical, not geographic.** Physical data residency cannot be enforced on one VM
  in one Frankfurt datacentre. What is real is the *enforcement mechanism*: policy rejects a
  tenant whose storage class, nodeSelector or egress allow-list contradicts its declared
  residency and licence. The topology is simulated; the mechanism is not.
- **No untrusted tenants and no real users.** This builds isolation mechanisms; it does not
  defend against an adversary, and it has never run under production load.
- **A CI policy check is not enforcement.** Anyone with kubectl bypasses it. CI is fast feedback;
  the admission controller is enforcement. Both are built here, and the difference is understood.
- **Postgres isolation is logical.** One instance, schema per tenant, per-tenant DB roles. This
  is weaker than the namespace and NetworkPolicy isolation. Accepted deliberately for resource
  reasons.
- **The age private key is an irreducible bootstrap secret.** It cannot live in git. Every
  secrets system has this chicken-and-egg at its root; Vault moves it to unseal keys, cloud KMS
  moves it to provider IAM. Ours is documented, not eliminated.
- **Bootstrap is three manual-equivalent steps, not zero and not one.** k3s install, ArgoCD
  install, age key delivery — all via Ansible, all before GitOps can take over. "No human touches
  the cluster" is true of *operations*, not of *bootstrap*, and the distinction is stated rather
  than blurred.
- **No public transit data is personal data.** Do not frame any of this as GDPR compliance.
- **Feed size is a real admission constraint, and we found it by measuring.** gtfs.de is
  characterised and **excluded as a tenant on resource grounds**: ~40 MB uncompressed per fetch (the
  only probed feed that does not gzip) against a measured ~29s cadence — not the documented 10s —
  which is 5–9.6 GB/hour of continuous traffic from a volunteer service, and 163,819 entities per
  snapshot roughly twice a minute into one Postgres shared by every tenant on a 12 GB node. Slowing
  to 5-minute polling still costs ~350 GB/month *and* makes freshness meaningless against a
  sub-minute upstream. Its licence is clean (CC BY-SA 4.0); the exclusion is purely about resources.
  Arithmetic in `docs/metrics.md`. This is a limit discovered, not assumed — the sort of thing this
  system is small enough to hit and honest enough to record.
- **Not every feed can carry an end-to-end freshness SLI.** ADR 0002's fallback for a producer that
  echoes serve time is `max(entity timestamp)` — but gtfs.de and OVapi publish **no entity
  timestamps at all** (coverage 0.0). A feed that both echoes *and* omits them has no freshness
  reference of any kind and must be excluded from `feed_freshness` outright. Settle that before
  Gate 8 rather than discovering it there.
- Not covered at all: vendor-proprietary operational tooling, genuine multi-region geographic
  distribution, operating under production load with real users.

---

## 10. Known gotchas to plan for, not discover

- **ArgoCD does not decrypt SOPS natively.** Needs ksops, helm-secrets, or a config management
  plugin. Decide this in Stage 1, not Stage 3, because it changes the chart structure.
- **Multi-arch builds are mandatory** on ARM. Set up `docker buildx` early.
- **CI writes the image digest into values**, rather than running Argo Image Updater. Keeps the
  change auditable in git and avoids another controller.
- **Rego is genuinely hard.** Budget roughly a week of struggle with the evaluation model,
  particularly comprehensions and partial rules. It does not think like any language already
  known.
- **Gatekeeper is heavier than Kyverno.** On 12 GB this is fine, but track it.
- **ApplicationSet blast radius.** A malformed tenant file that Conftest does not catch breaks one
  tenant. A tenant file that breaks the ApplicationSet *template* breaks every tenant at once. This
  shapes what Conftest must validate — schema conformance of every tenant file, not just the
  changed one — and it is a fair interview question about the onboarding design.
- **No public ingress.** Grafana and ArgoCD go behind Tailscale or a Cloudflare Tunnel. This
  removes a load balancer, cert-manager, and the entire public attack surface. Be able to explain
  how ingress + TLS would be done where it is required.

---

## 11. Stages 2–4 (not started; do not scaffold ahead)

**Stage 2 — multi-tenancy and onboarding.** Reusable Terraform module for per-tenant cloud-side
resources; ApplicationSet rendering the per-tenant in-cluster environment (namespace,
NetworkPolicy, ResourceQuota, scoped RBAC, storage). Onboard several tenants through it. Measure
onboarding using the metrics in section 8.

Two things this stage must carry:

- **A NetworkPolicy enforcement test, pod-to-pod.** Prove that a pod in tenant A cannot reach a pod
  in tenant B. NetworkPolicy underpins the isolation claim, so the claim needs an observed result
  behind it, not a manifest that looks right. Verify first that the pinned k3s version enforces
  NetworkPolicy at all rather than assuming its bundled networking does.
- **An honest answer to what per-tenant cloud-side resources actually are.** On one VM with one
  Postgres, the plausible list is short, and OCI's Always Free object storage cap (20 GB combined,
  50,000 API requests/month) constrains it further. If the module turns out thin, it is thin and we
  say so — the CLAUDE.md exemption granted to it is about reusability, not about manufacturing
  resources to justify the boundary. "Show me the tenant module" is a question that will be asked.

**Stage 3 — compliance gate.** Conftest/Rego rejecting a non-compliant Terraform plan in CI;
Gatekeeper enforcing the same rules at admission. Append-only audit log of every provisioning
action. Secrets fully through SOPS+age.

**One rule has a real subject waiting for it:** reject any tenant whose `licence` is `unresolved`.
OVapi is that tenant (section 4). This is worth more than a rule every tenant passes by
construction — the gate demonstrably blocks something, and the thing it blocks is a genuine
compliance gap we found by reading the licence rather than assuming it.

**Stage 4 — deferred.** Incident triage agent: on a firing alert, reads metrics, recent deploys
and tenant state, drafts a hypothesis and a remediation PR. Must never apply a change itself; the
policy gate and human review stay in the path. **Do not begin until Stage 3 is solid.**

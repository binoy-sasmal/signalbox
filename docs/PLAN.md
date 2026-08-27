# Signalbox — Project Plan

> **Signalbox** — a multi-tenant control plane for public realtime transit feeds, where
> onboarding a new data source is one merged pull request.

**Status:** planning complete, Stage 0 not started
**Owner:** Binoy
**Last updated:** 2026-08-27

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
that we did not do that, and here is the boundary.

### Cloud caveats to engineer around (OCI Always Free)

- Allowance was **halved in June 2026** to 2 OCPUs / 12 GB (1,500 OCPU-hours, 9,000 GB-hours per
  month) with no announcement. 12 GB is still sufficient for this build.
- A1 capacity is regional. Frankfurt usually provisions quickly; US regions often do not.
- Oracle may reclaim instances idle below 10% CPU **and** 10% network over 7 days. Verify our
  workload stays clear rather than assuming it does.
- ARM only. All images must be arm64 or multi-arch (`docker buildx`, manifest lists).
- No SLA and no change notification. If Oracle changes something under us, write the postmortem;
  it is real incident material.

### AWS account caveat

Accounts created after 15 July 2025 must select the **Paid plan** at signup. The Free plan
closes the account after six months or when credits run out, which would take our Terraform
state with it. Paid plan still receives the same credits. Set an AWS Budgets alarm at $1 on
day one. Do not join an AWS Organization; that expires the credits immediately.

---

## 4. Tenant set (to be confirmed by the Stage 0 probe)

| Tenant | Jurisdiction | Auth | Known characteristics |
|---|---|---|---|
| VBB (Berlin/Brandenburg) | DE | none | `https://production.gtfsrt.vbb.de/data` — 60 req/min, ETag supported, CC-BY 4.0. **Known degraded since 2026-06-04**, upstream data source problem, no restoration estimate. |
| gtfs.de national | DE | none | `https://realtime.gtfs.de/realtime-free.pb` — 10-second updates, CC BY-SA 4.0, TripUpdates + ServiceAlerts. Aggregate feed, not a single operator. |
| opentransportdata.swiss | CH | **API key** | 2 queries/minute, sliding window. The most valuable tenant despite being the most awkward: forces real per-tenant secret handling and a real rate limiter. |
| OVapi | NL | none | Verify licence, cadence and endpoint during probe. |
| HSL Helsinki | FI | none | Well-documented, reliable; good baseline for comparison. |

Consequence for the tenant schema: `rate_limit` and `auth_ref` must be **first-class fields from
day one**, not retrofitted.

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

Build a probe script (`scripts/probe/`) that polls each candidate for one hour and records:

- HTTP status distribution; whether auth is required and in what form
- ETag / Last-Modified support, and whether a conditional request actually returns 304
- Observed update cadence — count of distinct `FeedHeader.timestamp` values over the hour
- **Header timestamp sanity** — skew against local clock, and whether the timestamp genuinely
  reflects generation time or just echoes fetch time. This determines whether the end-to-end lag
  SLI is meaningful for that tenant.
- Payload size raw and decoded; entity counts by type (TripUpdate / VehiclePosition / Alert)
- Parse failure rate and the nature of failures
- Rate-limit behaviour on approach to the documented limit (approach carefully; do not get banned)
- Licence and required attribution string
- Any downtime observed during the window

Output a committed results table in `docs/metrics.md`.

**Gate 0:** at least three feeds confirmed usable, with measured cadence, ETag behaviour and
header-timestamp sanity recorded for each.

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
Bootstrap ArgoCD, then app-of-apps so ArgoCD's own configuration comes from git. Document the
irreducible manual bootstrap step honestly.
*Verify:* change ArgoCD's own Helm values in git; confirm it reconciles itself with no kubectl.

**Gate 5 — Ingest service, one tenant, one feed.**
Python service: poller with ETag / If-Modified-Since, protobuf decode, dedup, persist to
Postgres, bounded queue. **Record an explicit decision on backpressure behaviour** when the
queue fills — drop oldest, drop newest, or block and let lag grow. Each is defensible; silence
is not.
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
*Verify:* metric appears in Prometheus with the expected label set; run a cardinality check and
record series count per tenant in `docs/metrics.md`.

**Gate 8 — SLIs, SLOs, burn-rate alerting.**
Three SLIs with distinct fault domains:

1. **Ingest pipeline success rate** — our fault domain. **This one carries the error budget.**
2. **End-to-end lag** (`FeedHeader.timestamp` → row committed) — shared fault domain. Budgeted
   with an upstream-outage exclusion.
3. **Upstream availability** — their fault domain. Measured and dashboarded, **never budgeted**.

Caveat to state openly: we compare a producer-declared timestamp against our clock, so lag
includes clock skew and any upstream misreporting generation time. The Stage 0 probe tells us
which feeds misreport.

Set SLO targets *provisionally* and recalibrate after two weeks of real data. Do not invent
targets before a baseline exists.

Implement **multiwindow, multi-burn-rate alerts** (SRE workbook pattern: fast burn 1h/5m, slow
burn 6h/30m), not static thresholds. Route to ntfy.sh or Telegram.
*Verify:* **two different failure injections** — kill the pod, and separately block feed egress
with a NetworkPolicy. Confirm the correct alert fires within the predicted window and resolves.
They should page differently.

**Gate 9 — Rebuild drill.**
Destroy everything. Rebuild from git. Time it. Write down every manual step that could not be
avoided and why.
*Verify:* system green again; manual-step list short and explained.

**Stage 1 is done** when the environment can be destroyed, rebuilt from git, and a real feed is
flowing with alerting proven by injection. Not before.

---

## 8. Metrics to track (`docs/metrics.md`)

Measured, not asserted. These are the evidence base for interview claims.

- Number of **manual steps** to onboard a tenant (target: zero)
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
- **No public transit data is personal data.** Do not frame any of this as GDPR compliance.
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
- **No public ingress.** Grafana and ArgoCD go behind Tailscale or a Cloudflare Tunnel. This
  removes a load balancer, cert-manager, and the entire public attack surface. Be able to explain
  how ingress + TLS would be done where it is required.

---

## 11. Stages 2–4 (not started; do not scaffold ahead)

**Stage 2 — multi-tenancy and onboarding.** Reusable Terraform module for per-tenant cloud-side
resources; ApplicationSet rendering the per-tenant in-cluster environment (namespace,
NetworkPolicy, ResourceQuota, scoped RBAC, storage). Onboard several tenants through it. Measure
onboarding using the metrics in section 8.

**Stage 3 — compliance gate.** Conftest/Rego rejecting a non-compliant Terraform plan in CI;
Gatekeeper enforcing the same rules at admission. Append-only audit log of every provisioning
action. Secrets fully through SOPS+age.

**Stage 4 — deferred.** Incident triage agent: on a firing alert, reads metrics, recent deploys
and tenant state, drafts a hypothesis and a remediation PR. Must never apply a change itself; the
policy gate and human review stay in the path. **Do not begin until Stage 3 is solid.**

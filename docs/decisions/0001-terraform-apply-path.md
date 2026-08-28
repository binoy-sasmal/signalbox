# 0001 — What applies Terraform when a tenant PR merges

**Status:** Accepted
**Date:** 2026-08-28
**Related:** ADR 0002 (the provisioning-window exclusion this decision creates)

## Context

The headline claim is that onboarding a tenant is one merged pull request, with no human touching
a cluster. ArgoCD delivers the in-cluster half of that automatically: an ApplicationSet with a git
file generator sees the new `tenants/<name>.yaml` and renders a Helm release.

**The Terraform half had no defined trigger.** Nothing in the plan said what runs `terraform apply`
for the per-tenant cloud-side resources. Until that is answered the headline claim is either false
or undefined, and "what actually happens when the PR merges?" is the first question an interviewer
asks about the onboarding story.

There is a second, quieter problem underneath it. `tenants/<name>.yaml` has two consumers with **no
ordering relationship**. ArgoCD acts on the file the moment it lands in git; Terraform acts whenever
something invokes it. If the tenant's workload starts before its cloud-side resources exist, it
crashloops. That ordering was a race, not a design.

A third input constrains the whole question: OCI's Always Free object storage allowance is 20 GB
combined across tiers and 50,000 API requests per month (PLAN.md section 3, verified 2026-08-28).
Whatever per-tenant cloud-side resources we define have to fit inside that.

## Options

### 1. A human runs `terraform apply` after merge

Simple, safe, fully auditable, and no credentials leave the operator's machine. But the headline
claim becomes false, section 8's manual-step metric admits a non-zero number, and — more
importantly — the system is weaker, because a privileged human is now in the critical path.

### 2. CI applies on merge to main

Makes the claim true. CI holds OCI credentials and takes the S3 state lock.

Costs: CI becomes a privileged actor with cloud write access; concurrent merges contend on the state
lock; a failed apply leaves a tenant half-onboarded, in-cluster half live and cloud-side half
missing.

The plan **already requires** Conftest to validate a Terraform *plan* in CI — it is the stated reason
OPA/Rego was chosen over Kyverno (decision 5). The policy gate that guards this auto-apply is not new
work invented to justify the option; it exists by design and is currently gating nothing.

### 3. An in-cluster Terraform controller (Crossplane, tf-controller)

Rejected. It moves cloud provisioning inside the cluster, re-opens a settled decision, adds a
controller to a 12 GB node, and muddies the very boundary this project exists to demonstrate.

## Decision

**Option 2**, with the following conditions.

### Pipeline shape

- Conftest gates the plan **before** any apply. Plan output is posted to the PR **on the PR run**, so
  the reviewer sees what will change before merging rather than after.
- **Apply runs only on `main`**, after merge.
- **Concurrency group of 1** on the apply workflow, so applies serialise rather than fighting over
  the S3 state lock.
- **No environment approval gate.** An approval step would reintroduce exactly the manual action the
  onboarding metric claims to have removed, and would make the headline claim false by a different
  route. Review happens at the PR, which is where the plan output is.
- A failed apply pages. A half-onboarded tenant is an incident, not a silent state.

### Credentials

**Prefer short-lived credentials via OIDC federation from GitHub Actions to OCI.** Whether OCI
supports this must be **verified, not assumed** — it is exactly the class of upstream claim rule 6
forbids inventing.

If OCI does not support it, fall back to a scoped API key with least-privilege IAM, restricted to the
resource types the tenant module creates. **That fallback is a weaker position and is recorded as
such:** a long-lived credential in CI is standing cloud write access, mitigated only by IAM scoping
and rotation, where OIDC would bound it to the life of a single workflow run. If we end up on the
fallback, it belongs in `docs/limits.md` next to "a CI policy check is not enforcement".

### Ordering

**The ingest service treats a missing cloud-side dependency as a retryable not-ready condition**,
with a readiness probe that stays not-ready until the dependency resolves. Not a crashloop, and not a
sync-wave dependency between two systems that share no scheduler. This is what you would do in
production regardless, and it makes the ordering safe without coupling ArgoCD to Terraform's
completion.

## Consequences

- CI becomes a privileged cloud actor. That is a real security consequence and belongs in
  `docs/limits.md` alongside the existing CI-is-not-enforcement statement.
- **The not-ready window this creates must not burn the ingest error budget.** A tenant that is
  correctly waiting for its cloud-side resources is not a pipeline failure. This requires an explicit
  provisioning-window exclusion in the SLI definitions — specified in **ADR 0002**, which this
  decision is the cause of.
- The PR-merge-to-first-datapoint metric naturally includes Terraform apply time, which makes it a
  more honest number than it would otherwise have been.
- **Open sub-question, deliberately not answered here:** what per-tenant cloud-side resources
  actually exist? On one VM with one Postgres the plausible answer is short — perhaps an object
  storage bucket and an IAM policy, inside a 20 GB cap. If the Stage 2 module turns out thin, it is
  thin and we say so. The CLAUDE.md exemption granted to that module is about reusability, not a
  licence to manufacture resources so the boundary looks better defended.

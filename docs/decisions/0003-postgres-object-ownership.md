# 0003 — Postgres schemas and roles are owned by ArgoCD via an operator

**Status:** Accepted, with a verification item outstanding
**Date:** 2026-08-28

## Context

The architectural boundary assigns every object an owner by where it lives: cloud API objects to
Terraform, Kubernetes API objects to ArgoCD. Postgres schemas and per-tenant roles live in neither.
They are inside Postgres, which runs in-cluster.

So the boundary — the thing this project is built to demonstrate — has a hole in it exactly where
Stage 2 needs to create per-tenant database objects. Left unresolved, this becomes the question
that unpicks the whole boundary story in an interview.

## Options

### 1. A Job or init container running SQL

Simplest, and the common answer. No new controller.

But it is a **third reconciler with no reconciliation**: it runs once, has no drift detection, no
self-heal, and no notion of desired state. If someone drops a role, nothing notices. It also
inverts the property that makes the rest of the design defensible — every other object in this
system converges continuously, and this one would not. Ordering against the Postgres pod's
readiness is fragile on top of that.

### 2. Terraform's `postgresql` provider

Rejected. It puts Terraform inside the cluster's data plane, which is the boundary violation this
project exists to avoid, and it needs network reachability from wherever Terraform runs to an
in-cluster database that is deliberately not exposed. It would also re-create the two-reconciler
problem inside Postgres.

### 3. A Postgres operator with declarative CRDs

Postgres objects become Kubernetes API objects. ArgoCD then owns them **under the existing rule,
with no new exception** — the boundary stays exactly as stated, and the hole closes rather than
being papered over.

Drift detection and self-heal come free, because they are properties of the CRD + controller
pattern rather than something we build.

Cost: another controller on a 12 GB node.

## Decision

**Option 3.** Evaluate **CloudNativePG first.**

The reasoning that makes this more than a tooling preference: it is the only option that closes the
gap without amending the boundary. Options 1 and 2 both require saying "the boundary holds, except
for database objects" — and an exception in the central architectural claim is expensive.

## Consequences

- **Verification item, to be settled during evaluation and not assumed:** whether CloudNativePG at
  the version we pin actually exposes declarative CRDs at the granularity we need — databases,
  roles, and schema-level objects. If schema-per-tenant is not expressible declaratively, that part
  may still need a Job, which partially reopens this decision. **Do not write this ADR's premise
  into the tenant module before confirming the CRD surface against the pinned version's docs.**
- Resource cost on 12 GB must be tracked, alongside Gatekeeper (PLAN.md section 10). Two
  controllers we did not originally budget for.
- The operator manages a Postgres *cluster* resource. On a single node that is still one instance,
  so the honest limits statement in section 9 — "Postgres isolation is logical: one instance,
  schema per tenant, per-tenant DB roles" — remains accurate and does not need softening.
- This must be settled before Stage 2, because per-tenant database objects are part of what
  onboarding provisions.

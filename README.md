# Signalbox

A multi-tenant control plane for public realtime transit feeds, where onboarding a
new data source is one merged pull request.

Each upstream feed is an isolated tenant. Onboarding provisions an isolated ingest
pipeline, storage, quotas, dashboards and alerts with no human touching a cluster.

**Read [`docs/PLAN.md`](docs/PLAN.md) first** — it is the authoritative plan.
[`docs/status.md`](docs/status.md) says where the work actually is, and
[`docs/limits.md`](docs/limits.md) says what this is not. That last one is not
boilerplate; read it before believing anything above.

## What exists right now

Stage 0 (feed probe) is complete and Stage 1 has just started. There is no cluster,
no ingest service and no running system. See [`docs/status.md`](docs/status.md).

## Prerequisites

| Tool | Version | Why pinned |
|---|---|---|
| Terraform | `1.16.0` | Exact pin in `required_version`. `use_lockfile` needs ≥ 1.10. |
| AWS CLI | v2 | Credentials only; Terraform does not shell out to it. |

## AWS credentials

The profile is in the configuration, not the environment — see
[ADR 0007](docs/decisions/0007-terraform-state-backend.md) for why, and for what it
costs. **You do not need to set `AWS_PROFILE`.**

The profile is named `signalbox` and must exist in your local AWS config. Check it:

```sh
aws sts get-caller-identity --profile signalbox   # expect .../user/signalbox-terraform
```

An ARN ending in `:root` means the wrong credentials are in that profile. On a
machine using different profile names, override `var.aws_profile` for `bootstrap`
and edit the backend block in `infra/terraform/platform/main.tf` — a backend block
cannot take a variable.

## Terraform state

Two configurations, and the split is deliberate — see
[ADR 0007](docs/decisions/0007-terraform-state-backend.md).

```
infra/terraform/bootstrap/   # creates the S3 state bucket. Local state.
infra/terraform/platform/    # OCI cloud floor. Uses that bucket as its backend.
```

`bootstrap` runs once and creates the bucket every other configuration stores state
in. It cannot store its own state there, so its state is local and gitignored.

```sh
cd infra/terraform/bootstrap && terraform init && terraform apply
cd ../platform             && terraform init
```

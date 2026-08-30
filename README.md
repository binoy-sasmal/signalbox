# Signalbox

A multi-tenant control plane for public realtime transit feeds, where onboarding a
new data source is one merged pull request.

Each upstream feed is an isolated tenant. Onboarding provisions an isolated ingest
pipeline, storage, quotas, dashboards and alerts with no human touching a cluster.

**Read [`docs/PLAN.md`](docs/PLAN.md) first** — it is the authoritative plan.
[`docs/status.md`](docs/status.md) says where the work actually is, and
[`docs/limits.md`](docs/limits.md) says what this is not. That last one is not
boilerplate; read it before believing anything above.

## Architecture

![Signalbox architecture: a contributor's pull request enters a GitHub repo; CI
runs checks and Terraform, writing state to an S3 bucket in AWS and provisioning
a single ARM server in Oracle Cloud; ArgoCD on that server deploys Postgres,
per-tenant ingest pipelines and Prometheus with Grafana; the pipelines poll
public transit feeds, write rows to Postgres and emit metrics.](docs/images/system-overview.png)

**This is the target system, not what runs today.** Nothing inside the Oracle
Cloud box exists yet — see [`docs/status.md`](docs/status.md) for what is
actually built, and the section below.

Two boundaries carry most of the design. **Terraform owns cloud resources and
ArgoCD owns everything inside the cluster**, with `tenants/<name>.yaml` as the
single source of truth feeding both — two reconcilers over one object produce a
silent flapping loop, not an error. And **AWS holds Terraform state and nothing
else**, because the bucket has to exist before anything that stores state in it
([ADR 0007](docs/decisions/0007-terraform-state-backend.md)).

The drawing is deliberately coarse. Three precise diagrams — system context,
the tenant-onboarding path, and one tenant's data path — are in
[`docs/architecture.md`](docs/architecture.md) as Mermaid source, along with a
list of what `PLAN.md` leaves underspecified. Two simplifications worth naming
here: ArgoCD reaches Postgres through an operator rather than directly
([ADR 0003](docs/decisions/0003-postgres-object-ownership.md)), and the three
Ansible bootstrap steps that create the cluster before ArgoCD can manage itself
are not drawn at all.

## What exists right now

Stage 0 (feed probe) is complete and Stage 1 has just started. There is no cluster,
no ingest service and no running system. See [`docs/status.md`](docs/status.md).

## Prerequisites

| Tool | Version | Why pinned |
|---|---|---|
| Terraform | `1.16.0` | Exact pin in `required_version`. `use_lockfile` needs ≥ 1.10. |
| AWS CLI | v2 | Credentials only; Terraform does not shell out to it. |
| OCI account | — | Tenancy plus an API signing key in `~/.oci/config`. **Not yet created.** |

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

## OCI credentials

The same split as AWS, for a stronger reason: OCI's secret is a real private key.
Only the **profile name** lives in this repo. The key stays in `~/.oci/config`.

```sh
oci setup config     # writes ~/.oci/config and the API key. Profile: signalbox
```

`platform` needs two values that are deliberately not committed:

| Variable | Where it comes from | Why it is not in the repo |
|---|---|---|
| `compartment_ocid` | Your tenancy, or a compartment OCID | Account-specific. |
| `ssh_ingress_cidr` | Your public address, as `<addr>/32` | A home IP. Not a credential, but personal, and it changes. |

The SSH **public** key is read from `~/.ssh/signalbox_ed25519.pub` by default. Only
the public half ever leaves your machine and nothing is committed. Generate one:

```sh
ssh-keygen -t ed25519 -f ~/.ssh/signalbox_ed25519 -C signalbox
```

See [ADR 0008](docs/decisions/0008-oci-cloud-floor.md) for why each of these is
where it is.

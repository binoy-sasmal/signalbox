# 0007 — Terraform state: backend, locking, and the bootstrap chicken-and-egg

**Status:** Accepted
**Date:** 2026-08-29
**Related:** [`../PLAN.md`](../PLAN.md) section 7 Gate 1, [`../../README.md`](../../README.md)

## Context

`PLAN.md` settled the backend as AWS S3 with native S3 locking (decision 3, "no
DynamoDB lock table needed"). Gate 1 turns that into two configurations:
`infra/terraform/bootstrap/` creates the state bucket, `infra/terraform/platform/`
uses it. Three things needed deciding before any HCL was written.

## Decision 1 — native S3 locking, and the version floor it implies

`use_lockfile = true` on the S3 backend. It uses S3 conditional writes, so no
DynamoDB table exists to create, pay for, or forget to destroy.

**Verified rather than assumed.** `use_lockfile` was introduced in **Terraform
1.10**, and DynamoDB-based locking is documented as deprecated and slated for
removal in a future minor version. Checked against HashiCorp's S3 backend
documentation and release history on 2026-08-29. It requires `s3:GetObject`,
`s3:PutObject` and `s3:DeleteObject` on the `.tflock` object, not only on the state
object — an IAM detail that is easy to miss because the lock is a second object
under a different suffix.

Versions pinned exactly, per CLAUDE.md: Terraform `1.16.0`, AWS provider `6.62.0`.
`.terraform.lock.hcl` is committed; it is the provider pin with hashes.

## Decision 2 — credentials come from the environment, not from the repo

No `profile` argument appears in any backend or provider block. Terraform reads the
standard AWS credential chain, and `AWS_PROFILE` is documented in the README.

**Options considered.** Hardcoding `profile = "signalbox"` would make
`terraform init` work from a fresh clone with no setup, which reads better against
Gate 1's literal wording. It was rejected because the profile name exists only on
one machine: Stage 3 runs `terraform plan` under Conftest in CI, where credentials
arrive by OIDC and a named profile does not exist. Creating a local `[default]`
profile was rejected for the opposite reason — it makes the repo work by virtue of
machine state that nothing in the repo records.

**Consequence, stated rather than hidden:** Gate 1's "fresh clone" verification
requires `AWS_PROFILE` to be set first. That is one environment variable, it is in
the README, and it is named in the gate evidence rather than glossed over.

## Decision 3 — bootstrap keeps local state, gitignored

`bootstrap/` creates the bucket that every other configuration stores state in, so
it cannot store its own state there.

**Options considered.**

1. **Local state, gitignored.** Chosen.
2. **Migrate bootstrap's state into the bucket it just created.** Self-referential
   but functional. Rejected: it makes the bucket undestroyable without first
   rescuing the state that describes it, which is a worse failure at Gate 9's
   rebuild drill than the one it solves.
3. **Commit the state file.** Rejected. It puts Terraform state in git, and
   `.tfstate` is not a scannable suffix, so the credential gate would not read it.
   The coverage test added in `2b01a5b` would turn a tracked `.tfstate` into a red
   build — correctly, because it forces this decision rather than letting state
   drift into the repo unexamined.

**Consequence.** If bootstrap's local state is lost, the bucket still exists and
Terraform no longer knows it. Recovery is `terraform import`, not `apply`. This is
the honest cost of option 1 and it is the reason bootstrap creates exactly one
resource group and is expected to run once.

**No `prevent_destroy` on the bucket.** Gate 9 destroys and rebuilds from git, and
a lifecycle guard would have to be removed by hand at precisely the moment the
drill is meant to prove no manual step is needed. Whether the state bucket is
inside or outside "everything" is a Gate 9 decision and is deliberately not
pre-empted here.

## Consequences

- Two `terraform init` surfaces, not one, and they differ: bootstrap has no
  backend block at all.
- The bucket name `signalbox-tfstate-215573083789` is hardcoded in two places —
  the resource and the backend block. Backend blocks cannot interpolate variables
  or outputs, so this duplication is a Terraform constraint, not a design choice.
  It is the reason a bucket-name variable would buy nothing.
- Versioning is enabled on the bucket. A truncated or corrupted state push is
  recoverable from a prior object version; without it the recovery path is a
  rebuild.

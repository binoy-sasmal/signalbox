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
documentation and release history on 2026-08-29.

**IAM note, for when the policy is narrowed.** `use_lockfile` requires
`s3:GetObject`, `s3:PutObject` and `s3:DeleteObject` on the **`.tflock` object**,
not only on the state object. The lock is a second object under a different
suffix, so a policy written against `.../platform/terraform.tfstate` alone does not
cover it. `AmazonS3FullAccess` covers it today, which is exactly why this is worth
writing down: **narrowing the policy to the state bucket without including the
`.tflock` permissions would break locking silently.** Terraform would keep
applying, concurrent applies would stop being serialised, and nothing would report
an error until two runs corrupted each other's state.

Versions pinned exactly, per CLAUDE.md: Terraform `1.16.0`, AWS provider `6.62.0`.
`.terraform.lock.hcl` is committed; it is the provider pin with hashes.

## Decision 2 — the profile lives in the config, not in the environment

`profile` is set in the configuration: a variable with default `"signalbox"` in
`bootstrap`'s provider block, and a literal in `platform`'s backend block.

**Reversed on 2026-08-29, deliberately.** The first version of this ADR chose the
`AWS_PROFILE` environment variable, on the grounds that it keeps the repo
machine-neutral and works under OIDC in CI. That was overruled for a better
reason: **`AWS_PROFILE` had already failed to persist once on this machine**, and a
repo whose headline claim is reproducibility should not depend on a variable that
has demonstrably not survived a reboot. A value the repo asserts is checkable; a
value the environment is supposed to carry is not.

**The tradeoff this accepts, stated plainly.** It couples the configuration to one
machine's local profile naming. A fresh clone on a machine with differently named
profiles fails until `var.aws_profile` is overridden. That is a real cost and it is
accepted because the failure is *loud and immediate* — Terraform says the profile
does not exist — whereas a missing environment variable fails as `NoCredentials`,
which is the same error a broken key gives.

**The CI answer is not this.** Stage 3 runs `terraform plan` under Conftest, where a
named profile does not exist and credentials arrive by OIDC. That path is
**unverified** — [ADR 0001](0001-terraform-apply-path.md) already flags OIDC as
verify-don't-assume — and it is not settled here. When it is, `var.aws_profile`
gains an empty default or a CI-specific override, and `platform`'s backend needs a
partial configuration, because of the constraint below.

**A backend block cannot take a variable.** From Terraform's backend documentation:
*"A backend block cannot refer to named values (like input variables, locals, or
data source attributes)."* So `bootstrap` gets `var.aws_profile` and `platform`
gets the literal `"signalbox"`. The asymmetry is forced by Terraform, not chosen,
and it is the same constraint that duplicates the bucket name. An account
migration is therefore two edits — the variable default and the backend literal —
both inside `infra/terraform/`, not a repo-wide find-and-replace.

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

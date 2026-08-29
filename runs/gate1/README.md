# Gate 1 evidence — repo layout and remote state

Gate 1 was declared passed in `6160bf1` on the strength of console output pasted into
`docs/status.md`. Review 6's F3 found that this was the only record: `git grep` for the
quoted line returned exactly one file, `git ls-files runs/` had artefacts for Stage 0's
four probe runs and nothing for Gate 1, and nothing in CI reproduced any of it. The sole
evidence for a gate sat in the one file this repo has deliberately designated
builder-written narrative that a reviewer must not treat as evidence.

This directory is the artefact, captured 2026-08-29 at commit `696959f`. It is a
**re-observation, not a transcription** — every file here is program output redirected to
disk in the session that wrote this README, not text retyped from a terminal.

## What is here

| File | What it shows |
|---|---|
| `terraform-init-fresh-clone.txt` | Gate 1's stated criterion, re-run end to end |
| `aws-s3api-bucket-state.txt` | The bucket, read independently of Terraform |
| `terraform-fmt-validate.txt` | `fmt -check` and `validate` for both configurations |

Terraform 1.16.0, downloaded fresh and checksum-verified against HashiCorp's published
`SHA256SUMS` before use (`2a50a95205189c1c9fcefbd34eaa9e94ec905a32a4880bfea34ef9f97757c73f`).
AWS CLI 2.36.33.

## What was re-observed, and what could not be

**Re-observed in full: the criterion itself.** `docs/PLAN.md` section 7 states it as
*"`terraform init` from a fresh clone with no local state succeeds."* A clone was made into
a scratch directory, checked to contain no `.terraform/` and no `.tfstate`, and `init` was
run there. It configured the S3 backend, downloaded the OCI provider from scratch — note
`Installing oracle/oci v8.29.0`, not `Using previously-installed`, which is what makes it a
genuine fresh clone rather than a warm cache — and exited 0.

**Not reproducible: Gate 1's `terraform plan` output.** `docs/status.md` also records that
`plan` returned `No changes.`. That cannot be re-run, because Gate 2 added resources to the
same configuration in `648f6c3`; `plan` now fails at the OCI provider, which has no
credentials. It was never part of the gate's criterion. The `No changes.` line stays
builder-narrative and should be read as such.

## One thing the capture found that the narrative did not say

**The state bucket is empty.** `list-objects-v2` returns `null` — there is no
`platform/terraform.tfstate` object, because the platform configuration has never been
applied. That is expected, and it narrows a claim: `status.md` said `plan` *"round-tripped
the backend"*, which sounds like an object was written and read back. It was not. What was
demonstrated is that Terraform can reach the bucket and finds no state there, which proves
read access and the backend wiring, and proves nothing about write access or about
`use_lockfile`.

`status.md` already recorded that concurrent lock behaviour has not been observed. This is
the adjacent gap and it now sits beside the evidence rather than in narrative alone:
**nothing in this repo has yet written an object to that bucket.** The first `apply` will
be the first write, and that is Gate 2.

## Reproducing this

Everything except the AWS CLI calls now runs in CI on every push — see
`.github/workflows/terraform-check.yml`, added in the same commit as this directory, which
closes the other half of F3. CI runs `fmt -check`, `init -backend=false` and `validate`.

**CI deliberately does not run the backend half.** That requires AWS credentials, and
putting them in this repository's Actions is a decision nobody has made. So the
fresh-clone backend `init` — the criterion itself — remains a local, credentialed
observation, and this directory is its record. That limitation is the reason the artefact
exists rather than a reason to skip it.

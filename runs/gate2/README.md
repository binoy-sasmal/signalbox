# Gate 2 evidence — what has been observed while the gate is blocked

**Gate 2 has not passed and nothing here claims it has.** Its criterion is *"destroy then
apply produces a working SSH-able node. Twice. With no manual step"*, and that cannot run
until an OCI tenancy exists. What this directory holds is the two adversarial observations
the configuration work did produce, as program output rather than as prose.

Both were narrative until now. Review 7's F2 found them stated in
[`docs/status.md`](../../docs/status.md) and
[ADR 0008](../../docs/decisions/0008-oci-cloud-floor.md) with nothing under `runs/` behind
them — in the same range whose whole theme was that narrative is not evidence, one commit
after the identical finding was fixed for Gate 1.

| File | What it shows |
|---|---|
| `terraform-plan-blocked.txt` | `plan` failing at the missing `~/.oci/config`, and the `node_image_ocid` validation rejecting an image name — as an A/B pair one variable apart |
| `refresh-command-parse.txt` | The image-refresh command in `variables.tf` tokenising into all 15 arguments, with the pre-fix one-liner as a negative control |

Terraform 1.16.0, the same binary used for the Gate 1 captures.

## What is deliberately not here

**No `apply`, no state write, no lock contention.** The `plan` runs pass `-lock=false` on
purpose: the S3 backend runs `use_lockfile = true`, so an ordinary `plan` would write and
delete a `.tflock` object, and `runs/gate1/` records that nothing in this repo has yet
written an object to that bucket. A capture taken to prove a failure should not quietly
falsify a claim elsewhere in the record.

**The variable values in those runs are placeholders**, supplied on the command line to get
past variable collection. None is committed and none was observed. The `compartment_ocid`
is a literal `...placeholder` string and the ingress CIDR is from RFC 5737's documentation
range.

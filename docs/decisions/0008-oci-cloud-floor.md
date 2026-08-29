# 0008 - OCI cloud floor: credentials, exposure, and sizing

**Status:** Accepted (configuration written; **not yet provisioned**)
**Date:** 2026-08-29
**Related:** [`0007`](0007-terraform-state-backend.md) (the same credential split, for AWS),
[`../PLAN.md`](../PLAN.md) section 7 Gate 2, [`../metrics.md`](../metrics.md)

## Context

Gate 2 provisions the OCI cloud floor: VCN, subnet, internet gateway, route table,
network security group, an A1.Flex instance and a block volume. Four decisions had to
be made before any of it could be written, and one of them involves a genuine secret
for the first time in this repo.

## Decision 1 - credentials by profile name, key outside the repo

`provider "oci"` sets `config_file_profile = var.oci_profile` (default `"signalbox"`)
and nothing else. The tenancy OCID, user OCID, fingerprint and API signing key live in
`~/.oci/config` and never enter the repository.

This is deliberately the same split as ADR 0007: **the profile name is a checkable
value and lives in the config; the secret lives outside git entirely.** The difference
is that OCI's secret is a real one - an RSA private key - where AWS's was only a
profile name.

**Rejected: explicit provider arguments from a gitignored `terraform.tfvars`.** It is
more explicit about what the provider needs, and that is its only advantage. A
gitignored file holding live credentials is exactly the shape that produced the
`.aws/credentials` incident on 2026-08-29 - untracked, unignored until someone
remembered, and invisible to the structural check, which walks tracked files. See
[`../limits.md`](../limits.md).

**Rejected: SOPS-encrypted tfvars.** Consistent with the project's stated secrets
story, but it pulls Gate 4's age-key bootstrap forward for no gain. The OCIDs are
identifiers rather than secrets, and the private key does not need to be in git at
all. `sops` and `age` are not installed, and there is no reason Gate 2 should be the
thing that requires them.

## Decision 2 - SSH restricted to the operator, not the internet

The NSG permits TCP 22 from `var.ssh_ingress_cidr` only. **The variable has no default
and no committed value.**

**Why no default.** The value is the operator's own public address. It is not a
credential, but it is personal, and this repository is on GitHub - a home IP in a
public repo is a privacy leak no gate would catch, because it is not
credential-shaped. It also changes, so a committed default rots into either a lockout
or a stale rule pointing at somebody else's address.

**The cost, stated.** Gate 9's rebuild drill fails if the operator's IP has changed
since the value was last supplied. That failure is loud, immediate, and fixed by one
variable - a better property than an internet-exposed SSH port that never fails and
never complains.

**Rejected: `0.0.0.0/0` with key-only authentication.** Defensible, common, and it
would keep the drill clean. Rejected because "the node holds no data yet" is an
argument that expires at Gate 5, and a rule nobody revisits after it stops being true
is how exposure becomes permanent.

### Where else that line falls, recorded rather than left implicit

Review 6 raised as an observation (O2) that `signalbox-tfstate-215573083789` - the
state bucket name in `main.tf` and in the bootstrap configuration - embeds the
12-digit AWS account ID, in a repository this project intends to be public. It sits
on the same side of the "not a credential, but personal" line this decision drew for
the home IP, so the distinction is written down rather than left to inference.

**It stays.** Two things separate it from the home IP:

- **It is not secret in the first place.** An account ID appears in every bucket ARN,
  every IAM policy document and every error message AWS returns to a caller. It is an
  identifier AWS treats as public; access is controlled by credentials and policy,
  not by its obscurity. A home IP has no such story - nothing else publishes it.
- **It cannot be supplied at apply time.** A backend block cannot refer to variables
  (ADR 0007 records the same constraint forcing `profile` to be a literal), so the
  bucket name has to be a literal in the configuration. `ssh_ingress_cidr` had a
  choice; this does not.

What it does leak is that this account exists, and its rough age. That is accepted.
The rule the two cases share, stated so a third does not need re-arguing: **a value
that is personal and avoidable stays out; a value that is public by the provider's
own design and structurally unavoidable goes in, with the reasoning recorded.**

**Egress is open**, which is not the same kind of decision. The node pulls k3s,
container images and upstream transit feeds; all are CDN-fronted with moving
addresses, so a CIDR allow-list would be a list of lies that breaks silently. This is
the argument PLAN.md section 7 already makes for Gate 8's blackhole injection over an
egress NetworkPolicy.

## Decision 3 - sizing is the allowance, not a preference

2 OCPU and 12 GB, one instance. Arithmetic, not judgement: 1,500 OCPU-hours / 730 =
2.05, and 9,000 GB-hours / 730 = 12.3. The Always Free allowance pays for exactly one
instance of this size running continuously. Larger leaves the free tier; smaller
wastes it. Re-verified against Oracle on 2026-08-29 - [`../metrics.md`](../metrics.md).

50 GB boot plus a 50 GB block volume, 100 GB of the 200 GB total, leaving headroom for
the five allowed backups. **The data volume is separate from boot on purpose:** it is
what makes Gate 9 a rebuild drill rather than a data-loss event.

## Decision 4 - the image is pinned, not resolved

**Reversed 2026-08-29, by the human, after review 6 raised it as F4.** The original
decision is kept below so the reversal is legible rather than looking like the
configuration was always this way.

`var.node_image_ocid` holds the image OCID and the instance uses it directly. There
is no `data "oci_core_images"` block.

**Originally decided the other way**, and written in the same commit as the code -
which is the process defect F4 named separately, and is why this section is being
revised by the party the rule constrains rather than confirmed by them. The argument
was: an image OCID is region-specific and is *replaced* when Canonical publishes a
new build, so pinning one produces an apply that fails on a date nobody chose.
CLAUDE.md's "pin every version" was read as covering artefacts whose selection we
control - charts, provider versions, action SHAs, container digests - with the
selection rule as the stable thing here.

**Why that reading loses.** It collides with Gate 2's own criterion: *"destroy then
apply produces a working SSH-able node. Twice."* A floating image means the two
applies are not guaranteed to resolve the same image, so the drill would not be
repeating itself - it would be running two different experiments and reporting one
result. The same applies to Gate 9's rebuild drill, where the whole claim is that
the rebuilt node is the node that was destroyed.

**Determinism outranks avoiding a stale pin here, because the gate's verification
depends on it.** A stale pin fails loudly on a date nobody chose; a floating image
succeeds quietly while making the verification mean less than it appears to. The
first failure mode is the one this repo consistently prefers.

**Accepted cost: the refresh is a known maintenance task.** Canonical publishes new
24.04 builds and Oracle eventually retires old ones, so the pin goes stale on their
schedule. The refresh command sits next to the variable in `variables.tf`, not only
here - **and from `696959f` until now it was not runnable.** Embedded `#` characters mid-line
made a shell drop every flag after the first; review 7's F4. The mitigation *is* the
accepted cost, so a mitigation nobody had run was the cost being unpaid. It is now
split across comment lines and verified by tokenising it rather than by reading it:
[`runs/gate2/refresh-command-parse.txt`](../../runs/gate2/refresh-command-parse.txt).

**No default, and that is not the same as unpinned.** The value has never been
observed: there is no tenancy, and an image OCID is region-specific, so committing
one now would be inventing a number rather than measuring it - the thing this repo's
own rules forbid. The variable has no default and a validation that rejects anything
not shaped like an image OCID, so a missing or wrong value is a loud failure at plan
time rather than a silent resolve. **The default gets filled in at Gate 2, from the
value actually applied.** An image OCID is an identifier, not a secret; it belongs in
git as soon as it is real.

**Ubuntu rather than Oracle Linux** is unchanged and is still an assumption, not a
measured decision. Oracle Linux is OCI-native; Ubuntu is far better documented for
k3s and Ansible, which is Gate 3's entire content. It should be reversed if Gate 3
fights the distribution rather than the work - which now means changing the OCID
rather than a filter.

## Consequences

- **Gate 2 is written but not passed.** There is no OCI account, so `apply` and the
  SSH verification have not run. What has been observed, 2026-08-29, and re-observed
  after the Decision 4 reversal: `terraform fmt -check` clean, `init` successful
  against the real S3 backend, `validate` successful, and `plan` failing at
  `open ~/.oci/config: The system cannot find the path specified` - which is the
  blocker itself, reported by Terraform rather than asserted here. The `plan` failure
  is captured in
  [`runs/gate2/terraform-plan-blocked.txt`](../../runs/gate2/terraform-plan-blocked.txt);
  the static checks are in [`runs/gate1/`](../../runs/gate1/) and in CI.
- **The image OCID validation was checked adversarially, not assumed.** `plan` with
  `node_image_ocid=ubuntu-24-04-aarch64` returns *Invalid value for variable* against
  the validation rule in `variables.tf`. A validation nobody has seen reject anything is
  indistinguishable from one that cannot - **and for one commit this ADR was making that
  argument about an observation it had not captured.** Review 7's F2. Both runs are now
  under [`runs/gate2/`](../../runs/gate2/), as an A/B pair: the same `plan` with an
  OCID-shaped value produces the provider error and no validation error, so the rejection
  is the rule firing rather than noise from the missing config.
- Two claims in PLAN.md section 3 stay unverified and can only be settled by
  provisioning: **Frankfurt A1 capacity**, and **idle reclamation** below 10% CPU and
  network over 7 days. `var.availability_domain_index` exists because of the first -
  if capacity is refused in one AD, the observation is the verification.
- No key material is committed. The SSH public key is read with
  `file(pathexpand(var.ssh_public_key_path))` rather than inlined - confirmed to
  matter: an inline literal trips the credential gate on `ssh_authorized_keys`, which
  contains `key`. The file reference avoided needing a third gate exemption.

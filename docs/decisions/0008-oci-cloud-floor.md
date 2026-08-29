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

## Decision 4 - the image is resolved, not pinned

`data "oci_core_images"` filtered to Canonical Ubuntu 24.04 on the A1.Flex shape,
newest first - not a hardcoded image OCID.

This looks like a violation of CLAUDE.md's "pin every version" and is not. An image
OCID is region-specific and is *replaced* when Canonical publishes a new build, so
pinning one produces an apply that fails on a date nobody chose. The pinning rule is
about artefacts whose selection we control - charts, provider versions, action SHAs,
container digests. Here the selection rule is the stable thing.

**Ubuntu rather than Oracle Linux** is an assumption, not a measured decision. Oracle
Linux is OCI-native; Ubuntu is far better documented for k3s and Ansible, which is
Gate 3's entire content. One filter change reverses it, and it should be reversed if
Gate 3 fights the distribution rather than the work.

## Consequences

- **Gate 2 is written but not passed.** There is no OCI account, so `plan`, `apply`
  and the SSH verification have not run. `terraform init`, `validate` and `fmt` all
  succeed offline, and that is the whole of what has been observed.
- Two claims in PLAN.md section 3 stay unverified and can only be settled by
  provisioning: **Frankfurt A1 capacity**, and **idle reclamation** below 10% CPU and
  network over 7 days. `var.availability_domain_index` exists because of the first -
  if capacity is refused in one AD, the observation is the verification.
- No key material is committed. The SSH public key is read with
  `file(pathexpand(var.ssh_public_key_path))` rather than inlined - confirmed to
  matter: an inline literal trips the credential gate on `ssh_authorized_keys`, which
  contains `key`. The file reference avoided needing a third gate exemption.

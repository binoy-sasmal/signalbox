variable "oci_profile" {
  description = "Profile name in ~/.oci/config. The private key stays outside this repo; only the profile name lives here. See ADR 0008."
  type        = string
  default     = "signalbox"
}

variable "compartment_ocid" {
  description = "OCID of the compartment to build in. The tenancy OCID is the root compartment and is a valid answer."
  type        = string
}

# No default, deliberately. This is the operator's own public address: not a
# credential, but personal, and it changes. Committing it would put a home IP in
# a public repository and would silently rot. ADR 0008 records the tradeoff.
variable "ssh_ingress_cidr" {
  description = "CIDR permitted to reach port 22. Use your own address as a /32 -- find it with `curl ifconfig.me`."
  type        = string

  validation {
    condition     = can(cidrnetmask(var.ssh_ingress_cidr))
    error_message = "Must be a CIDR block, e.g. 203.0.113.7/32 -- a bare address is not accepted."
  }
}

variable "ssh_public_key_path" {
  description = "Path to the PUBLIC half of the SSH key placed on the node. Never the private half."
  type        = string
  default     = "~/.ssh/signalbox_ed25519.pub"
}

# PINNED, not resolved. This was a `data "oci_core_images"` block sorted newest
# first until 2026-08-29, when review 6's F4 raised that a floating image
# collides with Gate 2's own criterion: "destroy then apply produces a working
# SSH-able node. Twice." Two applies either side of a Canonical publish resolve
# two different images, so the drill would not be repeating itself. The human
# ruled that determinism outranks avoiding a stale pin, because the gate's
# verification depends on it. ADR 0008 decision 4 records the reversal.
#
# No default, for the same reason `ssh_ingress_cidr` has none: the value has
# never been observed. An image OCID is region-specific and this repo has no OCI
# tenancy yet, so a committed default would be invented rather than measured.
# Fill the default in at Gate 2, from the value actually applied -- an image
# OCID is an identifier, not a secret, and belongs in git once it is real.
#
# REFRESH IS A KNOWN MAINTENANCE TASK. Canonical publishes new 24.04 builds and
# retires old ones; this pin goes stale on Oracle's schedule, not ours, and the
# failure is a loud apply error rather than a silent drift. Find the current
# value with:
#
#   oci compute image list --compartment-id <compartment> #     --operating-system "Canonical Ubuntu" --operating-system-version "24.04" #     --shape VM.Standard.A1.Flex --sort-by TIMECREATED --sort-order DESC
variable "node_image_ocid" {
  description = "OCID of the Canonical Ubuntu 24.04 aarch64 image for VM.Standard.A1.Flex in eu-frankfurt-1. Pinned so the Gate 2 and Gate 9 drills repeat on one image; refreshed deliberately. See ADR 0008."
  type        = string

  validation {
    condition     = can(regex("^ocid1[.]image[.]", var.node_image_ocid))
    error_message = "Must be an image OCID, e.g. ocid1.image.oc1.eu-frankfurt-1.aaaa... -- an image name is not accepted."
  }
}

# Frankfurt has three availability domains and A1 capacity is not uniform across
# them. PLAN.md section 3 marks 'Frankfurt provisions quickly' as folklore with
# no primary source. If capacity is refused in one AD, move to 1 or 2 and record
# what was actually observed -- that observation is the verification.
variable "availability_domain_index" {
  description = "Which Frankfurt availability domain to use (0, 1 or 2)."
  type        = number
  default     = 0
}

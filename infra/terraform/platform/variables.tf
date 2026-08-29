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

# Frankfurt has three availability domains and A1 capacity is not uniform across
# them. PLAN.md section 3 marks 'Frankfurt provisions quickly' as folklore with
# no primary source. If capacity is refused in one AD, move to 1 or 2 and record
# what was actually observed -- that observation is the verification.
variable "availability_domain_index" {
  description = "Which Frankfurt availability domain to use (0, 1 or 2)."
  type        = number
  default     = 0
}

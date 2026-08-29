# Platform: OCI cloud floor -- VCN, subnet, gateway, route table, NSG, compute,
# block volume.
#
# Empty of resources at Gate 1, deliberately. Gate 1 asks only that this
# configuration uses the bootstrap bucket as its backend and that
# `terraform init` succeeds against it. The OCI provider and every resource
# above arrives at Gate 2; declaring them now would be scaffolding ahead.

terraform {
  required_version = "1.16.0"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "8.29.0"
    }
  }

  # State locking is native to S3 via `use_lockfile`, which uses S3 conditional
  # writes. Introduced in Terraform 1.10; DynamoDB-based locking is deprecated
  # and slated for removal. This is what makes PLAN.md's "no DynamoDB lock
  # table needed" true rather than aspirational.
  #
  # Requires s3:GetObject, s3:PutObject and s3:DeleteObject on the .tflock
  # object, not only on the state object.
  # `profile` is a literal here and a variable in ../bootstrap. That asymmetry
  # is forced, not chosen: "A backend block cannot refer to named values (like
  # input variables, locals, or data source attributes)" -- Terraform backend
  # documentation. The same constraint is why `bucket` is duplicated rather
  # than shared. ADR 0007 records both.
  backend "s3" {
    bucket       = "signalbox-tfstate-215573083789"
    key          = "platform/terraform.tfstate"
    region       = "eu-central-1"
    profile      = "signalbox"
    use_lockfile = true
  }
}

# Credentials come from ~/.oci/config, which holds the API signing key. Only the
# PROFILE NAME lives in this repo -- the same split as the AWS decision in ADR
# 0007, and the reason no SOPS machinery is needed at Gate 2. See ADR 0008.
provider "oci" {
  config_file_profile = var.oci_profile
  region              = "eu-frankfurt-1"
}

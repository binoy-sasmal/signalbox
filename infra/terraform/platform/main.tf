# Platform: OCI cloud floor -- VCN, subnet, gateway, route table, NSG, compute,
# block volume.
#
# Empty of resources at Gate 1, deliberately. Gate 1 asks only that this
# configuration uses the bootstrap bucket as its backend and that
# `terraform init` succeeds against it. The OCI provider and every resource
# above arrives at Gate 2; declaring them now would be scaffolding ahead.

terraform {
  required_version = "1.16.0"

  # State locking is native to S3 via `use_lockfile`, which uses S3 conditional
  # writes. Introduced in Terraform 1.10; DynamoDB-based locking is deprecated
  # and slated for removal. This is what makes PLAN.md's "no DynamoDB lock
  # table needed" true rather than aspirational.
  #
  # Requires s3:GetObject, s3:PutObject and s3:DeleteObject on the .tflock
  # object, not only on the state object.
  backend "s3" {
    bucket       = "signalbox-tfstate-215573083789"
    key          = "platform/terraform.tfstate"
    region       = "eu-central-1"
    use_lockfile = true
  }
}

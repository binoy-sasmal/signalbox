# Bootstrap: the S3 bucket that holds every other configuration's state.
#
# This is the chicken-and-egg root of the state story. It creates the bucket
# that `../platform` uses as a backend, so it cannot use that bucket itself.
# Its own state stays local and gitignored -- see ADR 0007 for why that is
# preferred over committing it or migrating it into the bucket it just made.
#
# Run this once, from this directory, with AWS_PROFILE set. After that it
# should not need to run again.

terraform {
  required_version = "1.16.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.62.0"
    }
  }
}

# Region hardcoded rather than parameterised: there is one caller and one
# region, and CLAUDE.md's rule is to hardcode until a second caller exists.
# eu-central-1 matches the OCI Frankfurt decision in PLAN.md section 3.
#
# `profile` is set from a variable rather than read from AWS_PROFILE. A repo
# that claims reproducibility should not depend on an environment variable that
# has already failed to persist once on this machine. See ADR 0007 for the
# tradeoff this accepts -- it couples the config to a local profile name, and
# the CI answer later is OIDC, which ADR 0001 flags as verify-don't-assume.
provider "aws" {
  region  = "eu-central-1"
  profile = var.aws_profile
}

resource "aws_s3_bucket" "state" {
  bucket = "signalbox-tfstate-215573083789"

  # No `prevent_destroy` lifecycle block, deliberately. Gate 9 is a rebuild
  # drill that destroys and rebuilds from git, and a guard that blocks it would
  # have to be removed by hand at exactly the moment the drill is meant to
  # prove nothing manual is needed. Whether the state bucket is inside or
  # outside "everything" is a Gate 9 decision, and it is not made here.
}

# Versioning is the one piece of hardening that is load-bearing rather than
# hygiene: a corrupted or truncated state push is recoverable from a prior
# object version, and without it the recovery path is "rebuild from nothing".
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

# S3 blocks public access by default on new buckets, so this is belt and
# braces rather than a fix. It is kept because it is an explicit, auditable
# assertion about a bucket holding infrastructure state, and because a default
# is a thing that can change under you.
resource "aws_s3_bucket_public_access_block" "state" {
  bucket = aws_s3_bucket.state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

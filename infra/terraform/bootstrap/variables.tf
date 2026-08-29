# The local AWS CLI profile Terraform authenticates with.
#
# A variable rather than a literal so an account migration is a default change
# here, not a find-and-replace. Note the asymmetry recorded in ADR 0007: this
# works in a provider block and cannot work in a backend block, which is why
# `../platform` carries the profile as a literal.
variable "aws_profile" {
  description = "Local AWS CLI profile used to authenticate. See README.md."
  type        = string
  default     = "signalbox"
}

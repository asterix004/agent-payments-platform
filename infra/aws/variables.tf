variable "region" {
  type    = string
  default = "us-east-1"
}

variable "name" {
  description = "Prefix for every resource."
  type        = string
  default     = "agent-payments"
}

variable "kubernetes_version" {
  description = "EKS version. Null lets EKS pick its current default."
  type        = string
  default     = null
}

variable "admin_cidrs" {
  description = "CIDRs allowed to reach the public EKS API endpoint. Set to your own IP (/32)."
  type        = list(string)
}

variable "node_instance_types" {
  description = "Spot instance types for the demo node group (several, so Spot capacity is easier to find)."
  type        = list(string)
  default     = ["t3.large", "t3a.large", "m5.large"]
}

variable "node_count" {
  type    = number
  default = 2
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "kya_public_key_pem" {
  description = "Public key of the KYA token issuer (not secret, but kept with the other runtime config)."
  type        = string
}

variable "github_repository" {
  description = "owner/repo allowed to assume the CI role via GitHub OIDC."
  type        = string
}

variable "create_github_oidc_provider" {
  description = "Set false if the account already has the token.actions.githubusercontent.com provider."
  type        = bool
  default     = true
}

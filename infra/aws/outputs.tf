output "cluster_name" {
  value = module.eks.cluster_name
}

output "region" {
  value = var.region
}

output "db_endpoint" {
  description = "Host:port for the payments database (goes into values-aws.yaml)."
  value       = module.db.db_instance_endpoint
}

output "db_master_secret_arn" {
  description = "Secrets Manager secret holding the RDS-managed username/password."
  value       = module.db.db_instance_master_user_secret_arn
}

output "github_plan_role_arn" {
  description = "Set as repository variable AWS_PLAN_ROLE_ARN to enable `terraform plan` in CI."
  value       = aws_iam_role.github_plan.arn
}

data "aws_availability_zones" "available" {
  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

data "aws_caller_identity" "current" {}

locals {
  azs      = slice(data.aws_availability_zones.available.names, 0, 2)
  vpc_cidr = "10.40.0.0/16"
  tags = {
    Project   = var.name
    ManagedBy = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Network: private subnets for nodes and RDS, one NAT gateway (demo trade-off,
# see docs/adr/0004-aws-cost-shape.md).
# ---------------------------------------------------------------------------
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 6.7"

  name = var.name
  cidr = local.vpc_cidr
  azs  = local.azs

  private_subnets  = [for i, _ in local.azs : cidrsubnet(local.vpc_cidr, 4, i)]
  public_subnets   = [for i, _ in local.azs : cidrsubnet(local.vpc_cidr, 8, i + 48)]
  database_subnets = [for i, _ in local.azs : cidrsubnet(local.vpc_cidr, 8, i + 52)]

  create_database_subnet_group = true
  enable_nat_gateway           = true
  single_nat_gateway           = true

  public_subnet_tags  = { "kubernetes.io/role/elb" = 1 }
  private_subnet_tags = { "kubernetes.io/role/internal-elb" = 1 }
}

# ---------------------------------------------------------------------------
# EKS
# ---------------------------------------------------------------------------
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.29"

  name               = var.name
  kubernetes_version = var.kubernetes_version

  # STANDARD: a cluster left on an old version is auto-upgraded instead of moving
  # to extended support, which bills the control plane at ~6x ($0.60/h vs $0.10/h).
  upgrade_policy = { support_type = "STANDARD" }

  endpoint_public_access       = true
  endpoint_public_access_cidrs = var.admin_cidrs

  enable_cluster_creator_admin_permissions = true

  addons = {
    coredns                = {}
    kube-proxy             = {}
    eks-pod-identity-agent = { before_compute = true }
    vpc-cni                = { before_compute = true }
    # The payments HPA scales on CPU; EKS ships no metrics API without this.
    metrics-server = {}
  }

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  eks_managed_node_groups = {
    default = {
      ami_type       = "AL2023_x86_64_STANDARD"
      capacity_type  = "SPOT"
      instance_types = var.node_instance_types
      min_size       = 1
      max_size       = 4
      desired_size   = var.node_count
    }
  }
}

# ---------------------------------------------------------------------------
# PostgreSQL. RDS generates and rotates the master password in Secrets Manager,
# so it never appears in Terraform state or variables.
# ---------------------------------------------------------------------------
resource "aws_security_group" "db" {
  name        = "${var.name}-db"
  description = "Postgres from EKS nodes only"
  vpc_id      = module.vpc.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "db_from_nodes" {
  security_group_id            = aws_security_group.db.id
  referenced_security_group_id = module.eks.node_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  description                  = "EKS nodes"
}

module "db" {
  source  = "terraform-aws-modules/rds/aws"
  version = "~> 7.2"

  identifier     = "${var.name}-pg"
  engine         = "postgres"
  engine_version = "17"
  family         = "postgres17"
  instance_class = var.db_instance_class

  allocated_storage     = 20
  max_allocated_storage = 50
  storage_encrypted     = true

  db_name                     = "payments"
  username                    = "payments_admin"
  manage_master_user_password = true
  port                        = 5432

  db_subnet_group_name   = module.vpc.database_subnet_group_name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false
  multi_az               = false

  backup_retention_period = 1
  skip_final_snapshot     = true
  deletion_protection     = false

  parameters = [
    # Static parameter: AWS records it as pending-reboot, so say so here or every
    # plan shows a phantom in-place change. New instances start with it applied.
    { name = "rds.force_ssl", value = "1", apply_method = "pending-reboot" }
  ]
}

# ---------------------------------------------------------------------------
# Runtime secrets read by External Secrets Operator (EKS Pod Identity).
# ---------------------------------------------------------------------------
resource "aws_secretsmanager_secret" "kya_public_key" {
  name                    = "${var.name}/prod/kya-public-key"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "kya_public_key" {
  secret_id     = aws_secretsmanager_secret.kya_public_key.id
  secret_string = var.kya_public_key_pem
}

data "aws_iam_policy_document" "pod_identity_trust" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "read_payment_secrets" {
  statement {
    actions = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [
      module.db.db_instance_master_user_secret_arn,
      aws_secretsmanager_secret.kya_public_key.arn,
    ]
  }
}

resource "aws_iam_role" "external_secrets" {
  name               = "${var.name}-external-secrets"
  assume_role_policy = data.aws_iam_policy_document.pod_identity_trust.json
}

resource "aws_iam_role_policy" "external_secrets" {
  role   = aws_iam_role.external_secrets.id
  policy = data.aws_iam_policy_document.read_payment_secrets.json
}

resource "aws_eks_pod_identity_association" "external_secrets" {
  cluster_name    = module.eks.cluster_name
  namespace       = "external-secrets"
  service_account = "external-secrets"
  role_arn        = aws_iam_role.external_secrets.arn
}

# ---------------------------------------------------------------------------
# GitHub Actions -> AWS via OIDC. No access keys exist anywhere.
# The role is read-only and can be assumed only by this repository's
# pull-request and main-branch workflows (used for `terraform plan`).
# ---------------------------------------------------------------------------
resource "aws_iam_openid_connect_provider" "github" {
  count          = var.create_github_oidc_provider ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

locals {
  github_oidc_arn = var.create_github_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : "arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/token.actions.githubusercontent.com"
}

data "aws_iam_policy_document" "github_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "repo:${var.github_repository}:pull_request",
        "repo:${var.github_repository}:ref:refs/heads/main",
      ]
    }
  }
}

resource "aws_iam_role" "github_plan" {
  name                 = "${var.name}-github-terraform-plan"
  assume_role_policy   = data.aws_iam_policy_document.github_trust.json
  max_session_duration = 3600
}

resource "aws_iam_role_policy_attachment" "github_plan_readonly" {
  role       = aws_iam_role.github_plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

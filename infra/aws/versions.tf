terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0"
    }
  }

  # Remote state for anything beyond a personal sandbox:
  # backend "s3" {
  #   bucket       = "<state-bucket>"
  #   key          = "agent-payments/aws.tfstate"
  #   region       = "us-east-2"
  #   use_lockfile = true
  #   encrypt      = true
  # }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = local.tags
  }
}

# 初回だけ管理者権限で手動 apply する土台（state 用バケット、GitHub Actions の OIDC ロール）。
# state はローカルに残る（terraform.tfstate）。秘密情報は含まないが、リポジトリにはコミットしない。

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

variable "project" {
  type    = string
  default = "teket-alt"
}

variable "region" {
  type    = string
  default = "ap-northeast-1"
}

variable "github_repository" {
  description = "owner/repo"
  type        = string
  default     = "YK0107/altanative-teket"
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = var.project }
  }
}

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "tfstate" {
  bucket = "${var.project}-tfstate-${data.aws_caller_identity.current.account_id}"
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

# environment: production のジョブからのみ引き受け可能。
# GitHub 側で production の Deployment branches を main のみに制限すること（制限しないと他ブランチから使える）
resource "aws_iam_role" "deploy" {
  name = "${var.project}-github-deploy"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repository}:environment:production"
        }
      }
    }]
  })
}

locals {
  account = data.aws_caller_identity.current.account_id
}

resource "aws_iam_role_policy" "deploy" {
  name = "deploy"
  role = aws_iam_role.deploy.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Services"
        Effect = "Allow"
        Action = [
          "dynamodb:*", "lambda:*", "apigateway:*", "cloudfront:*", "s3:*", "logs:*", "events:*",
          "ses:*", "route53:*", "acm:*", "sns:*", "cloudwatch:*",
        ]
        Resource = "*"
      },
      {
        Sid    = "ProjectRoles"
        Effect = "Allow"
        Action = [
          "iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:UpdateRole", "iam:TagRole", "iam:UntagRole",
          "iam:PutRolePolicy", "iam:GetRolePolicy", "iam:DeleteRolePolicy", "iam:ListRolePolicies",
          "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:ListAttachedRolePolicies",
          "iam:ListInstanceProfilesForRole", "iam:UpdateAssumeRolePolicy", "iam:PassRole",
        ]
        Resource = "arn:aws:iam::${local.account}:role/${var.project}-api"
      },
      {
        # Lambda からの SSM 参照ポリシーを作るために名前だけ読める（値は読まない）
        Sid      = "SsmDescribe"
        Effect   = "Allow"
        Action   = ["ssm:DescribeParameters"]
        Resource = "*"
      },
    ]
  })
}

output "state_bucket" {
  value = aws_s3_bucket.tfstate.bucket
}

output "deploy_role_arn" {
  value = aws_iam_role.deploy.arn
}

terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.68.0"
    }
  }
}

provider "aws" {
  region              = "ap-south-1"
  allowed_account_ids = ["707256068320"]
}

variable "create_github_oidc_provider" {
  type        = bool
  description = "Set false if token.actions.githubusercontent.com already exists in this AWS account."
  default     = true
}

locals {
  account_id        = "707256068320"
  state_bucket      = "ccd-terraform-state-707256068320-ap-south-1"
  oidc_provider_arn = "arn:aws:iam::${local.account_id}:oidc-provider/token.actions.githubusercontent.com"
  github_subject    = "repo:RAJULA-SAI-CHETAN-REDDY@178785352/Cloud_Certificate_System@1402759421:environment:development"
  project_policy_names = toset([
    "CCDApiGatewayDeployment",
    "CCDCognitoDevelopment",
    "CCDFrontendDeployment",
    "CCDIssuanceDeployment",
    "CCDNotificationDeployment",
  ])
}

resource "aws_s3_bucket" "terraform_state" {
  bucket = local.state_bucket

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_public_access_block" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_policy" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.terraform_state.arn, "${aws_s3_bucket.terraform_state.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 1 : 0

  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

resource "aws_iam_role" "github_deploy" {
  name                 = "ccd-github-deploy"
  max_session_duration = 3600
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = local.oidc_provider_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = { StringEquals = {
        "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        "token.actions.githubusercontent.com:sub" = local.github_subject
      } }
    }]
  })

  depends_on = [aws_iam_openid_connect_provider.github]
}

resource "aws_iam_policy" "state_access" {
  name = "CCDDevelopmentTerraformState"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.terraform_state.arn
        Condition = { StringLike = { "s3:prefix" = [
          "development/*", "bootstrap/*"
        ] } }
      },
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject"]
        Resource = [
          "${aws_s3_bucket.terraform_state.arn}/development/terraform.tfstate",
          "${aws_s3_bucket.terraform_state.arn}/bootstrap/terraform.tfstate",
        ]
      },
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = [
          "${aws_s3_bucket.terraform_state.arn}/development/terraform.tfstate.tflock",
          "${aws_s3_bucket.terraform_state.arn}/bootstrap/terraform.tfstate.tflock",
        ]
      },
    ]
  })
}

resource "aws_iam_user_policy_attachment" "developer_state" {
  user       = "ccd-developer"
  policy_arn = aws_iam_policy.state_access.arn
}

resource "aws_iam_role_policy_attachment" "github_state" {
  role       = aws_iam_role.github_deploy.name
  policy_arn = aws_iam_policy.state_access.arn
}

resource "aws_iam_role_policy" "github_storage" {
  name = "CCDStorageDevelopment"
  role = aws_iam_role.github_deploy.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ManageProjectCertificateBucket"
        Effect = "Allow"
        Action = "s3:*"
        Resource = [
          "arn:aws:s3:::ccd-certificates-707256068320-ap-south-1",
          "arn:aws:s3:::ccd-certificates-707256068320-ap-south-1/*",
        ]
      },
      {
        Sid      = "ManageProjectCertificateTable"
        Effect   = "Allow"
        Action   = "dynamodb:*"
        Resource = "arn:aws:dynamodb:ap-south-1:707256068320:table/ccd-certificates"
      },
    ]
  })
}

resource "aws_iam_role_policy" "github_verification" {
  name = "CCDVerificationDeployment"
  role = aws_iam_role.github_deploy.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ManageVerificationLambda"
        Effect   = "Allow"
        Action   = "lambda:*"
        Resource = "arn:aws:lambda:ap-south-1:707256068320:function:ccd-verify-certificate"
      },
      {
        Sid    = "ManageVerificationRole"
        Effect = "Allow"
        Action = [
          "iam:CreateRole",
          "iam:GetRole",
          "iam:UpdateAssumeRolePolicy",
          "iam:DeleteRole",
          "iam:TagRole",
          "iam:UntagRole",
          "iam:ListRoleTags",
          "iam:PutRolePolicy",
          "iam:GetRolePolicy",
          "iam:DeleteRolePolicy",
          "iam:ListRolePolicies",
          "iam:ListAttachedRolePolicies",
          "iam:ListInstanceProfilesForRole",
        ]
        Resource = "arn:aws:iam::707256068320:role/ccd-verification-lambda-role"
      },
      {
        Sid      = "PassVerificationRoleToLambda"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = "arn:aws:iam::707256068320:role/ccd-verification-lambda-role"
        Condition = {
          StringEquals = { "iam:PassedToService" = "lambda.amazonaws.com" }
        }
      },
      {
        Sid    = "ManageVerificationLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:DeleteLogGroup",
          "logs:PutRetentionPolicy",
          "logs:DeleteRetentionPolicy",
          "logs:TagResource",
          "logs:UntagResource",
          "logs:ListTagsForResource",
          "logs:TagLogGroup",
          "logs:UntagLogGroup",
          "logs:ListTagsLogGroup",
        ]
        Resource = [
          "arn:aws:logs:ap-south-1:707256068320:log-group:/aws/lambda/ccd-verify-certificate",
          "arn:aws:logs:ap-south-1:707256068320:log-group:/aws/lambda/ccd-verify-certificate:*",
        ]
      },
      {
        Sid      = "FindLogGroups"
        Effect   = "Allow"
        Action   = "logs:DescribeLogGroups"
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "github_project" {
  for_each = local.project_policy_names

  role       = aws_iam_role.github_deploy.name
  policy_arn = "arn:aws:iam::${local.account_id}:policy/${each.key}"
}

output "state_bucket" {
  value = aws_s3_bucket.terraform_state.bucket
}

output "github_deploy_role_arn" {
  value = aws_iam_role.github_deploy.arn
}

output "github_oidc_subject" {
  value = local.github_subject
}

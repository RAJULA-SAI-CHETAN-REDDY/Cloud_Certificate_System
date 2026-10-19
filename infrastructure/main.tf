terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region  = "ap-south-1"
  profile = "ccd"

  default_tags {
    tags = {
      Project     = "CloudCertificateSystem"
      Environment = "development"
    }
  }
}

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "certificates" {
  bucket = "ccd-certificates-${data.aws_caller_identity.current.account_id}-ap-south-1"
}

resource "aws_s3_bucket_public_access_block" "certificates" {
  bucket = aws_s3_bucket.certificates.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "certificates" {
  bucket = aws_s3_bucket.certificates.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_dynamodb_table" "certificates" {
  name         = "ccd-certificates"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "certificate_id"

  attribute {
    name = "certificate_id"
    type = "S"
  }
}

output "certificate_bucket" {
  value = aws_s3_bucket.certificates.bucket
}

output "certificate_table" {
  value = aws_dynamodb_table.certificates.name
}

output "aws_region" {
  value = "ap-south-1"
}
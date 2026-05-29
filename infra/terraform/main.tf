# main.tf — Provider configuration for the Meridian Platform.
# Pins provider versions for reproducible builds (supply chain security).
# GitHub Actions authenticates via OIDC — no static AWS credentials required.

terraform {
  # Tightened to ~> 1.9 — prevents accidental use of older 1.6/1.7 versions
  # and aligns with the pinned version in terraform.yml CI.
  required_version = "~> 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.50" # bumped from 5.31; stay within 5.x for non-breaking changes
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.45" # last stable v4.x; v5 has breaking schema changes (value→content)
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  # Propagate default tags to every resource that supports tags
  default_tags {
    tags = var.tags
  }
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

# ─────────────────────────────────────────────────────────────────────────────
# S3 Remote State Bucket
# Must exist before `terraform init` — created via infra/scripts/bootstrap.sh.
# We declare it here so Terraform can manage its configuration going forward.
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_s3_bucket" "tfstate" {
  bucket = var.state_bucket_name

  # State loss is catastrophic — prevent accidental destroy
  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name    = "${var.project_name}-tfstate"
    Purpose = "terraform-remote-state"
  }
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  versioning_configuration {
    status = "Enabled" # Enables state file history and rollback
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true # Reduces KMS API costs when using SSE-S3
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ─────────────────────────────────────────────────────────────────────────────
# DynamoDB State Lock Table
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_dynamodb_table" "tflock" {
  name         = var.lock_table_name
  billing_mode = "PAY_PER_REQUEST" # No capacity planning — lock ops are infrequent
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name    = "${var.project_name}-tflock"
    Purpose = "terraform-state-locking"
  }
}

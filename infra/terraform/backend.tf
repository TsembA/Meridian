# backend.tf — Configures Terraform remote state in S3 with DynamoDB locking.
# IMPORTANT: The S3 bucket and DynamoDB table must exist before running
# `terraform init`. Use infra/scripts/bootstrap.sh to create them first.
# The bucket name must be globally unique — update if it conflicts.

terraform {
  backend "s3" {
    bucket         = "meridian-platform-tfstate"
    key            = "meridian/terraform.tfstate"
    region         = "us-west-1"
    encrypt        = true                          # AES-256 server-side encryption
    dynamodb_table = "meridian-platform-tflock"    # Prevents concurrent applies
  }
}

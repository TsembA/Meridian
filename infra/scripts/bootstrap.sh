#!/usr/bin/env bash
# bootstrap.sh — One-time setup of S3 remote state bucket and DynamoDB lock table.
# Run this BEFORE `terraform init` on a brand-new AWS account / region.
# It is idempotent: safe to re-run if the bucket/table already exists.
#
# Usage:
#   chmod +x infra/scripts/bootstrap.sh
#   AWS_PROFILE=your-profile ./infra/scripts/bootstrap.sh
#
# Prerequisites: AWS CLI v2 installed and configured with credentials that have
#   s3:CreateBucket, s3:PutBucketVersioning, s3:PutEncryptionConfiguration,
#   s3:PutPublicAccessBlock, dynamodb:CreateTable permissions.

set -euo pipefail

# ─── Configuration (must match backend.tf) ───────────────────────────────────
BUCKET_NAME="${STATE_BUCKET:-meridian-platform-tfstate}"
TABLE_NAME="${LOCK_TABLE:-meridian-platform-tflock}"
REGION="${AWS_REGION:-us-west-1}"

echo "==> Bootstrapping Terraform state backend"
echo "    Region : ${REGION}"
echo "    Bucket : ${BUCKET_NAME}"
echo "    Table  : ${TABLE_NAME}"
echo

# ─── S3 Bucket ───────────────────────────────────────────────────────────────

echo "--> Creating S3 bucket: ${BUCKET_NAME}"

# us-east-1 does not accept LocationConstraint; all other regions require it
if [ "${REGION}" = "us-east-1" ]; then
  aws s3api create-bucket \
    --bucket "${BUCKET_NAME}" \
    --region "${REGION}" \
    2>/dev/null || echo "    Bucket already exists — skipping create"
else
  aws s3api create-bucket \
    --bucket "${BUCKET_NAME}" \
    --region "${REGION}" \
    --create-bucket-configuration LocationConstraint="${REGION}" \
    2>/dev/null || echo "    Bucket already exists — skipping create"
fi

echo "--> Enabling versioning on ${BUCKET_NAME}"
aws s3api put-bucket-versioning \
  --bucket "${BUCKET_NAME}" \
  --versioning-configuration Status=Enabled

echo "--> Enabling AES-256 server-side encryption on ${BUCKET_NAME}"
aws s3api put-bucket-encryption \
  --bucket "${BUCKET_NAME}" \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "AES256"
      },
      "BucketKeyEnabled": true
    }]
  }'

echo "--> Blocking all public access on ${BUCKET_NAME}"
aws s3api put-public-access-block \
  --bucket "${BUCKET_NAME}" \
  --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

# ─── DynamoDB Table ───────────────────────────────────────────────────────────

echo "--> Creating DynamoDB table: ${TABLE_NAME}"
aws dynamodb create-table \
  --table-name "${TABLE_NAME}" \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region "${REGION}" \
  2>/dev/null || echo "    Table already exists — skipping create"

echo
echo "==> Bootstrap complete. You can now run: terraform init"

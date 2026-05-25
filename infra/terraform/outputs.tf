# outputs.tf — Terraform outputs for the Meridian Platform.
# These values are printed after `terraform apply` and readable via `terraform output <name>`.
# Sensitive outputs (role ARNs, IPs) are marked sensitive where appropriate.
# CI/CD workflows read non-sensitive outputs to configure deployment steps.

# ─────────────────────────────────────────────────────────────────────────────
# Networking
# ─────────────────────────────────────────────────────────────────────────────

output "vpc_id" {
  description = "VPC ID — reference this when adding future peered services"
  value       = aws_vpc.main.id
}

output "public_subnet_id" {
  description = "Public subnet ID where the k3s EC2 instance runs"
  value       = aws_subnet.public.id
}

output "ec2_public_ip" {
  description = "Elastic IP of the k3s node — Cloudflare DNS A record points here"
  value       = aws_eip.main.public_ip
}

output "ec2_private_ip" {
  description = "Private IP of the k3s node — use for intra-VPC communication"
  value       = aws_instance.main.private_ip
}

output "ec2_instance_id" {
  description = "EC2 instance ID — use with SSM Session Manager to open a shell"
  value       = aws_instance.main.id
}

# ─────────────────────────────────────────────────────────────────────────────
# SSM Access (no SSH required)
# ─────────────────────────────────────────────────────────────────────────────

output "ssm_session_command" {
  description = "Copy-paste command to open an SSM shell session on the k3s node"
  value       = "aws ssm start-session --target ${aws_instance.main.id} --region ${var.aws_region}"
}

# ─────────────────────────────────────────────────────────────────────────────
# IAM
# ─────────────────────────────────────────────────────────────────────────────

output "github_actions_role_arn" {
  description = "IAM Role ARN for GitHub Actions OIDC — set as AWS_ROLE_TO_ASSUME in workflow secrets"
  value       = aws_iam_role.github_actions.arn
}

output "ec2_instance_profile_name" {
  description = "EC2 instance profile name — used by Terraform to attach the role to new instances"
  value       = aws_iam_instance_profile.ec2.name
}

output "mcp_agent_role_arn" {
  description = "Read-only IAM role ARN for the MCP diagnostic agent"
  value       = aws_iam_role.mcp_agent.arn
}

# ─────────────────────────────────────────────────────────────────────────────
# URLs
# ─────────────────────────────────────────────────────────────────────────────

output "app_url" {
  description = "Public HTTPS URL for the Meridian link shortener"
  value       = "https://${var.app_subdomain}.${var.domain_name}"
}

output "grafana_url" {
  description = "Grafana dashboard URL (protected by Cloudflare Access)"
  value       = "https://grafana.${var.domain_name}"
}

# ─────────────────────────────────────────────────────────────────────────────
# State backend (useful to confirm which bucket/table Terraform is using)
# ─────────────────────────────────────────────────────────────────────────────

output "tfstate_bucket" {
  description = "S3 bucket storing Terraform remote state"
  value       = aws_s3_bucket.tfstate.bucket
}

output "tfstate_lock_table" {
  description = "DynamoDB table used for Terraform state locking"
  value       = aws_dynamodb_table.tflock.name
}

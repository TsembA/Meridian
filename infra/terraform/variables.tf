# variables.tf — All input variables for the Meridian Platform infrastructure.
# No sensitive defaults — secrets are read from SSM Parameter Store at runtime.
# Override with terraform.tfvars (gitignored) or environment variables (TF_VAR_*).

variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-west-1"
}

variable "project_name" {
  description = "Project name used as a prefix/tag for all resource names"
  type        = string
  default     = "meridian"
}

variable "environment" {
  description = "Deployment environment label (dev | staging | prod)"
  type        = string
  default     = "prod"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

# ─── Networking ───────────────────────────────────────────────────────────────

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidr" {
  description = "CIDR block for the public subnet"
  type        = string
  default     = "10.0.1.0/24"
}

variable "availability_zone" {
  description = "Availability zone — us-west-1 has us-west-1b and us-west-1c (us-west-1a was deprecated)"
  type        = string
  default     = "us-west-1b"
}

# ─── Compute ─────────────────────────────────────────────────────────────────

variable "ec2_instance_type" {
  description = "EC2 instance type — t3.medium required for k3s + kube-prometheus-stack"
  type        = string
  default     = "t3.medium"
}

variable "ec2_ami_id" {
  description = "Ubuntu 22.04 LTS AMI for us-west-1 (ami-0d9858aa3c6322f73)"
  type        = string
  default     = "ami-0d9858aa3c6322f73"
}

variable "ssh_public_key" {
  description = "SSH public key for EC2 key pair. Used only for emergency break-glass access. Normal access is via SSM Session Manager."
  type        = string
  sensitive   = true
}

# ─── GitHub OIDC ─────────────────────────────────────────────────────────────

variable "github_org" {
  description = "GitHub organization or username — used to scope the OIDC trust policy"
  type        = string
}

variable "github_repo" {
  description = "GitHub repository name (without org prefix) — case-sensitive, must match GitHub exactly"
  type        = string
  default     = "Meridian"
}

# ─── Cloudflare ──────────────────────────────────────────────────────────────

variable "cloudflare_zone_id" {
  description = "Cloudflare zone ID for the target domain"
  type        = string
  sensitive   = true
}

variable "cloudflare_api_token" {
  description = "Cloudflare API token with DNS:Edit and Zone:Read permissions"
  type        = string
  sensitive   = true
}

variable "domain_name" {
  description = "Root domain name managed in Cloudflare (e.g. example.com)"
  type        = string
}

variable "app_subdomain" {
  description = "Subdomain for the Meridian app (e.g. 'app' → app.meridiancore.dev)"
  type        = string
  default     = "app"
}

# ─── State backend ───────────────────────────────────────────────────────────

variable "state_bucket_name" {
  description = "S3 bucket name for Terraform remote state"
  type        = string
  default     = "meridian-platform-tfstate"
}

variable "lock_table_name" {
  description = "DynamoDB table name for Terraform state locking"
  type        = string
  default     = "meridian-platform-tflock"
}

# ─── Tags ────────────────────────────────────────────────────────────────────

variable "tags" {
  description = "Common tags applied to all taggable AWS resources"
  type        = map(string)
  default = {
    Project     = "meridian"
    ManagedBy   = "terraform"
    Environment = "prod"
    Owner       = "platform-team"
  }
}

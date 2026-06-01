# ssm.tf — SSM Parameter Store entries managed by Terraform.
# Placeholder values are written here so the parameter paths exist in AWS from day one.
# Actual secrets are injected via `aws ssm put-parameter --overwrite` in the runbook
# or during first-deploy; Terraform will never overwrite them after initial creation
# thanks to `lifecycle { ignore_changes = [value] }`.
#
# Naming convention: /${var.project_name}/<service>/<key>
# All SecureString params use the AWS-managed SSM key (no extra cost, still encrypted).

# ─────────────────────────────────────────────────────────────────────────────
# Database (PostgreSQL)
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_ssm_parameter" "db_host" {
  name        = "/${var.project_name}/db/host"
  description = "PostgreSQL service hostname inside the cluster"
  type        = "String"
  # Helm release name is <project_name>-app; Bitnami PostgreSQL subchart appends its own name.
  # Full pattern: <release>-postgresql.<namespace>.svc.cluster.local
  value = "${var.project_name}-app-postgresql.${var.project_name}.svc.cluster.local"

  tags = { Name = "${var.project_name}-db-host" }
}

resource "aws_ssm_parameter" "db_port" {
  name        = "/${var.project_name}/db/port"
  description = "PostgreSQL port"
  type        = "String"
  value       = "5432"

  tags = { Name = "${var.project_name}-db-port" }
}

resource "aws_ssm_parameter" "db_name" {
  name        = "/${var.project_name}/db/name"
  description = "PostgreSQL database name"
  type        = "String"
  value       = var.project_name

  tags = { Name = "${var.project_name}-db-name" }
}

resource "aws_ssm_parameter" "db_user" {
  name        = "/${var.project_name}/db/user"
  description = "PostgreSQL application user"
  type        = "String"
  value       = "${var.project_name}_app"

  tags = { Name = "${var.project_name}-db-user" }
}

resource "aws_ssm_parameter" "db_password" {
  name        = "/${var.project_name}/db/password"
  description = "PostgreSQL application user password — set via runbook, never in code"
  type        = "SecureString"
  value       = "REPLACE_ME_VIA_RUNBOOK" # Overwrite: aws ssm put-parameter --name /meridian/db/password --value <pw> --type SecureString --overwrite

  lifecycle {
    ignore_changes = [value] # Terraform writes the placeholder once; humans/CI own updates
  }

  tags = {
    Name   = "${var.project_name}-db-password"
    Secret = "true"
  }
}

# ─────────────────────────────────────────────────────────────────────────────
# Redis
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_ssm_parameter" "redis_host" {
  name        = "/${var.project_name}/redis/host"
  description = "Redis service hostname inside the cluster"
  type        = "String"
  # Bitnami Redis standalone appends -redis-master to the release name.
  value = "${var.project_name}-app-redis-master.${var.project_name}.svc.cluster.local"

  tags = { Name = "${var.project_name}-redis-host" }
}

resource "aws_ssm_parameter" "redis_port" {
  name        = "/${var.project_name}/redis/port"
  description = "Redis port"
  type        = "String"
  value       = "6379"

  tags = { Name = "${var.project_name}-redis-port" }
}

# ─────────────────────────────────────────────────────────────────────────────
# Application
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_ssm_parameter" "app_secret_key" {
  name        = "/${var.project_name}/app/secret-key"
  description = "Application-level secret key for signing/session tokens"
  type        = "SecureString"
  value       = "REPLACE_ME_VIA_RUNBOOK"

  lifecycle {
    ignore_changes = [value]
  }

  tags = {
    Name   = "${var.project_name}-app-secret-key"
    Secret = "true"
  }
}

resource "aws_ssm_parameter" "app_base_url" {
  name        = "/${var.project_name}/app/base-url"
  description = "Public base URL of the application (used in short URL generation)"
  type        = "String"
  value       = "https://${var.app_subdomain}.${var.domain_name}"

  tags = { Name = "${var.project_name}-app-base-url" }
}

# ─────────────────────────────────────────────────────────────────────────────
# Grafana
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_ssm_parameter" "grafana_admin_password" {
  name        = "/${var.project_name}/grafana/admin-password"
  description = "Grafana admin password — Helm chart reads this during install"
  type        = "SecureString"
  value       = "REPLACE_ME_VIA_RUNBOOK"

  lifecycle {
    ignore_changes = [value]
  }

  tags = {
    Name   = "${var.project_name}-grafana-admin-password"
    Secret = "true"
  }
}

# ─────────────────────────────────────────────────────────────────────────────
# GitHub (MCP agent reads deployment history via read-only PAT)
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_ssm_parameter" "github_token" {
  name        = "/${var.project_name}/github/token"
  description = "GitHub read-only PAT for MCP agent deployment history queries — needs repo:read scope only"
  type        = "SecureString"
  value       = "REPLACE_ME_VIA_RUNBOOK"

  lifecycle {
    ignore_changes = [value]
  }

  tags = {
    Name   = "${var.project_name}-github-token"
    Secret = "true"
  }
}

resource "aws_ssm_parameter" "github_repo_owner" {
  name        = "/${var.project_name}/github/repo-owner"
  description = "GitHub org or username that owns the repository"
  type        = "String"
  value       = var.github_org

  tags = { Name = "${var.project_name}-github-repo-owner" }
}

resource "aws_ssm_parameter" "github_repo_name" {
  name        = "/${var.project_name}/github/repo-name"
  description = "GitHub repository name"
  type        = "String"
  value       = var.github_repo

  tags = { Name = "${var.project_name}-github-repo-name" }
}

# ─────────────────────────────────────────────────────────────────────────────
# Cloudflare (provider reads this via data source — see cloudflare.tf)
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_ssm_parameter" "cloudflare_api_token" {
  name        = "/${var.project_name}/cloudflare/api-token"
  description = "Cloudflare API token (DNS:Edit + Zone:Read) — used by Terraform Cloudflare provider"
  type        = "SecureString"
  value       = "REPLACE_ME_VIA_RUNBOOK"

  lifecycle {
    ignore_changes = [value]
  }

  tags = {
    Name   = "${var.project_name}-cloudflare-api-token"
    Secret = "true"
  }
}

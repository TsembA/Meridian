# iam.tf — IAM roles for EC2 instance profile and GitHub Actions OIDC federation.
# Zero static credentials: EC2 uses instance profile; CI/CD uses OIDC token exchange.
# MCP agent role has an explicit Deny on all write actions (belt-and-suspenders).

# ─────────────────────────────────────────────────────────────────────────────
# EC2 Instance Profile
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_iam_role" "ec2" {
  name = "${var.project_name}-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })

  tags = { Name = "${var.project_name}-ec2-role" }
}

# SSM Session Manager — replaces SSH entirely (no port 22 needed)
resource "aws_iam_role_policy_attachment" "ec2_ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Read SSM parameters — app reads DB/Redis creds, API tokens at pod startup
resource "aws_iam_role_policy" "ec2_ssm_params" {
  name = "${var.project_name}-ec2-ssm-params"
  role = aws_iam_role.ec2.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "ReadMeridianSSMParams"
      Effect = "Allow"
      Action = [
        "ssm:GetParameter",
        "ssm:GetParameters",
        "ssm:GetParametersByPath"
      ]
      # Scoped to this project's SSM prefix only
      Resource = "arn:aws:ssm:${var.aws_region}:*:parameter/${var.project_name}/*"
    }]
  })
}

# CloudWatch Agent — ships k3s and app metrics/logs
resource "aws_iam_role_policy_attachment" "ec2_cloudwatch" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

# Allow EC2 to pull from GHCR via ECR if images are mirrored there
resource "aws_iam_role_policy_attachment" "ec2_ecr" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${var.project_name}-ec2-profile"
  role = aws_iam_role.ec2.name
}

# ─────────────────────────────────────────────────────────────────────────────
# GitHub Actions OIDC Provider
# Allows GitHub Actions to authenticate with AWS without static credentials.
# The OIDC token is issued by GitHub and exchanged for a short-lived AWS role.
# ─────────────────────────────────────────────────────────────────────────────

data "tls_certificate" "github_oidc" {
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github_oidc.certificates[0].sha1_fingerprint]

  tags = { Name = "${var.project_name}-github-oidc" }
}

# Role assumed by GitHub Actions — scoped to this specific repository only
resource "aws_iam_role" "github_actions" {
  name = "${var.project_name}-github-actions-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          # Restrict to exact repo — prevents lateral movement from other repos
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_org}/${var.github_repo}:*"
        }
      }
    }]
  })

  tags = { Name = "${var.project_name}-github-actions-role" }
}

# Terraform plan + apply permissions for CI/CD
resource "aws_iam_role_policy" "github_actions_terraform" {
  name = "${var.project_name}-github-terraform"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "TerraformInfraOps"
        Effect = "Allow"
        Action = [
          "ec2:*", "elasticloadbalancing:*",
          "iam:*",
          "s3:*",
          "dynamodb:*",
          "ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath",
          "ssm:PutParameter", "ssm:AddTagsToResource",
          "logs:*",
          "cloudwatch:*",
          "sts:GetCallerIdentity",
          "route53:*"
        ]
        Resource = "*"
      }
    ]
  })
}

# ─────────────────────────────────────────────────────────────────────────────
# MCP Agent IAM Role — read-only with explicit Deny on all writes
# The Deny statement ensures read-only even if someone widens the Allow accidentally.
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_iam_role" "mcp_agent" {
  name = "${var.project_name}-mcp-agent-role"

  # MCP pod runs on k3s (on EC2) — assumes this role via EC2 instance profile chaining
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = aws_iam_role.ec2.arn }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Name = "${var.project_name}-mcp-agent-role" }
}

resource "aws_iam_role_policy" "mcp_agent_readonly" {
  name = "${var.project_name}-mcp-readonly"
  role = aws_iam_role.mcp_agent.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowReadOnlyOps"
        Effect = "Allow"
        Action = [
          "cloudwatch:GetMetricStatistics",
          "cloudwatch:ListMetrics",
          "cloudwatch:GetMetricData",
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams",
          "logs:GetLogEvents",
          "ssm:GetParameter",
          "ssm:GetParameters",
          "ssm:GetParametersByPath",
          "ec2:DescribeInstances",
          "ec2:DescribeInstanceStatus",
          "sts:GetCallerIdentity"
        ]
        Resource = "*"
      },
      {
        # Belt-and-suspenders: deny everything not in the allowlist above.
        # AWS Deny always wins over Allow — this can't be overridden by accident.
        Sid    = "DenyAllMutations"
        Effect = "Deny"
        NotAction = [
          "cloudwatch:GetMetricStatistics",
          "cloudwatch:ListMetrics",
          "cloudwatch:GetMetricData",
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams",
          "logs:GetLogEvents",
          "ssm:GetParameter",
          "ssm:GetParameters",
          "ssm:GetParametersByPath",
          "ec2:DescribeInstances",
          "ec2:DescribeInstanceStatus",
          "sts:AssumeRole",
          "sts:GetCallerIdentity"
        ]
        Resource = "*"
      }
    ]
  })
}

# ec2.tf — EC2 instance running k3s, hardened security group, Elastic IP.
# Port 22 is NEVER opened. All shell access via AWS SSM Session Manager.
# IMDSv2 enforced to prevent SSRF attacks targeting the instance metadata service.

resource "aws_key_pair" "ec2" {
  key_name   = "${var.project_name}-key"
  public_key = var.ssh_public_key

  tags = {
    Name    = "${var.project_name}-key-pair"
    Purpose = "break-glass-emergency-only"
  }
}

# ─────────────────────────────────────────────────────────────────────────────
# Security Group — least-privilege inbound rules
# Port 22 intentionally absent — SSM Session Manager handles all shell access
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_security_group" "ec2" {
  name        = "${var.project_name}-ec2-sg"
  description = "Meridian EC2 security group — no SSH, Cloudflare-proxied HTTP/S only"
  vpc_id      = aws_vpc.main.id

  # HTTP — Cloudflare proxies all traffic; WAF rules on CF side filter bad actors
  ingress {
    description = "HTTP ingress (Cloudflare proxy)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # HTTPS
  ingress {
    description = "HTTPS ingress (Cloudflare proxy)"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # k3s NodePort range — NGINX ingress controller uses 30080/30443
  ingress {
    description = "k3s NodePort services (NGINX ingress)"
    from_port   = 30000
    to_port     = 32767
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # All egress allowed — EC2 needs to reach AWS APIs, GHCR, Helm repos
  egress {
    description = "All outbound (AWS APIs, GHCR, Helm repos, OS updates)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-ec2-sg"
  }
}

# ─────────────────────────────────────────────────────────────────────────────
# EC2 Instance
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_instance" "main" {
  ami                    = var.ec2_ami_id
  instance_type          = var.ec2_instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.ec2.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name
  key_name               = aws_key_pair.ec2.key_name

  # k3s bootstrap — runs once on first launch
  user_data = file("${path.module}/../scripts/cloud-init.yaml")

  # Encrypted EBS root volume
  root_block_device {
    volume_type           = "gp3"
    volume_size           = 20    # GB — sufficient for k3s + container images
    encrypted             = true
    delete_on_termination = true

    tags = {
      Name = "${var.project_name}-root-volume"
    }
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required" # IMDSv2 — mitigates SSRF → IMDS attacks
    http_put_response_hop_limit = 1          # Prevent containers from reaching IMDS
  }

  # Replace instance rather than update in place when user_data changes
  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Name = "${var.project_name}-ec2"
    Role = "k3s-single-node"
  }
}

# Elastic IP — stable public IP so Cloudflare DNS record doesn't break on reboot
resource "aws_eip" "main" {
  instance = aws_instance.main.id
  domain   = "vpc"

  # Ensure IGW exists before associating EIP
  depends_on = [aws_internet_gateway.main]

  tags = {
    Name = "${var.project_name}-eip"
  }
}

# cloudflare.tf — Cloudflare DNS records and zone security settings for the Meridian platform.
# Proxied mode is ON for all records — Cloudflare acts as CDN, WAF, and DDoS shield.
# The EC2 public IP is never exposed directly; all traffic goes through Cloudflare's edge.

# ─────────────────────────────────────────────────────────────────────────────
# DNS Records
# ─────────────────────────────────────────────────────────────────────────────

# Application root — short URL redirects and API endpoints
resource "cloudflare_record" "app" {
  zone_id = var.cloudflare_zone_id
  name    = var.app_subdomain      # e.g. "app" → app.meridiancore.dev
  content = aws_eip.main.public_ip # `content` replaces deprecated `value` in CF provider v4+
  type    = "A"
  proxied = true # Cloudflare proxy on — hides origin IP
  ttl     = 1    # TTL is managed by Cloudflare when proxied

  comment = "Meridian app - k3s NodePort via Cloudflare proxy"
}

# Grafana — monitoring dashboard (protected by Cloudflare Access free tier)
resource "cloudflare_record" "grafana" {
  zone_id = var.cloudflare_zone_id
  name    = "grafana"
  content = aws_eip.main.public_ip
  type    = "A"
  proxied = true
  ttl     = 1

  comment = "Grafana dashboard - Cloudflare Access policy protects this subdomain"
}

# ─────────────────────────────────────────────────────────────────────────────
# Cloudflare Origin CA Certificate
#
# Cloudflare signs this cert — it is trusted by CF edge → origin connections.
# Required to switch ssl from "flexible" to "strict" (CF validates origin cert).
# The private key is stored in SSM; CI reads it at deploy time to create the
# k8s TLS secret — the key never leaves AWS.
#
# PREREQUISITE: var.cloudflare_api_token must have the
# "Zone:SSL and Certificates:Edit" permission in addition to DNS:Edit.
# Update the token in the Cloudflare dashboard before running terraform apply.
# ─────────────────────────────────────────────────────────────────────────────

resource "tls_private_key" "origin" {
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "tls_cert_request" "origin" {
  private_key_pem = tls_private_key.origin.private_key_pem

  subject {
    common_name  = var.domain_name
    organization = "Meridian"
  }

  dns_names = [
    var.domain_name,
    "*.${var.domain_name}",
  ]
}

resource "cloudflare_origin_ca_certificate" "main" {
  csr                = tls_cert_request.origin.cert_request_pem
  hostnames          = [var.domain_name, "*.${var.domain_name}"]
  request_type       = "origin-rsa"
  requested_validity = 5475 # 15 years — Cloudflare Origin CA maximum
}

# Cert and key stored in SSM — CI reads them at deploy time to create the
# meridian-tls k8s Secret. Terraform state in S3 is encrypted (AES256).
resource "aws_ssm_parameter" "tls_cert" {
  name        = "/meridian/tls/cert"
  type        = "SecureString"
  value       = cloudflare_origin_ca_certificate.main.certificate
  description = "Cloudflare Origin CA certificate for ${var.domain_name}"

  tags = {
    Name    = "meridian-tls-cert"
    Purpose = "cloudflare-origin-cert"
  }
}

resource "aws_ssm_parameter" "tls_key" {
  name        = "/meridian/tls/key"
  type        = "SecureString"
  value       = tls_private_key.origin.private_key_pem
  description = "Private key for Cloudflare Origin CA certificate — treat as secret"

  tags = {
    Name    = "meridian-tls-key"
    Purpose = "cloudflare-origin-cert"
  }
}

# ─────────────────────────────────────────────────────────────────────────────
# Zone Security Settings
#
# Note: plan-restricted or API-immutable fields (http2, polish, mirage,
# image_resizing) must be omitted entirely. Cloudflare's API rejects any write
# to those fields on the Free plan, even when the value matches the current
# default, with "cannot be set as it is read only".
# ─────────────────────────────────────────────────────────────────────────────

resource "cloudflare_zone_settings_override" "meridian" {
  zone_id = var.cloudflare_zone_id

  settings {
    # TLS hardening — reject TLS 1.0/1.1 clients
    min_tls_version = "1.2"
    tls_1_3         = "on"
    ssl             = "strict" # CF validates origin cert — requires Cloudflare Origin CA cert installed as meridian-tls k8s Secret.

    # Force HTTPS at the edge — redirect all plain-text HTTP
    automatic_https_rewrites = "on"

    # Browser integrity check — blocks headless/scriptless requests with bad reputations
    browser_check = "on"

    # Security level: aggressively challenge visitors with poor IP reputation
    security_level = "high"

    # HSTS: instruct browsers never to connect to origin over HTTP
    security_header {
      enabled            = true
      include_subdomains = true
      max_age            = 31536000 # 1 year
      nosniff            = true
    }
  }
}

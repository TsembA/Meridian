# cloudflare.tf — Cloudflare DNS records and zone security settings for the Meridian platform.
# Proxied mode is ON for all records — Cloudflare acts as CDN, WAF, and DDoS shield.
# The EC2 public IP is never exposed directly; all traffic goes through Cloudflare's edge.

# ─────────────────────────────────────────────────────────────────────────────
# DNS Records
# ─────────────────────────────────────────────────────────────────────────────

# Application root — short URL redirects and API endpoints
resource "cloudflare_record" "app" {
  zone_id = var.cloudflare_zone_id
  name    = var.app_subdomain      # e.g. "app" → app.example.com
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
    ssl             = "full" # Use "strict" once an origin cert is installed

    # Force HTTPS at the edge — redirect all plain-text HTTP
    automatic_https_rewrites = "on"

    # Browser integrity check — blocks headless/scriptless requests with bad reputations
    browser_check = "on"

    # Security level: challenge visitors with poor IP reputation
    security_level = "medium"

    # HSTS: instruct browsers never to connect to origin over HTTP
    security_header {
      enabled            = true
      include_subdomains = true
      max_age            = 31536000 # 1 year
      nosniff            = true
    }
  }
}

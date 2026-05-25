# Meridian Platform

> A cost-optimised, portfolio-grade DevOps platform on AWS — FastAPI microservice,
> full observability stack, GitOps CI/CD, and an AI-powered MCP diagnostic agent.
> Zero static credentials. Zero open SSH ports. Everything in SSM.

---

## Architecture

```mermaid
flowchart TB
    subgraph Internet
        Browser["👤 User / Browser"]
        CF["☁️ Cloudflare<br/>(CDN + WAF + DDoS)"]
    end

    subgraph AWS["AWS (us-west-1)"]
        EIP["Elastic IP"]

        subgraph EC2["EC2 t3.micro"]
            subgraph k3s_cluster["k3s Cluster"]
                NGINX["NGINX Ingress<br/>:30080 / :30443"]

                subgraph meridian["namespace: meridian"]
                    APP["🐍 FastAPI App<br/>meridian-app"]
                    PG["🐘 PostgreSQL"]
                    RD["⚡ Redis"]
                    MCP["🤖 MCP Agent<br/>meridian-mcp<br/>(ClusterIP only)"]
                end

                subgraph monitoring["namespace: monitoring"]
                    PROM["📊 Prometheus"]
                    GRAF["📈 Grafana"]
                    ALERT["🔔 Alertmanager"]
                end

                APP -->|reads creds via boto3| SSM
                APP -->|SQL| PG
                APP -->|cache| RD
                MCP -->|k8s API| k3s_cluster
                MCP -->|PromQL| PROM
                MCP -->|REST| ALERT
                PROM -->|scrape :8000/metrics| APP
                PROM -->|scrape :8080/metrics| MCP
            end
        end

        SSM["🔐 SSM Parameter Store<br/>/meridian/*"]
        S3["🪣 S3<br/>Terraform State"]
        DDB["🔒 DynamoDB<br/>State Lock"]
        IAM["🛡️ IAM<br/>OIDC Provider"]
    end

    subgraph GitHub["GitHub"]
        GHA["⚙️ GitHub Actions<br/>(OIDC — no static keys)"]
        GHCR["📦 GHCR<br/>Container Registry"]
    end

    Browser --> CF --> EIP --> NGINX --> APP
    GHA -->|OIDC token| IAM
    GHA -->|terraform apply| S3
    GHA -->|helm upgrade| EC2
    GHA -->|docker push| GHCR
    EC2 -->|pull images| GHCR
    GRAF -->|query| PROM
```

---

## Project Structure

```
meridian/
├── infra/
│   ├── terraform/          # Complete AWS infrastructure (VPC, EC2, IAM, SSM, Cloudflare)
│   └── scripts/
│       ├── bootstrap.sh    # One-time state backend creation
│       └── cloud-init.yaml # k3s bootstrap on first EC2 boot
├── k8s/
│   ├── charts/
│   │   ├── nexus-app/      # FastAPI Helm chart (+ PostgreSQL + Redis dependencies)
│   │   └── nexus-mcp/      # MCP agent Helm chart
│   ├── manifests/
│   │   ├── network-policies/  # Default-deny + explicit allow rules
│   │   └── rbac/              # Least-privilege service accounts
│   └── monitoring/
│       ├── dashboards/     # Grafana dashboard JSON (pre-provisioned)
│       └── alerts/         # PrometheusRule CRD (pod health, error rate, latency)
├── app/
│   ├── src/                # FastAPI application (main, config, models, db, cache, logger)
│   ├── tests/              # Unit tests (mocked SSM/DB/Redis)
│   ├── Dockerfile          # Multi-stage build, non-root user
│   └── requirements.txt    # Pinned versions
├── mcp-agent/
│   ├── src/                # MCP server (tools, audit logger, config)
│   ├── tests/              # Unit tests (mocked k8s/Prometheus/GitHub)
│   ├── Dockerfile          # Multi-stage build, non-root user (UID 1001)
│   └── requirements.txt
└── .github/
    └── workflows/
        ├── terraform.yml   # IaC pipeline (plan on PR, apply on main)
        ├── deploy.yml      # App pipeline (build → Trivy → Helm upgrade)
        └── security.yml    # Security gates (Trivy + tfsec + Bandit + pytest)
```

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Terraform | ≥ 1.6.0 | Infrastructure provisioning |
| AWS CLI | v2 | SSM Session Manager, parameter management |
| Helm | 3.14.x | Kubernetes application deployment |
| kubectl | 1.28.x | Cluster management |
| Docker | 24.x | Image building |
| Python | 3.12 | Application and MCP agent |

**AWS permissions required for the deploying IAM user/role:**
- `ec2:*`, `iam:*`, `s3:*`, `dynamodb:*`, `ssm:*` (scoped to this project's resources)

---

## First-Time Setup

### 1 — Bootstrap Terraform State Backend

```bash
chmod +x infra/scripts/bootstrap.sh
AWS_REGION=us-west-1 ./infra/scripts/bootstrap.sh
```

### 2 — Populate SSM Secrets

All secrets must be set before `terraform apply` or Helm installs run:

```bash
# Database password
aws ssm put-parameter \
  --name "/meridian/db/password" \
  --value "$(openssl rand -base64 32)" \
  --type SecureString \
  --overwrite \
  --region us-west-1

# Grafana admin password
aws ssm put-parameter \
  --name "/meridian/grafana/admin-password" \
  --value "$(openssl rand -base64 24)" \
  --type SecureString --overwrite --region us-west-1

# Application secret key
aws ssm put-parameter \
  --name "/meridian/app/secret-key" \
  --value "$(openssl rand -hex 32)" \
  --type SecureString --overwrite --region us-west-1

# GitHub read-only PAT (repo:read scope only)
aws ssm put-parameter \
  --name "/meridian/github/token" \
  --value "ghp_YOUR_TOKEN_HERE" \
  --type SecureString --overwrite --region us-west-1

# Cloudflare API token (DNS:Edit + Zone:Read)
aws ssm put-parameter \
  --name "/meridian/cloudflare/api-token" \
  --value "YOUR_CF_TOKEN" \
  --type SecureString --overwrite --region us-west-1
```

### 3 — Configure GitHub Actions Secrets

In your repository Settings → Secrets and variables → Actions:

| Secret | Value |
|--------|-------|
| `AWS_ROLE_TO_ASSUME` | Output of `terraform output github_actions_role_arn` |
| `AWS_REGION` | `us-west-1` |
| `CF_ZONE_ID` | Your Cloudflare zone ID |
| `CF_API_TOKEN` | Your Cloudflare API token |
| `DOMAIN_NAME` | Your domain (e.g. `example.com`) |
| `APP_HOSTNAME` | `app.example.com` |
| `EC2_SSH_PUBLIC_KEY` | Break-glass SSH public key (for the key pair — not used for normal access) |

### 4 — Terraform Apply

```bash
cd infra/terraform
terraform init
terraform plan -var="github_org=YOUR_GH_ORG" \
               -var="cloudflare_zone_id=YOUR_CF_ZONE_ID" \
               -var="cloudflare_api_token=$(aws ssm get-parameter --name /meridian/cloudflare/api-token --with-decryption --query Parameter.Value --output text)" \
               -var="domain_name=example.com" \
               -var="ssh_public_key=$(cat ~/.ssh/id_ed25519.pub)"
terraform apply
```

### 5 — Wait for Cloud-Init

The EC2 instance bootstraps k3s automatically. Check progress via SSM:

```bash
$(terraform output -raw ssm_session_command)
# Inside the session:
sudo journalctl -u cloud-final -f
sudo tail -f /var/log/cloud-init-output.log
```

### 6 — Deploy Applications

Push to `main` — GitHub Actions handles the rest. Or manually:

```bash
# Dependency update (first time only)
helm dependency update k8s/charts/nexus-app

# Install app
DB_PASS=$(aws ssm get-parameter --name /meridian/db/password --with-decryption --query Parameter.Value --output text --region us-west-1)
helm upgrade --install nexus-app k8s/charts/nexus-app \
  --namespace meridian --create-namespace \
  --set "image.repository=ghcr.io/YOUR_ORG/meridian-app" \
  --set "image.tag=latest" \
  --set "postgresql.auth.password=${DB_PASS}" \
  --set "ingress.hosts[0].host=app.example.com" \
  --wait

# Install MCP agent
helm upgrade --install nexus-mcp k8s/charts/nexus-mcp \
  --namespace meridian --create-namespace \
  --set "image.repository=ghcr.io/YOUR_ORG/meridian-mcp" \
  --set "image.tag=latest" \
  --wait

# Apply RBAC and NetworkPolicies
kubectl apply -f k8s/manifests/rbac/
kubectl apply -f k8s/manifests/network-policies/
```

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/shorten` | Create a short URL. Body: `{"url": "https://...", "custom_code": "optional"}` |
| `GET` | `/{code}` | Redirect to original URL (301) |
| `GET` | `/health` | Liveness check — returns DB and Redis status |
| `GET` | `/metrics` | Prometheus metrics endpoint |
| `GET` | `/stats` | Aggregated stats (total links, total clicks, top 10) |

---

## Observability

### Grafana

URL: `https://grafana.example.com`  
Protected by: Cloudflare Access (Google SSO — free tier)  
Default dashboard: **Meridian Platform** (auto-provisioned from `k8s/monitoring/dashboards/`)

Dashboard panels:
- Request rate by status code
- 5xx error rate (stat with threshold colours)
- p95 / p99 latency (stat with threshold colours)
- Pod readiness table
- Container restart count
- Node CPU / Memory / Disk gauges
- Network I/O
- Active alert table

### Alerts

| Alert | Condition | Severity |
|-------|-----------|----------|
| `MeridianPodNotReady` | Pod not Ready for 5min | critical |
| `MeridianPodCrashLooping` | >3 restarts in 15min | critical |
| `MeridianDeploymentUnavailable` | 0 available replicas | critical |
| `MeridianHighErrorRate` | 5xx rate >5% for 5min | warning |
| `MeridianCriticalErrorRate` | 5xx rate >20% for 2min | critical |
| `MeridianHighP95Latency` | p95 >1s for 5min | warning |
| `MeridianCriticalP99Latency` | p99 >5s for 5min | critical |
| `MeridianNodeHighCPU` | CPU >85% for 10min | warning |
| `MeridianNodeLowMemory` | <15% free RAM for 5min | critical |
| `MeridianDiskSpaceLow` | Disk >80% | warning |

---

## MCP Agent

The MCP agent runs inside the cluster (ClusterIP only) and exposes six diagnostic tools:

| Tool | Description |
|------|-------------|
| `get_pod_status` | List pods and readiness in a namespace |
| `get_recent_logs` | Tail N lines from a pod log |
| `get_active_alerts` | Firing Alertmanager alerts |
| `get_node_metrics` | CPU, memory, disk from Prometheus |
| `get_db_connectivity` | TCP ping to PostgreSQL (no credentials) |
| `get_deployment_history` | Recent GitHub Actions runs |

**Connecting Claude to the MCP agent** (via SSM port-forward):

```bash
# 1. Start an SSM session with port forwarding
INSTANCE_ID=$(terraform -chdir=infra/terraform output -raw ec2_instance_id)
aws ssm start-session \
  --target "$INSTANCE_ID" \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8080"],"localPortNumber":["8080"]}'

# 2. Add to ~/.claude/claude_desktop_config.json
{
  "mcpServers": {
    "meridian": {
      "url": "http://localhost:8080"
    }
  }
}
```

---

## Runbook

### Access the k3s node

```bash
# Get the SSM command from Terraform output
$(terraform -chdir=infra/terraform output -raw ssm_session_command)

# Inside the session — switch to root
sudo su -
kubectl get pods -A
```

### Tail application logs

```bash
kubectl logs -n meridian -l app.kubernetes.io/name=nexus-app -f --tail=100
```

### Restart the app pod

```bash
kubectl rollout restart deployment/nexus-app -n meridian
kubectl rollout status deployment/nexus-app -n meridian
```

### Update a secret in SSM

```bash
aws ssm put-parameter \
  --name "/meridian/db/password" \
  --value "new-password" \
  --type SecureString \
  --overwrite \
  --region us-west-1

# Restart the pod to pick up the new value (it's read at startup)
kubectl rollout restart deployment/nexus-app -n meridian
```

### Reclaim disk space (k3s container images)

```bash
# Inside SSM session
sudo k3s crictl rmi --prune
sudo docker system prune -f 2>/dev/null || true
df -h /
```

### Emergency: destroy and rebuild

```bash
# Destroy infrastructure (ALL DATA WILL BE LOST)
cd infra/terraform
terraform destroy -var="github_org=YOUR_ORG" ...

# Rebuild
terraform apply ...
# Wait for cloud-init, then redeploy via Helm
```

---

## Security Architecture

| Control | Implementation |
|---------|---------------|
| Zero static AWS credentials | OIDC (GitHub Actions) + instance profile (EC2) |
| No SSH port open | SSM Session Manager; SG has no port 22 rule |
| All secrets encrypted at rest | SSM SecureString (AES-256 managed key) |
| Secrets never in env vars | boto3 SSM fetch at pod startup |
| Container vulnerability scanning | Trivy on every build and PR |
| IaC security scanning | tfsec on every Terraform PR |
| Python SAST | Bandit on every PR |
| Network isolation | Default-deny NetworkPolicies; explicit allow rules only |
| Least-privilege RBAC | Dedicated SA per workload; MCP agent read-only ClusterRole |
| MCP agent hard limits | IAM `DenyAllMutations` + k8s read-only RBAC |
| IMDSv2 enforced | `http_tokens = "required"` on EC2 metadata endpoint |
| No shell=True anywhere | All subprocess replaced by k8s client / httpx |
| Supply chain pinning | All GitHub Actions pinned to SHA; all images pinned to version |
| WAF at edge | Cloudflare managed WAF + custom rules (scanner UA, path traversal) |
| Audit trail | Every MCP tool call logged to structured JSON + pod stdout |

---

## Cost Breakdown (Monthly Estimate)

| Resource | Spec | Est. Cost |
|----------|------|-----------|
| EC2 t3.micro | 1 instance, us-west-1 | ~$8.40 |
| EBS gp3 20 GiB | Root volume | ~$1.60 |
| Elastic IP (attached) | 1 EIP | $0.00 |
| S3 remote state | < 1 MB storage | ~$0.02 |
| DynamoDB on-demand | State lock (minimal ops) | ~$0.01 |
| SSM Parameter Store | Standard tier (<10k API calls/month) | $0.00 |
| VPC (no NAT GW) | IGW only | $0.00 |
| CloudWatch Logs | Flow logs 30-day retention | ~$0.50 |
| Cloudflare | Free tier (DNS, WAF, CDN) | $0.00 |
| GitHub Actions | Public repo or 2000 min/month free | $0.00 |
| GHCR | 500 MB free storage | $0.00 |
| **Total** | | **~$10.53/month** |

> **Note:** Costs are estimates based on AWS us-west-1 pricing as of 2024.
> The single biggest saving is the absence of a NAT Gateway (~$32/month) —
> achieved by placing EC2 in a public subnet with a hardened security group.

---

## Development

### Run tests locally

```bash
# App tests
cd app
pip install pytest pytest-asyncio pytest-mock -r requirements.txt
pytest tests/ -v --asyncio-mode=auto

# MCP agent tests
cd mcp-agent
pip install pytest pytest-asyncio pytest-mock -r requirements.txt
pytest tests/ -v --asyncio-mode=auto
```

### Run the app locally (mocked AWS)

```bash
cd app
# Set fake SSM values via env (dev only — never in production)
export AWS_DEFAULT_REGION=us-west-1
# Use moto or localstack for SSM, or patch get_settings() in tests
uvicorn src.main:app --reload --port 8000
```

---

## Licence

MIT — see [LICENSE](LICENSE).

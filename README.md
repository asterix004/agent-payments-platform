# Agent Payments Platform

A reference platform for an **AI-agent payments API**: agents prove who they are with signed *Know Your Agent* (KYA) tokens, move money through an **idempotent, double-entry ledger**, and the service ships through a **GitOps pipeline with a signed, scanned supply chain** onto **EKS**, with **SLO burn-rate alerting** and a runbook for every page.

The goal is the platform around a payments service, built the way a regulated fintech would expect: no long-lived credentials anywhere, every deploy traceable to a commit and an image digest, and failure modes rehearsed, not hoped about.

```mermaid
flowchart LR
  dev[git push] --> GA["GitHub Actions<br/>test (Postgres) · gitleaks · helm/kubeconform"]
  GA --> IMG["build · Trivy · SBOM · provenance<br/>cosign keyless sign"]
  IMG --> GHCR[(GHCR image@digest)]
  IMG --> BUMP["commit digest to<br/>values-aws.yaml"]
  BUMP --> ARGO[Argo CD]
  ARGO --> EKS
  subgraph EKS["EKS (private subnets)"]
    API["payments API<br/>HPA · PDB · NetworkPolicy"]
    ESO["External Secrets<br/>(Pod Identity)"]
    PROM["Prometheus · Alertmanager · Grafana<br/>SLO burn-rate rules"]
  end
  ESO -->|GetSecretValue| SM[(Secrets Manager)]
  API -->|TLS| RDS[(RDS Postgres<br/>managed master secret)]
  PROM -->|scrape /metrics| API
  GA -. "OIDC, read-only role" .-> AWS[terraform plan]
```

## What it demonstrates

| Concern | How |
|---|---|
| **Money correctness** | Integer minor units only; double-entry ledger where every transaction's rows sum to zero; account rows locked in a stable order so concurrent payments cannot overdraw or deadlock |
| **Exactly-once payments** | `Idempotency-Key` required; key, request hash and response stored in the *same* DB transaction as the ledger rows; retries replay the original response, and a reused key with a different body is rejected |
| **Agent identity** | ES256/RS256 JWTs from a KYA issuer; the API holds only the public key; scopes and a per-payment spend cap come from the token |
| **No static credentials** | GitHub → AWS via OIDC (read-only plan role); pods → Secrets Manager via EKS Pod Identity; RDS password generated and rotated by AWS, never in Terraform state |
| **Supply chain** | Trivy gate on fixable HIGH/CRITICAL, SPDX SBOM, build provenance, keyless cosign signature, deploy by immutable digest |
| **GitOps** | Argo CD app-of-apps with sync waves (operators → cluster config → workloads); CI promotes by committing the digest |
| **Reliability** | 99.9% availability and 99% < 250 ms SLOs; multi-window multi-burn-rate alerts; runbook link on every alert; HPA, PDB, zone spread, read-only root FS, non-root, dropped capabilities |
| **Rehearsed failure** | `make chaos` takes the database away under load and walks through detection and recovery |

## Run it locally (kind, no cloud cost)

Prerequisites: Docker, `kind`, `kubectl`, `helm`, Python 3.12.

```bash
make venv && make test          # 19 API tests on SQLite
make local-up                   # kind + Prometheus/Grafana + Postgres + payments (2 replicas)
make port-forward               # terminal 1: http://localhost:8080/docs
make loadgen RPS=20             # terminal 2: steady agent traffic
make grafana                    # terminal 3: dashboards
make chaos                      # terminal 4: database outage drill
make local-down
```

Race-condition tests need real row locks: `TEST_DATABASE_URL=postgresql+psycopg://... make test` (CI always runs them).

## Deploy to AWS

```bash
cp infra/aws/terraform.tfvars.example infra/aws/terraform.tfvars   # your IP, repo, KYA public key
make aws-init && make aws-plan && make aws-up                      # VPC, EKS, RDS, IAM, secrets
make aws-kubeconfig
# put db_endpoint and db_master_secret_arn from `terraform output` into deploy/helm/payments/values-aws.yaml
# replace asterix004 in deploy/argocd/*.yaml, commit, push
make argocd                                                        # Argo CD takes over from Git
make aws-down                                                      # tear down
```

Cost shape (Spot nodes, single NAT, `db.t4g.micro`, no Multi-AZ) and the production deltas are in [ADR 0004](docs/adr/0004-aws-cost-shape.md).

## API

| Method | Path | Scope | Notes |
|---|---|---|---|
| POST | `/v1/accounts` | `accounts:write` | Creates an account owned by the calling agent |
| GET | `/v1/accounts/{id}` | — | Owner only; balance is derived from the ledger |
| POST | `/v1/deposits` | `treasury:deposit` | Sandbox top-up from the treasury account |
| POST | `/v1/payments` | `payments:write` | Requires `Idempotency-Key`; `Idempotent-Replayed: true` on replays |
| GET | `/healthz`, `/readyz`, `/metrics` | — | Readiness checks the database |

## Repository layout

```
app/                    FastAPI service: ledger, KYA auth, metrics, optional OpenTelemetry
tests/                  API, idempotency, auth and Postgres race-condition tests
deploy/helm/payments/   Chart: Deployment, HPA, PDB, NetworkPolicy, ServiceMonitor, SLO rules, ExternalSecret
deploy/argocd/          App-of-apps and platform applications
deploy/platform/        ClusterSecretStore
infra/aws/              Terraform: VPC, EKS (v21 module), RDS, Pod Identity, GitHub OIDC
local/                  kind config, local Postgres, Prometheus values
scripts/                Dev KYA issuer, load generator, chaos drill
docs/                   ADRs, SLOs, runbooks, PCI-DSS control mapping
```

## Scope note

This is a reference implementation, not a production payments system. It moves balances in a sandbox ledger; it does not connect to card networks, banks or stablecoin rails, and it handles no cardholder data. [docs/pci-dss-mapping.md](docs/pci-dss-mapping.md) shows which platform controls map to PCI DSS v4.0 requirements, as a design aid rather than a compliance claim.

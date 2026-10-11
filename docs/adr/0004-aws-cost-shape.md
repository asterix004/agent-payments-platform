# ADR 0004: AWS cost shape for a reference environment

**Status:** accepted for the demo; each row lists the production choice

| Area | Demo | Production | Why the demo choice is acceptable |
|---|---|---|---|
| Nodes | 2 × Spot (`t3.large`/`t3a.large`/`m5.large`) | On-demand baseline + Spot or Karpenter for burst | Stateless API with PDB and 2+ replicas tolerates Spot interruption |
| NAT | Single NAT gateway | One per AZ | An AZ outage only affects egress for the demo |
| Database | `db.t4g.micro`, single-AZ, 1-day backups, no deletion protection | Multi-AZ, PITR, deletion protection, final snapshot | Data is synthetic and the environment is disposable |
| EKS API | Public endpoint restricted to `admin_cidrs` | Private endpoint, access via VPN/SSM | Laptop access without a bastion |
| Terraform state | Local | S3 backend with lockfile and versioning | One operator; `plan` in CI needs remote state (see workflow) |
| Secrets | Secrets Manager + External Secrets | Same, plus rotation alarms | — |

The environment is created and destroyed per session (`make aws-up` / `make aws-down`); the hourly cost is dominated by the EKS control plane, the NAT gateway and the nodes.

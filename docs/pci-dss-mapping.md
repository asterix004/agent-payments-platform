# PCI DSS v4.0 control mapping (design aid)

This service handles no primary account numbers (PANs) or other cardholder data, so it is not itself in PCI scope. A payments company still runs its whole platform to these standards, and an assessor would ask about these controls. The table shows where each is implemented here, and what is left for production.

| Req. | Requirement (summary) | Implemented here | Production gap |
|---|---|---|---|
| 1 | Network security controls | Private subnets for nodes and RDS; DB security group allows only the EKS node SG; default-deny ingress NetworkPolicy; EKS API restricted to admin CIDRs | Private API endpoint; egress NetworkPolicy; WAF in front of ingress |
| 2 | Secure configurations | Non-root, read-only root FS, all capabilities dropped, seccomp `RuntimeDefault`, no service-account token mounted | Pod Security Admission `restricted` enforced on the namespace; CIS EKS benchmark scan |
| 3 | Protect stored account data | RDS storage encryption; no card data stored | KMS customer-managed keys; data retention policy |
| 4 | Encrypt transmission | `rds.force_ssl=1` and `sslmode=require` | TLS at ingress with managed certificates; mTLS in-cluster |
| 6 | Secure development | Tests in CI; Trivy gate; gitleaks; SBOM; signed images; dependency pins | SAST, DAST and a documented secure-review process for releases |
| 7 | Restrict access by need to know | Token scopes; agents spend only from their own accounts; CI role read-only | RBAC mapped to job roles; periodic access review |
| 8 | Identify and authenticate | Signed, short-lived agent tokens; no shared keys; OIDC for CI; Pod Identity for workloads | MFA and SSO for human access to AWS/Argo CD/Grafana |
| 10 | Log and monitor | Structured logs; metrics; SLO alerts; Argo CD sync history; Git as audit trail of changes | Centralised, tamper-evident log retention (≥ 12 months); CloudTrail and EKS audit logs to it |
| 11 | Test security regularly | Chaos drill; race-condition tests | Quarterly vulnerability scans; annual penetration test |
| 12 | Policies and incident response | Runbooks per alert; SLO-based paging | Formal IR plan, on-call rota, tabletop exercises |

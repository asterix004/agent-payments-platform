# Runbook: PaymentsNoReadyPods

**Impact:** full outage. Readiness checks the database, so every pod leaving the Service usually means the database is unreachable. Pods are left running (liveness is DB-independent) so they recover as soon as it returns.

## Diagnose
```bash
kubectl -n payments get pods
kubectl -n payments logs deploy/payments --tail=50 | grep -i readiness
kubectl -n payments get externalsecret payments-secrets -o jsonpath='{.status.conditions}'
```
| Finding | Action |
|---|---|
| RDS instance stopped, rebooting or failing over | AWS console → RDS events; wait for `available`, or restore from snapshot |
| Password rotated, secret not yet refreshed | `kubectl -n payments annotate externalsecret payments-secrets force-sync=$(date +%s) --overwrite`, then `kubectl -n payments rollout restart deploy/payments` |
| Security group or NetworkPolicy change | Check `aws_security_group.db` ingress from the node SG; check recent Git changes |
| Local drill (`make chaos`) | Expected; the script restores Postgres |

## Rehearsal
`make chaos` on kind reproduces this alert. Run it before an interview or after any change to probes or alert rules.

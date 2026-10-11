# Runbook: PaymentsErrorBudgetFastBurn / SlowBurn

**Impact:** agents receive 5xx on `POST /v1/payments`. Because every payment is idempotent, clients that retry with the same key are safe; money is never moved twice.

## 1. Confirm and scope (2 min)
```promql
sum by (code) (rate(http_requests_total{route="/v1/payments"}[5m]))
```
- All replicas or one? `sum by (pod) (rate(http_requests_total{route="/v1/payments",code=~"5.."}[5m]))`
- Did it start with a deploy? Check Argo CD history for `payments` and the last digest commit to `values-aws.yaml`.

## 2. Mitigate first
| Cause | Signal | Action |
|---|---|---|
| Bad release | Errors began at a sync | `git revert` the digest commit; Argo CD rolls back |
| Database | `/readyz` failing, `PaymentsNoReadyPods` | See [payments-no-ready-pods](payments-no-ready-pods.md) |
| Saturation | CPU at limit, HPA at max | Raise `autoscaling.maxReplicas`; check DB connections |
| Secrets | ExternalSecret `SecretSyncedError` | `kubectl -n payments describe externalsecret payments-secrets` |

## 3. Afterwards
Record budget consumed (`payments:request_error_ratio:rate6h`), timeline and a fix in the postmortem. If more than 50% of the monthly budget is gone, freeze non-urgent releases.

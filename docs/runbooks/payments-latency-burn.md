# Runbook: PaymentsLatencyBudgetFastBurn

**Impact:** payments succeed but too many take more than 250 ms. Agents with tight timeouts start retrying, which adds load.

## Check, in order
1. **Database:** RDS CPU, `DatabaseConnections`, read/write latency in CloudWatch. Lock contention shows up as many concurrent payments from the same payer account.
2. **Pods:** CPU throttling: `rate(container_cpu_cfs_throttled_periods_total{namespace="payments"}[5m])`. If high, raise the CPU request or let the HPA scale out.
3. **Hot accounts:** a single payer receiving bursts is serialized by design (row lock). That is correct, and the fix is client-side batching or a per-account queue, not removing the lock.
4. **Recent change:** compare p95 before and after the last deploy:
   `histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{route="/v1/payments"}[5m])))`

## Mitigate
Scale out (`kubectl -n payments scale deploy/payments --replicas=N` temporarily; HPA takes over again), or roll back.

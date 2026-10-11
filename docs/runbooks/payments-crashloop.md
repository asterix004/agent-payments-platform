# Runbook: PaymentsPodCrashLooping

**Impact:** usually none while other replicas are healthy (PDB keeps at least one). Becomes an outage if the whole rollout crashes, which `maxUnavailable: 0` prevents from replacing healthy pods.

```bash
kubectl -n payments describe pod <pod>      # OOMKilled? image pull? probe failures?
kubectl -n payments logs <pod> --previous
```
| Cause | Action |
|---|---|
| `OOMKilled` | Raise `resources.limits.memory`; check for unbounded result sets |
| Missing env/secret | Check the ExternalSecret status and `secrets.*` values |
| Bad image | Revert the digest commit; Argo CD rolls back |
| Liveness failures while the database is down | See [payments-no-ready-pods](payments-no-ready-pods.md); liveness must not depend on the DB |
| Read-only filesystem error | The app may only write to `/tmp` (emptyDir) |

#!/usr/bin/env bash
# Chaos drill: take the local database away, watch readiness fail and the
# PaymentsNoReadyPods alert fire, then restore it and watch recovery.
# Run with `make loadgen` in another terminal and Grafana/Prometheus open.
set -euo pipefail
NS=payments
OUTAGE_SECONDS="${OUTAGE_SECONDS:-240}"

alerts() {
  local pod
  pod=$(kubectl -n monitoring get pod -l app.kubernetes.io/name=prometheus -o name | head -1)
  kubectl -n monitoring exec "$pod" -c prometheus -- \
    wget -qO- 'http://localhost:9090/api/v1/alerts' \
    | python3 -c 'import json,sys; a=json.load(sys.stdin)["data"]["alerts"]; print([ (x["labels"]["alertname"], x["state"]) for x in a if x["labels"]["alertname"].startswith("Payments")] or "no payments alerts")'
}

echo "$(date -u +%T) baseline:"; kubectl -n "$NS" get pods -l app.kubernetes.io/name=payments
echo "$(date -u +%T) stopping postgres for ${OUTAGE_SECONDS}s"
kubectl -n "$NS" scale deployment/postgres --replicas=0

end=$((SECONDS + OUTAGE_SECONDS))
while (( SECONDS < end )); do
  sleep 30
  ready=$(kubectl -n "$NS" get deploy payments -o jsonpath='{.status.readyReplicas}')
  echo "$(date -u +%T) ready payments pods: ${ready:-0} | alerts: $(alerts)"
done

echo "$(date -u +%T) restoring postgres"
kubectl -n "$NS" scale deployment/postgres --replicas=1
kubectl -n "$NS" rollout status deployment/postgres --timeout=120s
# Local Postgres uses emptyDir, so the restored DB is empty; the app recreates its schema on restart.
kubectl -n "$NS" rollout restart deployment/payments
kubectl -n "$NS" rollout status deployment/payments --timeout=180s
echo "$(date -u +%T) recovered | alerts: $(alerts)"

#!/usr/bin/env bash
# Chaos drill: take the local database away, watch readiness fail and the
# PaymentsNoReadyPods alert fire, then restore it and watch recovery.
# Run with `make loadgen` in another terminal and Grafana open.
set -euo pipefail
NS=payments
OUTAGE_SECONDS="${OUTAGE_SECONDS:-240}"
PROM_SVC=$(kubectl -n monitoring get svc -o name | grep -E 'kube-prometheus-stack-prometheus$' | head -1 | cut -d/ -f2)

alerts() {
  # Query Prometheus through the API server's service proxy; the Prometheus
  # image has no shell or wget to exec into.
  kubectl get --raw "/api/v1/namespaces/monitoring/services/${PROM_SVC}:9090/proxy/api/v1/alerts" \
    | python3 -c 'import json,sys; a=json.load(sys.stdin)["data"]["alerts"]; print([(x["labels"]["alertname"], x["state"]) for x in a if x["labels"]["alertname"].startswith("Payments")] or "no payments alerts")'
}

echo "$(date -u +%T) baseline: $(alerts)"; kubectl -n "$NS" get pods -l app.kubernetes.io/name=payments
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
# Local Postgres uses emptyDir, so the restored DB is empty; restart the app to recreate the schema.
kubectl -n "$NS" rollout restart deployment/payments
kubectl -n "$NS" rollout status deployment/payments --timeout=180s
sleep 60
echo "$(date -u +%T) recovered | alerts: $(alerts)"

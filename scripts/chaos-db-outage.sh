#!/usr/bin/env bash
# Chaos drill: take the local database away, watch readiness fail and the
# PaymentsNoReadyPods and error-budget alerts fire, then restore it and watch the
# API recover without a restart. Pods must go unready, never get liveness-killed.
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
# No restart: the API pods were never killed, they only went unready. Recovery is
# readiness passing again on its own once the database is back.
kubectl -n "$NS" wait --for=condition=Available deployment/payments --timeout=120s
kubectl -n "$NS" get pods -l app.kubernetes.io/name=payments
sleep 60
echo "$(date -u +%T) recovered | alerts: $(alerts)"

restarts=$(kubectl -n "$NS" get pods -l app.kubernetes.io/name=payments \
  -o jsonpath='{range .items[*]}{.status.containerStatuses[0].restartCount}{"\n"}{end}' | awk '{s+=$1} END {print s+0}')
if (( restarts == 0 )); then
  echo "PASS: database outage made the API unready, not restarted (0 container restarts)"
else
  echo "FAIL: payments containers restarted ${restarts} time(s) during a database outage; check liveness"; exit 1
fi

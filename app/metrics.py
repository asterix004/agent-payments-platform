"""Prometheus metrics. The SLOs in deploy/helm/payments/templates/prometheusrule.yaml are built on these."""
from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "HTTP requests by route template, method and status code",
    ["route", "method", "code"],
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency by route template",
    ["route", "method"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
PAYMENTS = Counter(
    "payments_total",
    "Payment attempts by outcome",
    ["outcome"],  # succeeded | insufficient_funds | limit_exceeded | rejected | replayed | conflict
)
PAYMENT_AMOUNT = Counter(
    "payments_amount_minor_total",
    "Sum of successfully moved amounts, minor units",
    ["currency"],
)
DB_CIRCUIT_STATE = Gauge(
    "payments_db_circuit_state",
    "Database circuit breaker state (1 for the current state)",
    ["state"],  # closed | open | half_open
)

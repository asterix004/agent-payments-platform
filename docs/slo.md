# Service level objectives

| SLO | SLI | Target (30 days) | Error budget |
|---|---|---|---|
| Availability | Share of `POST /v1/payments` responses that are not 5xx | 99.9% | 43 min of full outage, or 0.1% of requests |
| Latency | Share of `POST /v1/payments` requests completing in ≤ 250 ms | 99% | 1% of requests |

4xx responses (insufficient funds, limit exceeded, bad token) are correct behaviour and do not burn the availability budget.

## Alerting
Multi-window, multi-burn-rate alerts (Google SRE Workbook), defined in `deploy/helm/payments/templates/prometheusrule.yaml`:

| Alert | Condition | Meaning | Action |
|---|---|---|---|
| `PaymentsErrorBudgetFastBurn` | 1h and 5m error ratio > 14.4 × budget | ~2% of the monthly budget gone in an hour | Page |
| `PaymentsErrorBudgetSlowBurn` | 6h and 30m error ratio > 6 × budget | ~5% gone in six hours | Page |
| `PaymentsLatencyBudgetFastBurn` | 1h and 5m slow ratio > 14.4 × budget | Latency SLO at risk | Page |
| `PaymentsNoReadyPods` | 0 ready pods for 2m | Readiness (database) failing everywhere | Page |
| `PaymentsPodCrashLooping` | > 3 restarts in 15m | Bad deploy or config | Ticket |

The short window stops an alert from firing on a brief spike and lets it clear soon after recovery; the long window ensures the burn is sustained. Every alert links to a runbook in `docs/runbooks/`.

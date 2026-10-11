# ADR 0002: Idempotency keys stored in the payment transaction

**Status:** accepted

## Context
Agents retry on timeouts. Without idempotency, a slow response followed by a retry moves money twice. AI agents retry more aggressively and less predictably than human-driven clients.

## Decision
- `POST /v1/payments` requires an `Idempotency-Key` header (8–128 chars), scoped per agent.
- The service stores `(agent_id, key) → (sha256 of canonical request body, status, response)` **in the same database transaction** as the ledger entries. Either the money moves and the key is recorded, or neither happens.
- On a repeat: same body → return the stored response with `Idempotent-Replayed: true`; different body → `422 IdempotencyConflict`.
- If two requests with the same key race, the primary key on `(agent_id, key)` makes the loser fail at commit. Its transaction rolls back and it replays the winner's response (`tests/test_concurrency.py`: 10 concurrent retries produce one transaction).

## Alternatives rejected
- **Redis lock + separate store:** a second system that must stay consistent with the ledger; a crash between "money moved" and "key saved" double-charges on retry.
- **Client-generated transaction IDs as primary keys:** works only for one endpoint and leaks storage design into the API.

## Follow-ups
Expire keys after a retention window (e.g. 24–72h) with a scheduled delete, and document the window in the API contract.

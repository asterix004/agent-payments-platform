# ADR 0003: Know-Your-Agent tokens, verified with the issuer's public key only

**Status:** accepted

## Decision
Agents authenticate with short-lived JWTs (ES256 or RS256) issued by a KYA identity provider. The payments service is configured with the issuer's **public** key, audience and issuer URL, and checks `exp`, `iat`, `iss` and `aud` on every request.

Claims drive authorization:
- `sub`: the agent. Accounts are owned by agents, and an agent can only spend from its own accounts.
- `scope`: `accounts:write`, `payments:write`, `treasury:deposit`.
- `max_txn_minor`: per-payment cap set by the agent's owner, applied together with a service-wide ceiling.

## Why
- A compromised API pod cannot mint identities, because it never has a signing key.
- Spend controls travel with the identity, so an owner can issue a narrowly-scoped, low-limit token to a new or untrusted agent.

## Not yet
JWKS discovery with key rotation (`kid`), token revocation for long-lived tokens, and a daily/rolling spend limit enforced from the ledger.

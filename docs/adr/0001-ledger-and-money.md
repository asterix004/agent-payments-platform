# ADR 0001: Double-entry ledger in integer minor units

**Status:** accepted

## Decision
- Amounts are `BIGINT` minor units (cents). The API rejects floats and non-positive values at the schema layer.
- Balances are never stored; they are the sum of an account's ledger entries. Each transaction writes exactly two entries, `-amount` on the payer and `+amount` on the payee, so the sum over the whole ledger is always zero (asserted in `tests/test_payments.py`).
- A payment locks both account rows (`SELECT … FOR UPDATE`) in sorted-ID order before reading the payer's balance. The lock makes concurrent debits serial, and the stable order prevents A→B and B→A payments from deadlocking.

## Consequences
- **Correct under concurrency:** `tests/test_concurrency.py` fires 15 parallel 1,000-cent payments at a 10,000-cent balance; exactly 10 succeed and the balance ends at 0.
- **Cost:** a balance read is an aggregate over the account's entries. At scale, add a per-account running balance maintained in the same transaction, or periodic balance snapshots, and keep the entries as the source of truth.
- **Multi-currency** is per account; cross-currency payments are rejected rather than converted.

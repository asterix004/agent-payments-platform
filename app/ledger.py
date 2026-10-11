"""Ledger operations. Each public function runs inside one database transaction."""
import hashlib
import json
import uuid

from sqlalchemy import func, select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from .db import TREASURY_ACCOUNT_ID, accounts, idempotency_keys, ledger_entries, transactions


class LedgerError(Exception):
    status_code = 400
    outcome = "rejected"


class NotFound(LedgerError):
    status_code = 404


class Forbidden(LedgerError):
    status_code = 403


class InsufficientFunds(LedgerError):
    status_code = 409
    outcome = "insufficient_funds"


class LimitExceeded(LedgerError):
    status_code = 403
    outcome = "limit_exceeded"


class IdempotencyConflict(LedgerError):
    status_code = 422
    outcome = "conflict"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def request_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def balance(conn: Connection, account_id: str) -> int:
    total = conn.execute(
        select(func.coalesce(func.sum(ledger_entries.c.amount_minor), 0)).where(
            ledger_entries.c.account_id == account_id
        )
    ).scalar_one()
    return int(total)


def get_account(conn: Connection, account_id: str, *, lock: bool = False):
    query = select(accounts).where(accounts.c.id == account_id)
    if lock:
        # Serialises concurrent debits of the same account (no-op on SQLite, used only in tests).
        query = query.with_for_update()
    row = conn.execute(query).first()
    if row is None:
        raise NotFound(f"account {account_id} not found")
    return row


def create_account(conn: Connection, agent_id: str, currency: str) -> dict:
    account_id = new_id("acct")
    conn.execute(accounts.insert().values(id=account_id, owner_agent_id=agent_id, currency=currency))
    return {"id": account_id, "owner_agent_id": agent_id, "currency": currency, "balance_minor": 0}


def _post(conn: Connection, *, kind: str, payer: str, payee: str, amount: int, currency: str,
          agent_id: str, memo: str | None) -> str:
    txn_id = new_id("txn")
    conn.execute(
        transactions.insert().values(
            id=txn_id, kind=kind, payer_account_id=payer, payee_account_id=payee,
            amount_minor=amount, currency=currency, initiated_by_agent=agent_id, memo=memo,
        )
    )
    conn.execute(
        ledger_entries.insert(),
        [
            {"transaction_id": txn_id, "account_id": payer, "amount_minor": -amount},
            {"transaction_id": txn_id, "account_id": payee, "amount_minor": amount},
        ],
    )
    return txn_id


def deposit(conn: Connection, *, agent_id: str, account_id: str, amount: int) -> dict:
    """Fund an account from the treasury (sandbox top-up). The treasury may go negative."""
    acct = get_account(conn, account_id, lock=True)
    txn_id = _post(conn, kind="deposit", payer=TREASURY_ACCOUNT_ID, payee=account_id, amount=amount,
                   currency=acct.currency, agent_id=agent_id, memo="sandbox deposit")
    return {"id": txn_id, "account_id": account_id, "balance_minor": balance(conn, account_id)}


def pay(conn: Connection, *, agent_id: str, agent_max_txn: int | None, hard_max: int,
        idem_key: str, body: dict) -> tuple[int, dict, bool]:
    """Move money payer -> payee exactly once per (agent, Idempotency-Key).

    Returns (status_code, response_body, replayed).
    """
    req_hash = request_hash(body)
    prior = conn.execute(
        select(idempotency_keys).where(
            idempotency_keys.c.agent_id == agent_id, idempotency_keys.c.key == idem_key
        )
    ).first()
    if prior is not None:
        if prior.request_hash != req_hash:
            raise IdempotencyConflict("Idempotency-Key reused with a different request body")
        return prior.status_code, json.loads(prior.response_body), True

    amount = body["amount_minor"]
    limit = min(hard_max, agent_max_txn) if agent_max_txn is not None else hard_max
    if amount > limit:
        raise LimitExceeded(f"amount {amount} exceeds the agent's per-payment limit {limit}")
    if body["payer_account_id"] == body["payee_account_id"]:
        raise LedgerError("payer and payee must differ")

    # Lock accounts in a stable order to avoid deadlocks between opposite-direction payments.
    first, second = sorted([body["payer_account_id"], body["payee_account_id"]])
    locked = {first: get_account(conn, first, lock=True), second: get_account(conn, second, lock=True)}
    payer, payee = locked[body["payer_account_id"]], locked[body["payee_account_id"]]

    if payer.owner_agent_id != agent_id:
        raise Forbidden("agent does not own the payer account")
    if not (payer.currency == payee.currency == body["currency"]):
        raise LedgerError("currency mismatch between payment and accounts")
    available = balance(conn, payer.id)
    if available < amount:
        raise InsufficientFunds(f"balance {available} < amount {amount}")

    txn_id = _post(conn, kind="payment", payer=payer.id, payee=payee.id, amount=amount,
                   currency=body["currency"], agent_id=agent_id, memo=body.get("memo"))
    response = {
        "id": txn_id,
        "payer_account_id": payer.id,
        "payee_account_id": payee.id,
        "amount_minor": amount,
        "currency": body["currency"],
        "payer_balance_minor": available - amount,
    }
    try:
        # Same transaction as the ledger rows: either both the money movement and the
        # idempotency record commit, or neither does.
        conn.execute(
            idempotency_keys.insert().values(
                agent_id=agent_id, key=idem_key, request_hash=req_hash,
                status_code=201, response_body=json.dumps(response),
            )
        )
    except IntegrityError as exc:
        # A concurrent request with the same key committed first; the caller rolls back
        # this transaction and replays the stored response.
        raise ConcurrentRetry() from exc
    return 201, response, False


class ConcurrentRetry(Exception):
    """Raised when the same idempotency key is being processed concurrently."""

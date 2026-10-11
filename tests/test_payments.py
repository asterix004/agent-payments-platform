from sqlalchemy import func, select

from app.db import ledger_entries
from tests.conftest import auth, idem, token


def pay(client, alice, bob, amount=2_500, headers=None, **extra):
    body = {"payer_account_id": alice["id"], "payee_account_id": bob["id"],
            "amount_minor": amount, "currency": "USD", **extra}
    return client.post("/v1/payments", json=body, headers={**auth("agent_alice"), **(headers or idem())})


def balance_of(client, account, agent):
    return client.get(f"/v1/accounts/{account['id']}", headers=auth(agent)).json()["balance_minor"]


def test_payment_moves_money_and_balances_reconcile(client, funded):
    alice, bob = funded
    r = pay(client, alice, bob, 2_500)
    assert r.status_code == 201, r.text
    assert r.json()["payer_balance_minor"] == 7_500
    assert balance_of(client, alice, "agent_alice") == 7_500
    assert balance_of(client, bob, "agent_bob") == 2_500
    # Double-entry invariant: all ledger rows across the system sum to zero.
    with client.app.state.engine.connect() as conn:
        assert conn.execute(select(func.sum(ledger_entries.c.amount_minor))).scalar_one() == 0


def test_retry_with_same_key_does_not_double_charge(client, funded):
    alice, bob = funded
    key = idem()
    first = pay(client, alice, bob, 1_000, headers=key)
    second = pay(client, alice, bob, 1_000, headers=key)
    assert first.status_code == second.status_code == 201
    assert second.headers.get("Idempotent-Replayed") == "true"
    assert first.json()["id"] == second.json()["id"]
    assert balance_of(client, alice, "agent_alice") == 9_000


def test_same_key_different_body_is_rejected(client, funded):
    alice, bob = funded
    key = idem()
    assert pay(client, alice, bob, 1_000, headers=key).status_code == 201
    r = pay(client, alice, bob, 1_001, headers=key)
    assert r.status_code == 422
    assert r.json()["error"] == "IdempotencyConflict"


def test_insufficient_funds(client, funded):
    alice, bob = funded
    r = pay(client, alice, bob, 10_001)
    assert r.status_code == 409
    assert balance_of(client, alice, "agent_alice") == 10_000


def test_agent_spend_limit_from_token(client, funded):
    alice, bob = funded
    body = {"payer_account_id": alice["id"], "payee_account_id": bob["id"], "amount_minor": 600, "currency": "USD"}
    r = client.post("/v1/payments", json=body, headers={**auth("agent_alice", max_txn=500), **idem()})
    assert r.status_code == 403
    assert r.json()["error"] == "LimitExceeded"


def test_agent_cannot_spend_from_someone_elses_account(client, funded):
    alice, bob = funded
    body = {"payer_account_id": alice["id"], "payee_account_id": bob["id"], "amount_minor": 100, "currency": "USD"}
    r = client.post("/v1/payments", json=body, headers={**auth("agent_bob"), **idem()})
    assert r.status_code == 403


def test_idempotency_key_required(client, funded):
    alice, bob = funded
    body = {"payer_account_id": alice["id"], "payee_account_id": bob["id"], "amount_minor": 100, "currency": "USD"}
    assert client.post("/v1/payments", json=body, headers=auth("agent_alice")).status_code == 422


def test_rejects_unsigned_expired_and_wrong_issuer_tokens(client, funded):
    alice, bob = funded
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    other = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    body = {"payer_account_id": alice["id"], "payee_account_id": bob["id"], "amount_minor": 100, "currency": "USD"}
    for bad in (token("agent_alice", key=other), token("agent_alice", ttl=-10), token("agent_alice", issuer="https://evil")):
        r = client.post("/v1/payments", json=body, headers={"Authorization": f"Bearer {bad}", **idem()})
        assert r.status_code == 401
    assert client.post("/v1/payments", json=body, headers=idem()).status_code == 401


def test_missing_scope(client, funded):
    alice, bob = funded
    body = {"payer_account_id": alice["id"], "payee_account_id": bob["id"], "amount_minor": 100, "currency": "USD"}
    r = client.post("/v1/payments", json=body, headers={**auth("agent_alice", scope="accounts:write"), **idem()})
    assert r.status_code == 403


def test_rejects_float_and_negative_amounts(client, funded):
    alice, bob = funded
    assert pay(client, alice, bob, 10.5).status_code == 422
    assert pay(client, alice, bob, -5).status_code == 422


def test_health_and_metrics(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200
    m = client.get("/metrics").text
    assert "http_requests_total" in m and "payments_total" in m

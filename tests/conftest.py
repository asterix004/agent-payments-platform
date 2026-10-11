import os
import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

ISSUER = "https://kya.test"
AUDIENCE = "payments-api"

_key = ec.generate_private_key(ec.SECP256R1())
PRIVATE_PEM = _key.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()
PUBLIC_PEM = _key.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
).decode()

os.environ.update({"KYA_PUBLIC_KEY": PUBLIC_PEM, "KYA_ISSUER": ISSUER, "KYA_AUDIENCE": AUDIENCE})


def token(agent: str, scope: str = "accounts:write payments:write", max_txn: int | None = None,
          ttl: int = 300, key: str = PRIVATE_PEM, issuer: str = ISSUER) -> str:
    now = int(time.time())
    claims = {"sub": agent, "scope": scope, "iat": now, "exp": now + ttl, "iss": issuer, "aud": AUDIENCE}
    if max_txn is not None:
        claims["max_txn_minor"] = max_txn
    return jwt.encode(claims, key, algorithm="ES256")


def auth(agent: str, **kw) -> dict:
    return {"Authorization": f"Bearer {token(agent, **kw)}"}


@pytest.fixture()
def client(tmp_path):
    # Postgres in CI (DATABASE_URL set by the workflow); a throwaway SQLite file locally.
    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path}/test.db"
    from app.main import create_app

    app = create_app(url)
    with TestClient(app) as c:
        yield c
    if url.startswith("postgresql"):
        from app.db import metadata

        metadata.drop_all(app.state.engine)


@pytest.fixture()
def funded(client):
    """Two agents: alice with a funded USD account, bob with an empty one."""
    alice = client.post("/v1/accounts", json={"currency": "USD"}, headers=auth("agent_alice")).json()
    bob = client.post("/v1/accounts", json={"currency": "USD"}, headers=auth("agent_bob")).json()
    r = client.post(
        "/v1/deposits",
        json={"account_id": alice["id"], "amount_minor": 10_000},
        headers=auth("ops", scope="treasury:deposit"),
    )
    assert r.status_code == 201, r.text
    return alice, bob


def idem() -> dict:
    return {"Idempotency-Key": f"test-{uuid.uuid4().hex}"}

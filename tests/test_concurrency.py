"""Race-condition tests. They need real row locks, so they run only against Postgres (CI)."""
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.conftest import auth, idem

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"),
    reason="row-level locking needs Postgres; set TEST_DATABASE_URL",
)


def _body(alice, bob, amount):
    return {"payer_account_id": alice["id"], "payee_account_id": bob["id"], "amount_minor": amount, "currency": "USD"}


def test_concurrent_retries_with_one_key_charge_once(client, funded):
    alice, bob = funded
    key = idem()
    headers = {**auth("agent_alice"), **key}
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(lambda _: client.post("/v1/payments", json=_body(alice, bob, 1_000), headers=headers),
                                range(10)))
    ids = {r.json()["id"] for r in results if r.status_code == 201}
    assert len(ids) == 1
    balance = client.get(f"/v1/accounts/{alice['id']}", headers=auth("agent_alice")).json()["balance_minor"]
    assert balance == 9_000


def test_concurrent_debits_never_overdraw(client, funded):
    alice, bob = funded  # alice holds 10,000

    def one(_):
        return client.post("/v1/payments", json=_body(alice, bob, 1_000), headers={**auth("agent_alice"), **idem()})

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(one, range(15)))
    succeeded = sum(r.status_code == 201 for r in results)
    assert succeeded == 10
    assert all(r.status_code in (201, 409) for r in results)
    balance = client.get(f"/v1/accounts/{alice['id']}", headers=auth("agent_alice")).json()["balance_minor"]
    assert balance == 0

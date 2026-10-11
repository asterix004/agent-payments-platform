#!/usr/bin/env python3
"""Traffic generator for demos and SLO testing.

Creates N agents with funded accounts, then sends payments at a target rate.
On a timeout it retries with the SAME Idempotency-Key, which is what a correct
agent client must do; the ledger guarantees the payment still happens once.

  python scripts/loadgen.py --base-url http://localhost:8080 --rps 20 --duration 300
Requires .dev-keys/ from `python scripts/kya_dev_issuer.py keys`.
"""
import argparse
import asyncio
import random
import time
import uuid

import httpx
from kya_dev_issuer import mint


async def setup(client: httpx.AsyncClient, agents: int, issuer: str, audience: str) -> list[dict]:
    ops = {"Authorization": f"Bearer {mint('ops', 'treasury:deposit', None, 3600, issuer, audience)}"}
    out = []
    for i in range(agents):
        agent = f"agent_load_{i}"
        tok = mint(agent, "accounts:write payments:write", 50_000, 3600, issuer, audience)
        headers = {"Authorization": f"Bearer {tok}"}
        acct = (await client.post("/v1/accounts", json={"currency": "USD"}, headers=headers)).json()
        await client.post("/v1/deposits", json={"account_id": acct["id"], "amount_minor": 10_000_000}, headers=ops)
        out.append({"agent": agent, "headers": headers, "account": acct["id"]})
    return out


async def one_payment(client, payer, payee, stats) -> None:
    key = uuid.uuid4().hex
    amount = random.randint(1, 5_000)  # noqa: S311 - test data, not cryptography
    body = {"payer_account_id": payer["account"], "payee_account_id": payee["account"],
            "amount_minor": amount, "currency": "USD", "memo": "loadgen"}
    for attempt in range(3):
        try:
            r = await client.post("/v1/payments", json=body, headers={**payer["headers"], "Idempotency-Key": key})
            stats[r.status_code] = stats.get(r.status_code, 0) + 1
            if r.headers.get("Idempotent-Replayed"):
                stats["replayed"] = stats.get("replayed", 0) + 1
            return
        except httpx.TransportError:
            stats["transport_error"] = stats.get("transport_error", 0) + 1
            await asyncio.sleep(0.2 * (attempt + 1))


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://localhost:8080")
    p.add_argument("--agents", type=int, default=10)
    p.add_argument("--rps", type=float, default=10)
    p.add_argument("--duration", type=int, default=120)
    p.add_argument("--issuer", default="https://kya.example.dev")
    p.add_argument("--audience", default="payments-api")
    args = p.parse_args()

    async with httpx.AsyncClient(base_url=args.base_url, timeout=5) as client:
        agents = await setup(client, args.agents, args.issuer, args.audience)
        stats: dict = {}
        tasks, start, sent = set(), time.monotonic(), 0
        while time.monotonic() - start < args.duration:
            payer, payee = random.sample(agents, 2)
            task = asyncio.create_task(one_payment(client, payer, payee, stats))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
            sent += 1
            if sent % max(1, int(args.rps * 10)) == 0:
                print(f"t={time.monotonic() - start:5.0f}s sent={sent} {stats}", flush=True)
            await asyncio.sleep(1 / args.rps)
        await asyncio.gather(*tasks)
        print(f"done: sent={sent} {stats}")


if __name__ == "__main__":
    asyncio.run(main())

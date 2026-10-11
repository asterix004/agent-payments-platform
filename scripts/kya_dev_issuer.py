#!/usr/bin/env python3
"""Development-only KYA issuer: creates a signing key pair and mints agent tokens.

In production the issuer is an external identity provider; the payments service
only ever receives its public key (see app/auth.py).

  python scripts/kya_dev_issuer.py keys                    # writes .dev-keys/
  python scripts/kya_dev_issuer.py token agent_alice \
      --scope "accounts:write payments:write" --max-txn 5000 # prints a JWT
"""
import argparse
import time
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

KEY_DIR = Path(__file__).resolve().parent.parent / ".dev-keys"


def make_keys() -> None:
    KEY_DIR.mkdir(exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    (KEY_DIR / "issuer.key").write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    (KEY_DIR / "issuer.pub").write_bytes(
        key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    print(f"wrote {KEY_DIR}/issuer.key (keep private) and {KEY_DIR}/issuer.pub")


def mint(agent: str, scope: str, max_txn: int | None, ttl: int, issuer: str, audience: str) -> str:
    now = int(time.time())
    claims = {"sub": agent, "scope": scope, "iat": now, "exp": now + ttl, "iss": issuer, "aud": audience}
    if max_txn is not None:
        claims["max_txn_minor"] = max_txn
    return jwt.encode(claims, (KEY_DIR / "issuer.key").read_text(), algorithm="ES256")


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("keys")
    t = sub.add_parser("token")
    t.add_argument("agent")
    t.add_argument("--scope", default="accounts:write payments:write")
    t.add_argument("--max-txn", type=int, default=None)
    t.add_argument("--ttl", type=int, default=900)
    t.add_argument("--issuer", default="https://kya.example.dev")
    t.add_argument("--audience", default="payments-api")
    args = p.parse_args()
    if args.cmd == "keys":
        make_keys()
    else:
        print(mint(args.agent, args.scope, args.max_txn, args.ttl, args.issuer, args.audience))


if __name__ == "__main__":
    main()

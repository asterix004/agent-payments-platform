"""Know-Your-Agent (KYA) token verification.

An AI agent presents a short-lived JWT signed (RS256/ES256) by a trusted KYA issuer.
The service only holds the issuer's PUBLIC key, so it can verify identity but can
never mint tokens. Claims used:

  sub                 agent id
  scope               space-separated, e.g. "payments:write accounts:write"
  max_txn_minor       per-payment spending cap set by the agent's owner
"""
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, status

from .config import Settings, get_settings

ALGORITHMS = ["RS256", "ES256"]


@dataclass(frozen=True)
class Agent:
    agent_id: str
    scopes: frozenset[str]
    max_txn_minor: int | None

    def require(self, scope: str) -> None:
        if scope not in self.scopes:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"token lacks scope '{scope}'")


def current_agent(request: Request, settings: Settings = Depends(get_settings)) -> Agent:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    if not settings.kya_public_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "KYA public key not configured")
    try:
        claims = jwt.decode(
            header[7:],
            settings.kya_public_key,
            algorithms=ALGORITHMS,
            audience=settings.kya_audience,
            issuer=settings.kya_issuer,
            options={"require": ["sub", "exp", "iat", "iss", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid agent token: {exc}") from exc
    max_txn = claims.get("max_txn_minor")
    return Agent(
        agent_id=claims["sub"],
        scopes=frozenset(str(claims.get("scope", "")).split()),
        max_txn_minor=int(max_txn) if max_txn is not None else None,
    )

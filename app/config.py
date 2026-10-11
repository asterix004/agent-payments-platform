"""Runtime configuration from environment variables (12-factor; no secrets in code)."""
import os
from dataclasses import dataclass, field
from pathlib import Path


def _read_public_key() -> str:
    inline = os.environ.get("KYA_PUBLIC_KEY", "")
    if inline:
        return inline
    path = os.environ.get("KYA_PUBLIC_KEY_FILE", "")
    return Path(path).read_text() if path else ""


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.environ.get("DATABASE_URL", "sqlite:///./payments.db"))
    # PEM public key of the KYA issuer. Tokens are verified, never issued, by this service.
    kya_public_key: str = field(default_factory=_read_public_key)
    kya_issuer: str = field(default_factory=lambda: os.environ.get("KYA_ISSUER", "https://kya.example.dev"))
    kya_audience: str = field(default_factory=lambda: os.environ.get("KYA_AUDIENCE", "payments-api"))
    # Hard ceiling regardless of what a token allows: 10,000.00 in minor units.
    max_payment_minor: int = field(default_factory=lambda: int(os.environ.get("MAX_PAYMENT_MINOR", "1000000")))
    service_name: str = field(default_factory=lambda: os.environ.get("OTEL_SERVICE_NAME", "payments-api"))


def get_settings() -> Settings:
    return Settings()

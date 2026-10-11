"""Schema and engine. Money is always an integer number of minor units (cents)."""
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    func,
    text,
)
from sqlalchemy.engine import Engine

metadata = MetaData()

TREASURY_ACCOUNT_ID = "acct_treasury"

accounts = Table(
    "accounts",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("owner_agent_id", String(128), nullable=False, index=True),
    Column("currency", String(3), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

transactions = Table(
    "transactions",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("kind", String(16), nullable=False),  # payment | deposit
    Column("payer_account_id", String(64), ForeignKey("accounts.id"), nullable=False),
    Column("payee_account_id", String(64), ForeignKey("accounts.id"), nullable=False),
    Column("amount_minor", BigInteger, nullable=False),
    Column("currency", String(3), nullable=False),
    Column("initiated_by_agent", String(128), nullable=False),
    Column("memo", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

# Double-entry: every transaction writes exactly two rows that sum to zero.
ledger_entries = Table(
    "ledger_entries",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("transaction_id", String(64), ForeignKey("transactions.id"), nullable=False),
    Column("account_id", String(64), ForeignKey("accounts.id"), nullable=False),
    Column("amount_minor", BigInteger, nullable=False),  # negative = debit, positive = credit
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)
Index("ix_ledger_account", ledger_entries.c.account_id)

# Idempotency: one row per (agent, key). Stores the original request hash and response
# so a retried request returns the same result instead of moving money twice.
idempotency_keys = Table(
    "idempotency_keys",
    metadata,
    Column("agent_id", String(128), primary_key=True),
    Column("key", String(128), primary_key=True),
    Column("request_hash", String(64), nullable=False),
    Column("status_code", Integer, nullable=False),
    Column("response_body", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)


def make_engine(url: str) -> Engine:
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


def init_db(engine: Engine) -> None:
    """Create tables and the treasury account. Production would run Alembic migrations as a pre-deploy Job.

    On Postgres an advisory lock serialises this across replicas starting at the same time.
    """
    with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(727274)"))
        metadata.create_all(conn)
        exists = conn.execute(accounts.select().where(accounts.c.id == TREASURY_ACCOUNT_ID)).first()
        if not exists:
            conn.execute(accounts.insert().values(id=TREASURY_ACCOUNT_ID, owner_agent_id="system", currency="USD"))

from pydantic import BaseModel, Field


class AccountCreate(BaseModel):
    currency: str = Field(default="USD", pattern="^[A-Z]{3}$")


class Account(BaseModel):
    id: str
    owner_agent_id: str
    currency: str
    balance_minor: int


class DepositCreate(BaseModel):
    account_id: str
    amount_minor: int = Field(gt=0)


class PaymentCreate(BaseModel):
    payer_account_id: str
    payee_account_id: str
    amount_minor: int = Field(gt=0, description="Integer minor units, e.g. cents. Never floats.")
    currency: str = Field(pattern="^[A-Z]{3}$")
    memo: str | None = Field(default=None, max_length=280)


class Payment(BaseModel):
    id: str
    payer_account_id: str
    payee_account_id: str
    amount_minor: int
    currency: str
    payer_balance_minor: int

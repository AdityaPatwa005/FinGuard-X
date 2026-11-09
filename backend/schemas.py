import re
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CustomerCreate(BaseModel):
    """Client-provided fields for registering a customer."""

    model_config = ConfigDict(str_strip_whitespace=True)

    full_name: str = Field(min_length=1, max_length=160)
    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def normalize_and_validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        email_pattern = re.compile(
            r"[A-Za-z0-9.!#$%&'*+/=?^_{|}~-]+@"
            r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
            r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+"
        )
        local_part = normalized.partition("@")[0]
        if (
            len(local_part) > 64
            or local_part.startswith(".")
            or local_part.endswith(".")
            or ".." in normalized
            or email_pattern.fullmatch(normalized) is None
        ):
            raise ValueError("Enter a valid email address.")
        return normalized


class AccountResponse(BaseModel):
    """Safe account fields returned alongside a customer."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_number: str
    account_type: str
    balance: Decimal
    currency: str
    status: str


class CustomerResponse(BaseModel):
    """Customer registration response with its associated account."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    full_name: str
    email: str
    account: AccountResponse


class FundingRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    account_id: UUID
    amount: Decimal = Field(gt=Decimal("0"), max_digits=18, decimal_places=2)
    description: str | None = Field(default=None, max_length=255)


class TransferRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    sender_account_id: UUID
    receiver_account_id: UUID
    amount: Decimal = Field(gt=Decimal("0"), max_digits=18, decimal_places=2)
    description: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def accounts_must_differ(self) -> "TransferRequest":
        if self.sender_account_id == self.receiver_account_id:
            raise ValueError("Sender and receiver accounts must be different.")
        return self


class LedgerEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ledger_account_id: UUID
    entry_type: str
    amount: Decimal
    currency: str
    created_at: datetime


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sender_account_id: UUID | None
    receiver_account_id: UUID
    transaction_type: str
    amount: Decimal
    currency: str
    status: str
    idempotency_key: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    ledger_entries: list[LedgerEntryResponse]

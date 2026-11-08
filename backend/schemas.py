import re
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


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

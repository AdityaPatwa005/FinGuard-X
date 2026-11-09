import re
from datetime import datetime
from decimal import Decimal
from typing import Literal
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


RiskBandValue = Literal["LOW", "GUARDED", "ELEVATED", "CRITICAL"]
IncidentStatusValue = Literal["OPEN", "INVESTIGATING", "RESOLVED", "DISMISSED"]


class RiskDistributionResponse(BaseModel):
    band: RiskBandValue
    count: int


class DashboardSummaryResponse(BaseModel):
    period_start: datetime
    transactions_monitored: int
    high_risk_transactions: int
    active_incidents: int
    open_cases: int
    critical_cases: int
    awaiting_review: int
    resolved_cases: int
    blocked_transactions: int | None
    blocked_transactions_note: str
    triggered_detections: int
    risk_distribution: list[RiskDistributionResponse]
    risk_distribution_total: int


class DetectionEvidenceResponse(BaseModel):
    name: str
    value: str | int | bool
    unit: str | None = None


class DetectionBriefResponse(BaseModel):
    id: UUID
    rule_id: str
    rule_version: str
    rule_name: str
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    explanation: str
    evidence: list[DetectionEvidenceResponse]
    detected_at: datetime
    incident_id: UUID | None


class RecentTransactionResponse(BaseModel):
    id: UUID
    transaction_type: Literal["FUNDING", "TRANSFER"]
    sender_account: str | None
    receiver_account: str
    amount: Decimal
    currency: str
    status: Literal["PENDING", "COMPLETED", "FAILED"]
    created_at: datetime
    risk_score: int | None
    risk_band: RiskBandValue | None
    triggered_detection_count: int
    detections: list[DetectionBriefResponse]


class RecentDetectionResponse(DetectionBriefResponse):
    transaction_amount: Decimal
    currency: str
    incident_risk_score: int | None
    incident_risk_band: RiskBandValue | None


class IncidentListItemResponse(BaseModel):
    id: UUID
    title: str
    status: IncidentStatusValue
    risk_score: int
    risk_band: RiskBandValue
    risk_explanation: str
    primary_account: str
    opened_at: datetime
    last_activity_at: datetime
    closed_at: datetime | None
    transaction_count: int
    detection_count: int


class IncidentListResponse(BaseModel):
    items: list[IncidentListItemResponse]
    total: int
    limit: int
    offset: int


class IncidentTransactionResponse(BaseModel):
    id: UUID
    transaction_type: Literal["FUNDING", "TRANSFER"]
    amount: Decimal
    currency: str
    status: Literal["PENDING", "COMPLETED", "FAILED"]
    created_at: datetime


class RuleEvaluationResponse(BaseModel):
    id: UUID
    rule_id: str
    rule_version: str
    rule_name: str
    rule_description: str
    transaction_id: UUID
    detected_at: datetime
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    outcome: Literal["TRIGGERED", "NOT_TRIGGERED", "NOT_EVALUATED"]
    explanation: str
    evidence: list[DetectionEvidenceResponse]
    limitation: str | None


class IncidentLifecycleResponse(BaseModel):
    id: UUID
    from_status: IncidentStatusValue | None
    to_status: IncidentStatusValue
    actor_identifier: str | None
    note: str | None
    changed_at: datetime


class IncidentDetailResponse(IncidentListItemResponse):
    anchor_transaction_id: UUID
    risk_policy_version: str
    risk_evidence: list[dict[str, object]]
    transactions: list[IncidentTransactionResponse]
    detections: list[RuleEvaluationResponse]
    timeline: list[IncidentLifecycleResponse]


class IncidentStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: IncidentStatusValue
    note: str | None = Field(default=None, max_length=2000)


class IncidentNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    note: str = Field(min_length=1, max_length=2000)

    @field_validator("note")
    @classmethod
    def note_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Note cannot be blank.")
        return value.strip()

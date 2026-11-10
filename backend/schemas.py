import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
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


class RuleThresholdResponse(BaseModel):
    name: str
    value: str | int
    unit: str | None = None


class RuleCatalogItemResponse(BaseModel):
    rule_id: str
    version: str
    name: str
    description: str
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    required_features: list[str]
    minimum_history: str
    thresholds: list[RuleThresholdResponse]


class RuleEvaluationListItemResponse(BaseModel):
    id: UUID
    rule_id: str
    rule_version: str
    rule_name: str
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    outcome: Literal["TRIGGERED", "NOT_TRIGGERED", "NOT_EVALUATED"]
    explanation: str
    evidence: list[DetectionEvidenceResponse]
    limitation: str | None
    transaction_id: UUID
    transaction_type: Literal["FUNDING", "TRANSFER"]
    transaction_amount: Decimal
    currency: str
    detected_at: datetime
    incident_id: UUID | None
    incident_risk_score: int | None
    incident_risk_band: RiskBandValue | None


class RuleEvaluationListResponse(BaseModel):
    items: list[RuleEvaluationListItemResponse]
    total: int
    limit: int
    offset: int


class OutboxHealthResponse(BaseModel):
    pending_count: int
    processing_count: int
    processed_count: int
    failed_count: int
    oldest_pending_at: datetime | None
    oldest_failed_at: datetime | None
    last_processed_at: datetime | None
    status: Literal["HEALTHY", "ATTENTION"]
    note: str


GeoEventType = Literal[
    "LOGIN_LOCATION", "TRANSACTION_ORIGIN", "BENEFICIARY_LOCATION", "TRANSACTION_ROUTE"
]
GeoRiskBand = Literal["LOW", "GUARDED", "ELEVATED", "CRITICAL"]


class GeoCoordinateResponse(BaseModel):
    latitude: Decimal = Field(ge=-90, le=90)
    longitude: Decimal = Field(ge=-180, le=180)


class GeoMetadataResponse(BaseModel):
    synthetic: bool
    city: str | None = None
    scenario: str | None = None
    label: str | None = None


class GeospatialEventResponse(BaseModel):
    id: UUID
    event_type: GeoEventType
    account_id: UUID | None
    transaction_id: UUID | None
    incident_id: UUID | None
    coordinate: GeoCoordinateResponse | None
    event_at: datetime
    metadata: GeoMetadataResponse
    incident_risk_band: GeoRiskBand | None = None
    incident_risk_score: int | None = Field(default=None, ge=0, le=100)


class GeospatialEventPage(BaseModel):
    items: list[GeospatialEventResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)


class GeospatialRouteResponse(BaseModel):
    id: UUID
    transaction_id: UUID
    incident_id: UUID | None
    origin_event_id: UUID
    destination_event_id: UUID
    origin: GeoCoordinateResponse
    destination: GeoCoordinateResponse
    origin_label: str | None = None
    destination_label: str | None = None
    amount: Decimal
    currency: str
    transaction_status: Literal["PENDING", "COMPLETED", "FAILED"]
    transaction_type: Literal["FUNDING", "TRANSFER"]
    event_at: datetime
    synthetic: bool
    scenario: str | None = None
    incident_status: str | None = None
    incident_risk_band: GeoRiskBand | None = None
    incident_risk_score: int | None = Field(default=None, ge=0, le=100)


class GeospatialRoutePage(BaseModel):
    items: list[GeospatialRouteResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)


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

"""Claim, normalize, validate, and acknowledge transactional outbox events."""

import logging
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Literal, Sequence
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from outbox_models import OutboxEvent


logger = logging.getLogger(__name__)


class EventNormalizationError(ValueError):
    """Validation failure with a safe message that excludes payload values."""


class NormalizedTransactionEvent(BaseModel):
    """Canonical, typed representation; original payload remains available."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    event_type: str = Field(min_length=1, max_length=100)
    event_version: int = Field(gt=0)
    source_system: str = Field(min_length=1, max_length=80)
    transaction_id: UUID
    transaction_type: Literal["FUNDING", "TRANSFER"]
    sender_account_id: UUID | None
    receiver_account_id: UUID
    amount: Decimal = Field(gt=Decimal("0"), max_digits=18, decimal_places=2)
    currency: Literal["INR"]
    timestamp: datetime
    description: str | None = Field(default=None, max_length=255)
    original_payload: dict[str, Any]

    @field_validator("amount", mode="before")
    @classmethod
    def reject_binary_float(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError("amount must use a decimal-safe representation")
        return value

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class EventClaim:
    event_id: UUID
    processing_token: UUID
    event_type: str
    event_version: int
    source_system: str
    related_transaction_id: UUID
    payload: dict[str, Any]


@dataclass(frozen=True)
class EventBatchResult:
    claimed: int
    processed: int
    failed: int


def normalize_transaction_event(
    *,
    event_id: UUID,
    event_type: str,
    event_version: int,
    source_system: str,
    related_transaction_id: UUID,
    payload: dict[str, Any],
) -> NormalizedTransactionEvent:
    """Validate payload and envelope agreement without changing stored JSON."""
    try:
        normalized = NormalizedTransactionEvent.model_validate(
            {**payload, "original_payload": deepcopy(payload)}
        )
    except ValidationError as exc:
        allowed_fields = {
            "event_id", "event_type", "event_version", "source_system",
            "transaction_id", "transaction_type", "sender_account_id",
            "receiver_account_id", "amount", "currency", "timestamp", "description",
        }
        paths = sorted(
            {
                str(error["loc"][0])
                if error["loc"] and error["loc"][0] in allowed_fields
                else "unknown field"
                for error in exc.errors()
            }
        )
        field_summary = ", ".join(paths[:8]) or "payload"
        raise EventNormalizationError(f"Invalid event payload fields: {field_summary}.") from None

    expected_type = f"transaction.{normalized.transaction_type.lower()}.completed"
    if (
        normalized.event_id != event_id
        or normalized.event_type != event_type
        or normalized.event_version != event_version
        or normalized.source_system != source_system
        or normalized.transaction_id != related_transaction_id
        or normalized.event_type != expected_type
    ):
        raise EventNormalizationError("Event envelope does not match its payload.")
    if normalized.transaction_type == "FUNDING" and normalized.sender_account_id is not None:
        raise EventNormalizationError("Funding events must not include a sender account.")
    if normalized.transaction_type == "TRANSFER":
        if normalized.sender_account_id is None:
            raise EventNormalizationError("Transfer events require a sender account.")
        if normalized.sender_account_id == normalized.receiver_account_id:
            raise EventNormalizationError("Transfer accounts must be different.")
    return normalized


def claim_pending_events(
    db: Session,
    *,
    batch_size: int,
    lease_seconds: int = 300,
    now: datetime | None = None,
    event_ids: Sequence[UUID] | None = None,
) -> list[EventClaim]:
    """Claim a batch inside the caller's transaction using SKIP LOCKED."""
    if batch_size < 1 or lease_seconds < 1:
        raise ValueError("batch_size and lease_seconds must be positive")
    current_time = now or datetime.now(timezone.utc)
    reclaim_before = current_time - timedelta(seconds=lease_seconds)
    eligible = or_(
        OutboxEvent.processing_status.in_(("PENDING", "FAILED")),
        and_(
            OutboxEvent.processing_status == "PROCESSING",
            OutboxEvent.processing_started_at < reclaim_before,
        ),
    )
    if event_ids is not None:
        eligible = and_(eligible, OutboxEvent.id.in_(event_ids))
    events = db.scalars(
        select(OutboxEvent)
        .where(eligible)
        .order_by(OutboxEvent.created_at, OutboxEvent.id)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    ).all()

    claims: list[EventClaim] = []
    for event in events:
        token = uuid4()
        event.processing_status = "PROCESSING"
        event.processing_started_at = current_time
        event.processing_token = token
        event.attempt_count += 1
        claims.append(
            EventClaim(
                event_id=event.id,
                processing_token=token,
                event_type=event.event_type,
                event_version=event.event_version,
                source_system=event.source_system,
                related_transaction_id=event.related_transaction_id,
                payload=deepcopy(event.payload),
            )
        )
    db.flush()
    return claims


def process_event_batch(
    session_factory: Callable[[], Session],
    *,
    batch_size: int = 50,
    lease_seconds: int = 300,
) -> EventBatchResult:
    """Claim and process one batch; a later invocation retries FAILED events."""
    with session_factory() as db:
        with db.begin():
            claims = claim_pending_events(
                db, batch_size=batch_size, lease_seconds=lease_seconds
            )

    processed = 0
    failed = 0
    for claim in claims:
        try:
            normalized = normalize_transaction_event(
                event_id=claim.event_id,
                event_type=claim.event_type,
                event_version=claim.event_version,
                source_system=claim.source_system,
                related_transaction_id=claim.related_transaction_id,
                payload=claim.payload,
            )
            if not _process_claimed_event(session_factory, claim, normalized):
                # A lease may have expired and been reclaimed while this worker ran.
                logger.info("Outbox event %s claim was superseded.", claim.event_id)
                continue
            processed += 1
        except EventNormalizationError as exc:
            _mark_failed(session_factory, claim, str(exc))
            failed += 1
            logger.warning("Outbox event %s failed validation: %s", claim.event_id, exc)
        except Exception as exc:
            _mark_failed(session_factory, claim, "Event processing failed.")
            failed += 1
            logger.error(
                "Outbox event %s failed during processing (%s).",
                claim.event_id,
                type(exc).__name__,
            )
    return EventBatchResult(claimed=len(claims), processed=processed, failed=failed)


def _process_claimed_event(
    session_factory: Callable[[], Session],
    claim: EventClaim,
    normalized: NormalizedTransactionEvent,
) -> bool:
    """Persist detections and acknowledge the outbox row atomically."""
    with session_factory() as db:
        with db.begin():
            outbox = db.scalar(
                select(OutboxEvent)
                .where(
                    OutboxEvent.id == claim.event_id,
                    OutboxEvent.processing_status == "PROCESSING",
                    OutboxEvent.processing_token == claim.processing_token,
                )
                .with_for_update()
            )
            if outbox is None:
                return False

            # Import at call-time to avoid coupling the reusable normalizer to
            # the detection layer's event types.
            from detection_pipeline import persist_transfer_detections

            persist_transfer_detections(db, normalized)
            outbox.processing_status = "PROCESSED"
            outbox.processed_at = datetime.now(timezone.utc)
            outbox.processing_started_at = None
            outbox.processing_token = None
            outbox.last_error = None
            db.flush()
            return True


def _mark_failed(
    session_factory: Callable[[], Session], claim: EventClaim, safe_error: str
) -> bool:
    # Error strings are authored by this module and never include raw payload values.
    safe_error = safe_error[:500]
    with session_factory() as db:
        with db.begin():
            result = db.execute(
                update(OutboxEvent)
                .where(
                    OutboxEvent.id == claim.event_id,
                    OutboxEvent.processing_status == "PROCESSING",
                    OutboxEvent.processing_token == claim.processing_token,
                )
                .values(
                    processing_status="FAILED",
                    processed_at=None,
                    processing_started_at=None,
                    processing_token=None,
                    last_error=safe_error,
                )
            )
            return result.rowcount == 1

"""Create versioned outbox event envelopes for committed simulator operations."""

from datetime import timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from outbox_models import OutboxEvent
from transaction_models import Transaction


SOURCE_SYSTEM = "finbank_simulator"


def add_transaction_completed_event(db: Session, transaction: Transaction) -> OutboxEvent:
    """Stage exactly one safe telemetry event in the financial transaction."""
    event_id = uuid4()
    event_type = f"transaction.{transaction.transaction_type.lower()}.completed"
    timestamp = transaction.created_at
    # SQLite's test dialect returns naive values for timezone-aware columns.
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    payload = {
        "event_id": str(event_id),
        "event_type": event_type,
        "event_version": 1,
        "source_system": SOURCE_SYSTEM,
        "transaction_id": str(transaction.id),
        "transaction_type": transaction.transaction_type,
        "sender_account_id": (
            str(transaction.sender_account_id)
            if transaction.sender_account_id is not None
            else None
        ),
        "receiver_account_id": str(transaction.receiver_account_id),
        "amount": format(transaction.amount, ".2f"),
        "currency": transaction.currency,
        "timestamp": timestamp.astimezone(timezone.utc).isoformat(),
        "description": transaction.description,
    }
    event = OutboxEvent(
        id=event_id,
        event_type=event_type,
        event_version=1,
        source_system=SOURCE_SYSTEM,
        related_transaction_id=transaction.id,
        deduplication_key=f"transaction:{transaction.id}:completed:v1",
        payload=payload,
    )
    db.add(event)
    return event

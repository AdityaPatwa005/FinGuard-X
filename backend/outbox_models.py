"""Transactional outbox records emitted by simulator transactions."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Uuid,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models import Base
from transaction_models import Transaction


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint(
            "processing_status IN ('PENDING', 'PROCESSING', 'PROCESSED', 'FAILED')",
            name="ck_outbox_events_status",
        ),
        CheckConstraint("event_version > 0", name="ck_outbox_events_version_positive"),
        CheckConstraint("attempt_count >= 0", name="ck_outbox_events_attempts_nonnegative"),
        CheckConstraint(
            "(processing_status = 'PROCESSED' AND processed_at IS NOT NULL) OR "
            "(processing_status <> 'PROCESSED' AND processed_at IS NULL)",
            name="ck_outbox_events_processed_timestamp",
        ),
        CheckConstraint(
            "(processing_status = 'PROCESSING' AND processing_started_at IS NOT NULL "
            "AND processing_token IS NOT NULL) OR "
            "(processing_status <> 'PROCESSING' AND processing_started_at IS NULL "
            "AND processing_token IS NULL)",
            name="ck_outbox_events_processing_lease",
        ),
        UniqueConstraint("deduplication_key", name="uq_outbox_events_deduplication_key"),
        UniqueConstraint("related_transaction_id", name="uq_outbox_events_transaction"),
        Index("ix_outbox_events_status_created", "processing_status", "created_at"),
        Index("ix_outbox_events_type_created", "event_type", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_system: Mapped[str] = mapped_column(String(80), nullable=False)
    related_transaction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("transactions.id"), nullable=False
    )
    deduplication_key: Mapped[str] = mapped_column(String(160), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processing_status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="PENDING", server_default=text("'PENDING'")
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # A lease makes abandoned PROCESSING events recoverable after worker crashes.
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processing_token: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )

    transaction: Mapped[Transaction] = relationship()

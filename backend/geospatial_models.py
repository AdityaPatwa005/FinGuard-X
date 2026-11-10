"""Synthetic geospatial events tied to persisted simulator activity."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    JSON,
    Numeric,
    String,
    Uuid,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from incident_models import SecurityIncident
from models import Account, Base
from transaction_models import Transaction


class GeospatialEvent(Base):
    __tablename__ = "geospatial_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('LOGIN_LOCATION', 'TRANSACTION_ORIGIN', "
            "'BENEFICIARY_LOCATION', 'TRANSACTION_ROUTE')",
            name="ck_geospatial_events_type",
        ),
        CheckConstraint(
            "(latitude IS NULL AND longitude IS NULL) OR "
            "(latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180)",
            name="ck_geospatial_events_coordinate_bounds",
        ),
        CheckConstraint(
            "(event_type = 'TRANSACTION_ROUTE' AND latitude IS NULL AND longitude IS NULL "
            "AND transaction_id IS NOT NULL AND origin_event_id IS NOT NULL "
            "AND destination_event_id IS NOT NULL AND origin_event_id <> destination_event_id "
            "AND origin_event_type = 'TRANSACTION_ORIGIN' "
            "AND destination_event_type = 'BENEFICIARY_LOCATION') OR "
            "(event_type = 'LOGIN_LOCATION' AND latitude IS NOT NULL AND longitude IS NOT NULL "
            "AND account_id IS NOT NULL AND origin_event_id IS NULL AND destination_event_id IS NULL "
            "AND origin_event_type IS NULL AND destination_event_type IS NULL) OR "
            "(event_type IN ('TRANSACTION_ORIGIN', 'BENEFICIARY_LOCATION') "
            "AND latitude IS NOT NULL AND longitude IS NOT NULL AND account_id IS NOT NULL "
            "AND transaction_id IS NOT NULL AND origin_event_id IS NULL AND destination_event_id IS NULL "
            "AND origin_event_type IS NULL AND destination_event_type IS NULL)",
            name="ck_geospatial_events_shape",
        ),
        UniqueConstraint("deduplication_key", name="uq_geospatial_events_deduplication_key"),
        UniqueConstraint("id", "event_type", name="uq_geospatial_events_id_type"),
        ForeignKeyConstraint(
            ["origin_event_id", "origin_event_type"],
            ["geospatial_events.id", "geospatial_events.event_type"],
            ondelete="RESTRICT",
            name="fk_geospatial_events_origin_location_type",
        ),
        ForeignKeyConstraint(
            ["destination_event_id", "destination_event_type"],
            ["geospatial_events.id", "geospatial_events.event_type"],
            ondelete="RESTRICT",
            name="fk_geospatial_events_destination_location_type",
        ),
        Index("ix_geospatial_events_type_time", "event_type", "event_at"),
        Index("ix_geospatial_events_transaction", "transaction_id"),
        Index("ix_geospatial_events_incident_time", "incident_id", "event_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deduplication_key: Mapped[str] = mapped_column(String(180), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True
    )
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("transactions.id", ondelete="RESTRICT"), nullable=True
    )
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("security_incidents.id", ondelete="SET NULL"), nullable=True
    )
    origin_event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    destination_event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    origin_event_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    destination_event_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    account: Mapped[Account | None] = relationship()
    transaction: Mapped[Transaction | None] = relationship()
    incident: Mapped[SecurityIncident | None] = relationship()
    origin_event: Mapped["GeospatialEvent | None"] = relationship(
        remote_side="GeospatialEvent.id", foreign_keys=[origin_event_id]
    )
    destination_event: Mapped["GeospatialEvent | None"] = relationship(
        remote_side="GeospatialEvent.id", foreign_keys=[destination_event_id]
    )

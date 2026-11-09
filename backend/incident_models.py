"""Durable rule evaluations, incidents, and lifecycle audit records."""

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
    Text,
    Uuid,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models import Account, Base
from transaction_models import Transaction


class SecurityIncident(Base):
    __tablename__ = "security_incidents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN', 'INVESTIGATING', 'RESOLVED', 'DISMISSED')",
            name="ck_security_incidents_status",
        ),
        CheckConstraint("risk_score BETWEEN 0 AND 100", name="ck_security_incidents_risk_score"),
        CheckConstraint(
            "risk_band IN ('LOW', 'GUARDED', 'ELEVATED', 'CRITICAL')",
            name="ck_security_incidents_risk_band",
        ),
        CheckConstraint(
            "(status IN ('RESOLVED', 'DISMISSED') AND closed_at IS NOT NULL) OR "
            "(status IN ('OPEN', 'INVESTIGATING') AND closed_at IS NULL)",
            name="ck_security_incidents_closed_at",
        ),
        Index("ix_security_incidents_account_status_activity", "primary_account_id", "status", "last_activity_at"),
        Index("ix_security_incidents_status_activity", "status", "last_activity_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    primary_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    anchor_transaction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("transactions.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="OPEN", server_default=text("'OPEN'")
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    risk_score: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    risk_band: Mapped[str] = mapped_column(
        String(12), nullable=False, default="LOW", server_default=text("'LOW'")
    )
    risk_policy_version: Mapped[str] = mapped_column(
        String(24), nullable=False, default="1.0", server_default=text("'1.0'")
    )
    risk_explanation: Mapped[str] = mapped_column(
        Text, nullable=False, default="No triggered evidence.", server_default=text("'No triggered evidence.'")
    )
    risk_evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    primary_account: Mapped[Account] = relationship()
    anchor_transaction: Mapped[Transaction] = relationship()
    evaluations: Mapped[list["RuleEvaluationRecord"]] = relationship(
        back_populates="incident"
    )
    lifecycle_events: Mapped[list["IncidentLifecycleEvent"]] = relationship(
        back_populates="incident"
    )


class RuleEvaluationRecord(Base):
    __tablename__ = "rule_evaluations"
    __table_args__ = (
        CheckConstraint(
            "evaluation_outcome IN ('TRIGGERED', 'NOT_TRIGGERED', 'NOT_EVALUATED')",
            name="ck_rule_evaluations_outcome",
        ),
        CheckConstraint(
            "severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
            name="ck_rule_evaluations_severity",
        ),
        UniqueConstraint(
            "transaction_id", "rule_id", "rule_version",
            name="uq_rule_evaluations_transaction_rule_version",
        ),
        Index("ix_rule_evaluations_account_detected", "relevant_account_id", "detected_at"),
        Index("ix_rule_evaluations_incident", "incident_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    rule_id: Mapped[str] = mapped_column(String(100), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_name: Mapped[str] = mapped_column(String(160), nullable=False)
    rule_description: Mapped[str] = mapped_column(Text, nullable=False)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("transactions.id"), nullable=False
    )
    relevant_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    severity: Mapped[str] = mapped_column(String(12), nullable=False)
    evaluation_outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    required_features: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    minimum_history: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    limitation: Mapped[str | None] = mapped_column(Text, nullable=True)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("security_incidents.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    transaction: Mapped[Transaction] = relationship()
    relevant_account: Mapped[Account] = relationship()
    incident: Mapped[SecurityIncident | None] = relationship(back_populates="evaluations")


class IncidentLifecycleEvent(Base):
    __tablename__ = "incident_lifecycle_events"
    __table_args__ = (
        CheckConstraint(
            "from_status IS NULL OR from_status IN ('OPEN', 'INVESTIGATING', 'RESOLVED', 'DISMISSED')",
            name="ck_incident_lifecycle_from_status",
        ),
        CheckConstraint(
            "to_status IN ('OPEN', 'INVESTIGATING', 'RESOLVED', 'DISMISSED')",
            name="ck_incident_lifecycle_to_status",
        ),
        Index("ix_incident_lifecycle_incident_changed", "incident_id", "changed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("security_incidents.id"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_identifier: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    incident: Mapped[SecurityIncident] = relationship(back_populates="lifecycle_events")

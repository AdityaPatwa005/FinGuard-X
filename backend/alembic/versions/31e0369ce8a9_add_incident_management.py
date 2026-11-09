"""add incident management

Revision ID: 31e0369ce8a9
Revises: 1332a150f950
Create Date: 2026-11-10 00:49:41.636173

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '31e0369ce8a9'
down_revision: Union[str, Sequence[str], None] = '1332a150f950'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "security_incidents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("primary_account_id", sa.Uuid(), nullable=False),
        sa.Column("anchor_transaction_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'OPEN'"), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("risk_score", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("risk_band", sa.String(length=12), server_default=sa.text("'LOW'"), nullable=False),
        sa.Column("risk_policy_version", sa.String(length=24), server_default=sa.text("'1.0'"), nullable=False),
        sa.Column("risk_explanation", sa.Text(), server_default=sa.text("'No triggered evidence.'"), nullable=False),
        sa.Column("risk_evidence", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('OPEN', 'INVESTIGATING', 'RESOLVED', 'DISMISSED')", name="ck_security_incidents_status"),
        sa.CheckConstraint("risk_score BETWEEN 0 AND 100", name="ck_security_incidents_risk_score"),
        sa.CheckConstraint("risk_band IN ('LOW', 'GUARDED', 'ELEVATED', 'CRITICAL')", name="ck_security_incidents_risk_band"),
        sa.CheckConstraint(
            "(status IN ('RESOLVED', 'DISMISSED') AND closed_at IS NOT NULL) OR "
            "(status IN ('OPEN', 'INVESTIGATING') AND closed_at IS NULL)",
            name="ck_security_incidents_closed_at",
        ),
        sa.ForeignKeyConstraint(["primary_account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["anchor_transaction_id"], ["transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_security_incidents_account_status_activity", "security_incidents",
        ["primary_account_id", "status", "last_activity_at"], unique=False,
    )
    op.create_index(
        "ix_security_incidents_status_activity", "security_incidents",
        ["status", "last_activity_at"], unique=False,
    )

    op.create_table(
        "rule_evaluations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.String(length=100), nullable=False),
        sa.Column("rule_version", sa.String(length=32), nullable=False),
        sa.Column("rule_name", sa.String(length=160), nullable=False),
        sa.Column("rule_description", sa.Text(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("relevant_account_id", sa.Uuid(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("severity", sa.String(length=12), nullable=False),
        sa.Column("evaluation_outcome", sa.String(length=16), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("required_features", sa.JSON(), nullable=False),
        sa.Column("minimum_history", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("limitation", sa.Text(), nullable=True),
        sa.Column("incident_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "evaluation_outcome IN ('TRIGGERED', 'NOT_TRIGGERED', 'NOT_EVALUATED')",
            name="ck_rule_evaluations_outcome",
        ),
        sa.CheckConstraint("severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')", name="ck_rule_evaluations_severity"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.ForeignKeyConstraint(["relevant_account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["incident_id"], ["security_incidents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "transaction_id", "rule_id", "rule_version",
            name="uq_rule_evaluations_transaction_rule_version",
        ),
    )
    op.create_index(
        "ix_rule_evaluations_account_detected", "rule_evaluations",
        ["relevant_account_id", "detected_at"], unique=False,
    )
    op.create_index("ix_rule_evaluations_incident", "rule_evaluations", ["incident_id"], unique=False)

    op.create_table(
        "incident_lifecycle_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(length=16), nullable=True),
        sa.Column("to_status", sa.String(length=16), nullable=False),
        sa.Column("actor_identifier", sa.String(length=120), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN ('OPEN', 'INVESTIGATING', 'RESOLVED', 'DISMISSED')",
            name="ck_incident_lifecycle_from_status",
        ),
        sa.CheckConstraint(
            "to_status IN ('OPEN', 'INVESTIGATING', 'RESOLVED', 'DISMISSED')",
            name="ck_incident_lifecycle_to_status",
        ),
        sa.ForeignKeyConstraint(["incident_id"], ["security_incidents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_incident_lifecycle_incident_changed", "incident_lifecycle_events",
        ["incident_id", "changed_at"], unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_incident_lifecycle_incident_changed", table_name="incident_lifecycle_events")
    op.drop_table("incident_lifecycle_events")
    op.drop_index("ix_rule_evaluations_incident", table_name="rule_evaluations")
    op.drop_index("ix_rule_evaluations_account_detected", table_name="rule_evaluations")
    op.drop_table("rule_evaluations")
    op.drop_index("ix_security_incidents_status_activity", table_name="security_incidents")
    op.drop_index("ix_security_incidents_account_status_activity", table_name="security_incidents")
    op.drop_table("security_incidents")

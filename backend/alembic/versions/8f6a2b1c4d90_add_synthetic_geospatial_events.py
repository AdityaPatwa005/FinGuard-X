"""add synthetic geospatial events

Revision ID: 8f6a2b1c4d90
Revises: 31e0369ce8a9
Create Date: 2026-11-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8f6a2b1c4d90"
down_revision: Union[str, Sequence[str], None] = "31e0369ce8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "geospatial_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("deduplication_key", sa.String(length=180), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("transaction_id", sa.Uuid(), nullable=True),
        sa.Column("incident_id", sa.Uuid(), nullable=True),
        sa.Column("origin_event_id", sa.Uuid(), nullable=True),
        sa.Column("destination_event_id", sa.Uuid(), nullable=True),
        sa.Column("origin_event_type", sa.String(length=32), nullable=True),
        sa.Column("destination_event_type", sa.String(length=32), nullable=True),
        sa.Column("latitude", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("longitude", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('LOGIN_LOCATION', 'TRANSACTION_ORIGIN', 'BENEFICIARY_LOCATION', 'TRANSACTION_ROUTE')",
            name="ck_geospatial_events_type",
        ),
        sa.CheckConstraint(
            "(latitude IS NULL AND longitude IS NULL) OR "
            "(latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180)",
            name="ck_geospatial_events_coordinate_bounds",
        ),
        sa.CheckConstraint(
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
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["incident_id"], ["security_incidents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["origin_event_id", "origin_event_type"], ["geospatial_events.id", "geospatial_events.event_type"],
            ondelete="RESTRICT", name="fk_geospatial_events_origin_location_type",
        ),
        sa.ForeignKeyConstraint(
            ["destination_event_id", "destination_event_type"], ["geospatial_events.id", "geospatial_events.event_type"],
            ondelete="RESTRICT", name="fk_geospatial_events_destination_location_type",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("deduplication_key", name="uq_geospatial_events_deduplication_key"),
        sa.UniqueConstraint("id", "event_type", name="uq_geospatial_events_id_type"),
    )
    op.create_index("ix_geospatial_events_type_time", "geospatial_events", ["event_type", "event_at"])
    op.create_index("ix_geospatial_events_transaction", "geospatial_events", ["transaction_id"])
    op.create_index("ix_geospatial_events_incident_time", "geospatial_events", ["incident_id", "event_at"])


def downgrade() -> None:
    op.drop_index("ix_geospatial_events_incident_time", table_name="geospatial_events")
    op.drop_index("ix_geospatial_events_transaction", table_name="geospatial_events")
    op.drop_index("ix_geospatial_events_type_time", table_name="geospatial_events")
    op.drop_table("geospatial_events")

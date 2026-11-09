"""add simulator transactions and ledger entries

Revision ID: 27c572d3f9de
Revises: c2be55dbccc4
Create Date: 2026-11-09 05:46:39.593534

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '27c572d3f9de'
down_revision: Union[str, Sequence[str], None] = 'c2be55dbccc4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sender_account_id", sa.Uuid(), nullable=True),
        sa.Column("receiver_account_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_type", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'INR'"), nullable=False),
        sa.Column("status", sa.String(length=12), server_default=sa.text("'PENDING'"), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("transaction_type IN ('FUNDING', 'TRANSFER')", name="ck_transactions_type"),
        sa.CheckConstraint("status IN ('PENDING', 'COMPLETED', 'FAILED')", name="ck_transactions_status"),
        sa.CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        sa.CheckConstraint("currency = 'INR'", name="ck_transactions_currency_inr"),
        sa.CheckConstraint(
            "(transaction_type = 'FUNDING' AND sender_account_id IS NULL AND receiver_account_id IS NOT NULL) OR "
            "(transaction_type = 'TRANSFER' AND sender_account_id IS NOT NULL AND receiver_account_id IS NOT NULL AND sender_account_id <> receiver_account_id)",
            name="ck_transactions_account_shape",
        ),
        sa.ForeignKeyConstraint(["sender_account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["receiver_account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_transactions_idempotency_key"),
    )
    op.create_index("ix_transactions_sender_account_id", "transactions", ["sender_account_id"])
    op.create_index("ix_transactions_receiver_account_id", "transactions", ["receiver_account_id"])
    op.create_index("ix_transactions_status_created_at", "transactions", ["status", "created_at"])

    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("ledger_account_id", sa.Uuid(), nullable=False),
        sa.Column("entry_type", sa.String(length=6), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'INR'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("entry_type IN ('DEBIT', 'CREDIT')", name="ck_ledger_entries_type"),
        sa.CheckConstraint("amount > 0", name="ck_ledger_entries_amount_positive"),
        sa.CheckConstraint("currency = 'INR'", name="ck_ledger_entries_currency_inr"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.ForeignKeyConstraint(["ledger_account_id"], ["ledger_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_id", "entry_type", name="uq_ledger_entries_transaction_type"),
    )
    op.create_index("ix_ledger_entries_ledger_account_id", "ledger_entries", ["ledger_account_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_ledger_entries_ledger_account_id", table_name="ledger_entries")
    op.drop_table("ledger_entries")
    op.drop_index("ix_transactions_status_created_at", table_name="transactions")
    op.drop_index("ix_transactions_receiver_account_id", table_name="transactions")
    op.drop_index("ix_transactions_sender_account_id", table_name="transactions")
    op.drop_table("transactions")

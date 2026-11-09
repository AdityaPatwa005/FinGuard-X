import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Uuid,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ledger_models import LedgerAccount
from models import Account, Base


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("transaction_type IN ('FUNDING', 'TRANSFER')", name="ck_transactions_type"),
        CheckConstraint("status IN ('PENDING', 'COMPLETED', 'FAILED')", name="ck_transactions_status"),
        CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        CheckConstraint("currency = 'INR'", name="ck_transactions_currency_inr"),
        CheckConstraint(
            "(transaction_type = 'FUNDING' AND sender_account_id IS NULL AND receiver_account_id IS NOT NULL) OR "
            "(transaction_type = 'TRANSFER' AND sender_account_id IS NOT NULL AND receiver_account_id IS NOT NULL AND sender_account_id <> receiver_account_id)",
            name="ck_transactions_account_shape",
        ),
        UniqueConstraint("idempotency_key", name="uq_transactions_idempotency_key"),
        Index("ix_transactions_sender_account_id", "sender_account_id"),
        Index("ix_transactions_receiver_account_id", "receiver_account_id"),
        Index("ix_transactions_status_created_at", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sender_account_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id"), nullable=True
    )
    receiver_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    transaction_type: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="INR", server_default=text("'INR'")
    )
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="PENDING", server_default=text("'PENDING'")
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    sender_account: Mapped[Account | None] = relationship(foreign_keys=[sender_account_id])
    receiver_account: Mapped[Account] = relationship(foreign_keys=[receiver_account_id])
    ledger_entries: Mapped[list["LedgerEntry"]] = relationship(back_populates="transaction")


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        CheckConstraint("entry_type IN ('DEBIT', 'CREDIT')", name="ck_ledger_entries_type"),
        CheckConstraint("amount > 0", name="ck_ledger_entries_amount_positive"),
        CheckConstraint("currency = 'INR'", name="ck_ledger_entries_currency_inr"),
        UniqueConstraint("transaction_id", "entry_type", name="uq_ledger_entries_transaction_type"),
        Index("ix_ledger_entries_ledger_account_id", "ledger_account_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("transactions.id"), nullable=False
    )
    ledger_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ledger_accounts.id"), nullable=False
    )
    entry_type: Mapped[str] = mapped_column(String(6), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="INR", server_default=text("'INR'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    transaction: Mapped[Transaction] = relationship(back_populates="ledger_entries")
    ledger_account: Mapped[LedgerAccount] = relationship()

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models import Account, Base


class LedgerAccount(Base):
    __tablename__ = "ledger_accounts"
    __table_args__ = (
        CheckConstraint(
            "account_type IN ('CUSTOMER', 'FUNDING_POOL')",
            name="ck_ledger_accounts_account_type",
        ),
        CheckConstraint(
            "(account_type = 'CUSTOMER' AND bank_account_id IS NOT NULL) OR "
            "(account_type = 'FUNDING_POOL' AND bank_account_id IS NULL)",
            name="ck_ledger_accounts_type_bank_account",
        ),
        Index(
            "uq_ledger_accounts_bank_account_id",
            "bank_account_id",
            unique=True,
            postgresql_where=text("bank_account_id IS NOT NULL"),
            sqlite_where=text("bank_account_id IS NOT NULL"),
        ),
        Index(
            "uq_ledger_accounts_single_funding_pool",
            "account_type",
            unique=True,
            postgresql_where=text("account_type = 'FUNDING_POOL'"),
            sqlite_where=text("account_type = 'FUNDING_POOL'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    bank_account_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id"), nullable=True
    )
    account_type: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="INR", server_default=text("'INR'")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    bank_account: Mapped[Account | None] = relationship()

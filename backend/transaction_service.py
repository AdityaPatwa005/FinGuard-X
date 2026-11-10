"""Atomic simulator funding and internal transfer operations."""

import logging
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from ledger_models import LedgerAccount
from models import Account
from outbox_events import add_transaction_completed_event
from schemas import TransactionResponse
from transaction_models import LedgerEntry, Transaction


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TransactionResult:
    transaction: TransactionResponse
    replayed: bool


IDEMPOTENCY_CONSTRAINT = "uq_transactions_idempotency_key"


def integrity_error_metadata(error: IntegrityError) -> tuple[str, str]:
    """Return safe PostgreSQL diagnostics without including SQL or parameters."""
    original = error.orig
    diagnostic = getattr(original, "diag", None)
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    constraint = getattr(diagnostic, "constraint_name", None) or getattr(
        original, "constraint_name", None
    )
    return str(sqlstate or "unknown"), str(constraint or "unknown")


def funding_transaction(
    db: Session,
    *,
    account_id: UUID,
    amount: Decimal,
    idempotency_key: str,
    description: str | None,
) -> TransactionResult:
    return _execute_transaction(
        db,
        transaction_type="FUNDING",
        sender_account_id=None,
        receiver_account_id=account_id,
        amount=amount,
        idempotency_key=idempotency_key,
        description=description,
    )


def transfer_transaction(
    db: Session,
    *,
    sender_account_id: UUID,
    receiver_account_id: UUID,
    amount: Decimal,
    idempotency_key: str,
    description: str | None,
) -> TransactionResult:
    if sender_account_id == receiver_account_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Sender and receiver accounts must be different.",
        )
    return _execute_transaction(
        db,
        transaction_type="TRANSFER",
        sender_account_id=sender_account_id,
        receiver_account_id=receiver_account_id,
        amount=amount,
        idempotency_key=idempotency_key,
        description=description,
    )


def _execute_transaction(
    db: Session,
    *,
    transaction_type: str,
    sender_account_id: UUID | None,
    receiver_account_id: UUID,
    amount: Decimal,
    idempotency_key: str,
    description: str | None,
) -> TransactionResult:
    if not isinstance(amount, Decimal) or amount <= Decimal("0"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Amount must be a positive decimal value.",
        )

    operation_phase = "idempotency_lookup"
    try:
        with db.begin():
            existing = _find_transaction(db, idempotency_key)
            if existing is not None:
                return _replay_or_reject(
                    existing,
                    transaction_type=transaction_type,
                    sender_account_id=sender_account_id,
                    receiver_account_id=receiver_account_id,
                    amount=amount,
                    description=description,
                )

            # Lock and validate referenced rows before inserting Transaction.
            # Otherwise a missing account raises a raw FK IntegrityError before
            # the service can return its intended 404 response.
            operation_phase = "account_lock_and_validation"
            account_ids = [receiver_account_id]
            if sender_account_id is not None:
                account_ids.append(sender_account_id)
            accounts = _lock_accounts(db, account_ids)
            accounts_by_id = {account.id: account for account in accounts}
            if len(accounts_by_id) != len(set(account_ids)):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="One or more customer accounts were not found.",
                )
            if any(account.status.lower() != "active" for account in accounts):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="All customer accounts must be active.",
                )

            customer_ledgers = _lock_customer_ledgers(db, account_ids)
            receiver = accounts_by_id[receiver_account_id]
            receiver_ledger = customer_ledgers[receiver_account_id]

            if transaction_type == "FUNDING":
                operation_phase = "funding_pool_lock"
                funding_pool = db.scalar(
                    select(LedgerAccount)
                    .where(
                        LedgerAccount.account_type == "FUNDING_POOL",
                        LedgerAccount.bank_account_id.is_(None),
                        LedgerAccount.is_active.is_(True),
                    )
                    .with_for_update()
                )
                if funding_pool is None:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="Funding is temporarily unavailable.",
                    )
            else:
                sender = accounts_by_id[sender_account_id]
                sender_ledger = customer_ledgers[sender_account_id]
                if sender.balance < amount:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="The sender account has insufficient funds.",
                    )

            transaction = Transaction(
                sender_account_id=sender_account_id,
                receiver_account_id=receiver_account_id,
                transaction_type=transaction_type,
                amount=amount,
                currency="INR",
                status="PENDING",
                idempotency_key=idempotency_key,
                description=description,
            )
            db.add(transaction)
            # Claim the unique idempotency key before changing balances.
            operation_phase = "transaction_insert"
            db.flush()

            if transaction_type == "FUNDING":
                receiver.balance = receiver.balance + amount
                entries = [
                    LedgerEntry(
                        transaction_id=transaction.id,
                        ledger_account_id=funding_pool.id,
                        entry_type="DEBIT",
                        amount=amount,
                        currency="INR",
                    ),
                    LedgerEntry(
                        transaction_id=transaction.id,
                        ledger_account_id=receiver_ledger.id,
                        entry_type="CREDIT",
                        amount=amount,
                        currency="INR",
                    ),
                ]
            else:
                sender.balance = sender.balance - amount
                receiver.balance = receiver.balance + amount
                entries = [
                    LedgerEntry(
                        transaction_id=transaction.id,
                        ledger_account_id=sender_ledger.id,
                        entry_type="DEBIT",
                        amount=amount,
                        currency="INR",
                    ),
                    LedgerEntry(
                        transaction_id=transaction.id,
                        ledger_account_id=receiver_ledger.id,
                        entry_type="CREDIT",
                        amount=amount,
                        currency="INR",
                    ),
                ]

            transaction.ledger_entries.extend(entries)
            transaction.status = "COMPLETED"
            operation_phase = "ledger_entry_flush"
            db.flush()
            db.refresh(transaction)
            # The outbox insert is part of this transaction: either both the
            # financial operation and its event commit, or neither does.
            operation_phase = "outbox_event_creation"
            add_transaction_completed_event(db, transaction)
            operation_phase = "outbox_event_flush"
            db.flush()
            response = TransactionResponse.model_validate(transaction)
            operation_phase = "commit"
            return TransactionResult(transaction=response, replayed=False)

    except IntegrityError as error:
        db.rollback()
        sqlstate, constraint = integrity_error_metadata(error)
        if constraint == IDEMPOTENCY_CONSTRAINT:
            # A concurrent request may claim the key after our initial lookup.
            try:
                existing = _find_transaction(db, idempotency_key)
                if existing is not None:
                    return _replay_or_reject(
                        existing,
                        transaction_type=transaction_type,
                        sender_account_id=sender_account_id,
                        receiver_account_id=receiver_account_id,
                        amount=amount,
                        description=description,
                    )
            finally:
                db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An idempotency conflict occurred. Verify the request key and try again.",
            ) from None

        logger.error(
            "Simulator transaction integrity failure: operation=%s phase=%s sqlstate=%s constraint=%s",
            transaction_type,
            operation_phase,
            sqlstate,
            constraint,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The transaction could not be completed because of a data integrity error.",
        ) from None
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Simulator transaction failed; database transaction rolled back.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The transaction could not be completed. No changes were applied.",
        ) from None


def _find_transaction(db: Session, idempotency_key: str) -> Transaction | None:
    return db.scalar(
        select(Transaction)
        .options(selectinload(Transaction.ledger_entries))
        .where(Transaction.idempotency_key == idempotency_key)
    )


def _replay_or_reject(
    existing: Transaction,
    *,
    transaction_type: str,
    sender_account_id: UUID | None,
    receiver_account_id: UUID,
    amount: Decimal,
    description: str | None,
) -> TransactionResult:
    matches_request = (
        existing.transaction_type == transaction_type
        and existing.sender_account_id == sender_account_id
        and existing.receiver_account_id == receiver_account_id
        and existing.amount == amount
        and existing.currency == "INR"
        and existing.description == description
    )
    if not matches_request or existing.status != "COMPLETED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This idempotency key is already associated with a different request.",
        )
    return TransactionResult(
        transaction=TransactionResponse.model_validate(existing), replayed=True
    )


def _lock_accounts(db: Session, account_ids: list[UUID]) -> list[Account]:
    """Lock accounts in a stable order to reduce deadlock risk."""
    return list(db.scalars(account_lock_statement(account_ids)).all())


def account_lock_statement(account_ids: list[UUID]):
    """Return the deterministic row-lock query used for customer balances."""
    return (
        select(Account)
        .where(Account.id.in_(set(account_ids)))
        .order_by(Account.id)
        .with_for_update()
    )


def _lock_customer_ledgers(
    db: Session, account_ids: list[UUID]
) -> dict[UUID, LedgerAccount]:
    ledgers = db.scalars(
        select(LedgerAccount)
        .where(
            LedgerAccount.bank_account_id.in_(set(account_ids)),
            LedgerAccount.account_type == "CUSTOMER",
        )
        .order_by(LedgerAccount.bank_account_id)
        .with_for_update()
    ).all()
    by_account_id = {ledger.bank_account_id: ledger for ledger in ledgers}
    if len(by_account_id) != len(set(account_ids)):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A customer ledger account is not initialized.",
        )
    return by_account_id

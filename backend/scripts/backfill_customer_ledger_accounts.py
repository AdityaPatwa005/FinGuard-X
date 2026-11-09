"""Backfill CUSTOMER ledger accounts for existing bank accounts.

Run from the backend directory with:
    python -m scripts.backfill_customer_ledger_accounts
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from database import SessionLocal
from ledger_models import LedgerAccount
from models import Account


logger = logging.getLogger(__name__)


def backfill_customer_ledger_accounts(session: Session) -> tuple[int, int, int, int]:
    """Insert missing CUSTOMER ledger rows; return total, missing, inserted, skipped."""
    account_rows = session.execute(
        select(Account.id, Account.account_number, LedgerAccount.id)
        .outerjoin(LedgerAccount, LedgerAccount.bank_account_id == Account.id)
        .order_by(Account.id)
    ).all()

    missing_accounts = [
        (account_id, account_number)
        for account_id, account_number, ledger_account_id in account_rows
        if ledger_account_id is None
    ]
    if not missing_accounts:
        return len(account_rows), 0, 0, len(account_rows)

    # Assign each row's UUID explicitly so each value in the multi-row INSERT
    # gets a distinct primary key. Other fields use the model/server defaults.
    ledger_rows = [
        {
            "id": uuid.uuid4(),
            "bank_account_id": account_id,
            "account_type": "CUSTOMER",
            "name": f"Customer ledger {account_number}",
        }
        for account_id, account_number in missing_accounts
    ]

    statement = (
        insert(LedgerAccount)
        .values(ledger_rows)
        .on_conflict_do_nothing(
            index_elements=[LedgerAccount.bank_account_id],
            index_where=LedgerAccount.bank_account_id.is_not(None),
        )
        .returning(LedgerAccount.bank_account_id)
    )
    inserted_account_ids = session.execute(statement).scalars().all()
    inserted_count = len(inserted_account_ids)
    total_count = len(account_rows)
    skipped_count = total_count - inserted_count
    return total_count, len(missing_accounts), inserted_count, skipped_count


def run_backfill() -> tuple[int, int, int, int]:
    """Run the complete backfill in one transaction."""
    with SessionLocal.begin() as session:
        return backfill_customer_ledger_accounts(session)


def main() -> int:
    try:
        total_count, missing_count, inserted_count, skipped_count = run_backfill()
    except Exception as error:
        # SessionLocal.begin() rolls back the entire batch if an error escapes.
        logger.error(
            "Customer ledger backfill failed; transaction rolled back (%s).",
            type(error).__name__,
        )
        logger.debug("Backfill failure details", exc_info=True)
        return 1

    logger.info(
        "Customer ledger backfill complete: %d checked, %d missing before insert, "
        "%d ledger accounts inserted, %d skipped (already linked or conflict ignored).",
        total_count,
        missing_count,
        inserted_count,
        skipped_count,
    )
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    raise SystemExit(main())

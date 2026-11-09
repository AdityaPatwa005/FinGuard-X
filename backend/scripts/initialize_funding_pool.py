"""Create the single FinBank Simulator funding-pool ledger account if absent.

Run from the backend directory with:
    python -m scripts.initialize_funding_pool
"""

import logging
import uuid

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from database import SessionLocal
from ledger_models import LedgerAccount


logger = logging.getLogger(__name__)
FUNDING_POOL_NAME = "FinBank Simulator Funding Pool"


def ensure_funding_pool(session: Session) -> bool:
    """Insert the funding pool once; return True only when this call inserted it."""
    statement = (
        insert(LedgerAccount)
        .values(
            id=uuid.uuid4(),
            bank_account_id=None,
            account_type="FUNDING_POOL",
            name=FUNDING_POOL_NAME,
        )
        .on_conflict_do_nothing(
            index_elements=[LedgerAccount.account_type],
            index_where=text("account_type = 'FUNDING_POOL'"),
        )
        .returning(LedgerAccount.id)
    )
    inserted_id = session.execute(statement).scalar_one_or_none()
    return inserted_id is not None


def run_initialization() -> bool:
    """Initialize the funding pool in one transaction."""
    with SessionLocal.begin() as session:
        return ensure_funding_pool(session)


def main() -> int:
    try:
        was_created = run_initialization()
    except Exception as error:
        # SessionLocal.begin() rolls back if insertion or commit fails.
        logger.error(
            "Funding-pool initialization failed; transaction rolled back (%s).",
            type(error).__name__,
        )
        logger.debug("Funding-pool initialization failure details", exc_info=True)
        return 1

    if was_created:
        logger.info("Created the single funding-pool ledger account: %s.", FUNDING_POOL_NAME)
    else:
        logger.info("Funding-pool ledger account already exists; no changes made.")
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    raise SystemExit(main())

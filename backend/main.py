

import secrets

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from database import engine, get_db
from ledger_models import LedgerAccount
from models import Account, User
from schemas import (
    CustomerCreate,
    CustomerResponse,
    FundingRequest,
    TransactionResponse,
    TransferRequest,
)
from transaction_service import funding_transaction, transfer_transaction

app = FastAPI(
    title="FinGuard X API",
    description="Financial Cybersecurity Intelligence Platform",
    version="0.1.0",
)


def generate_account_number(db: Session) -> str:
    """Generate an account number not currently present in the database."""
    while True:
        account_number = f"FG{secrets.randbelow(10**16):016d}"
        existing_account = db.scalar(
            select(Account.id).where(Account.account_number == account_number)
        )
        if existing_account is None:
            return account_number


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "application": "FinGuard X",
        "environment": "development"
    }


@app.post(
    "/customers",
    response_model=CustomerResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_customer(payload: CustomerCreate, db: Session = Depends(get_db)):
    try:
        with db.begin():
            existing_user = db.scalar(
                select(User.id).where(User.email == payload.email)
            )
            if existing_user is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A customer with this email already exists.",
                )

            user = User(full_name=payload.full_name, email=payload.email)
            account = Account(
                account_number=generate_account_number(db),
                account_type="savings",
            )
            user.accounts.append(account)
            db.add(user)
            db.flush()

            ledger_account = LedgerAccount(
                bank_account_id=account.id,
                account_type="CUSTOMER",
                name=f"Customer ledger {account.account_number}",
            )
            db.add(ledger_account)
            db.flush()

        db.refresh(user)
        db.refresh(account)
        return CustomerResponse.model_validate(
            {
                "id": user.id,
                "full_name": user.full_name,
                "email": user.email,
                "account": account,
            }
        )
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A customer with this email or account number already exists.",
        ) from None


IdempotencyHeader = Header(
    ...,
    alias="Idempotency-Key",
    min_length=1,
    max_length=128,
    pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    description="Unique request key; reuse the same key only when retrying the same operation.",
)


@app.post(
    "/transactions/funding",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": TransactionResponse, "description": "Idempotent replay"}},
    summary="Fund a customer account from the simulator funding pool",
    description=(
        "Moves synthetic INR from the single FinBank Simulator funding pool to an active "
        "customer account. Requires an Idempotency-Key header. This is a simulator operation; "
        "it does not connect to an external payment network."
    ),
)
def fund_customer_account(
    payload: FundingRequest,
    response: Response,
    idempotency_key: str = IdempotencyHeader,
    db: Session = Depends(get_db),
):
    result = funding_transaction(
        db,
        account_id=payload.account_id,
        amount=payload.amount,
        idempotency_key=idempotency_key,
        description=payload.description,
    )
    if result.replayed:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotency-Replayed"] = "true"
    return result.transaction


@app.post(
    "/transactions/transfers",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": TransactionResponse, "description": "Idempotent replay"}},
    summary="Transfer synthetic funds between customer accounts",
    description=(
        "Moves synthetic INR between two active FinBank Simulator customer accounts. "
        "Requires an Idempotency-Key header. Debits, credits and cached balances are committed atomically."
    ),
)
def transfer_between_accounts(
    payload: TransferRequest,
    response: Response,
    idempotency_key: str = IdempotencyHeader,
    db: Session = Depends(get_db),
):
    result = transfer_transaction(
        db,
        sender_account_id=payload.sender_account_id,
        receiver_account_id=payload.receiver_account_id,
        amount=payload.amount,
        idempotency_key=idempotency_key,
        description=payload.description,
    )
    if result.replayed:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotency-Replayed"] = "true"
    return result.transaction


@app.get("/health/database")
def database_health_check():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        return {
            "status": "healthy",
            "database": "connected"
        }

    except SQLAlchemyError:
        return {
            "status": "unhealthy",
            "database": "disconnected"
        }

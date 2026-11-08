

import secrets

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from database import engine, get_db
from models import Account, User
from schemas import CustomerCreate, CustomerResponse

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

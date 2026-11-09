

import os
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import case, distinct, func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, aliased

from database import engine, get_db
from incident_models import IncidentLifecycleEvent, RuleEvaluationRecord, SecurityIncident
from incident_service import IncidentTransitionError, transition_incident
from ledger_models import LedgerAccount
from models import Account, User
from schemas import (
    CustomerCreate,
    CustomerResponse,
    DashboardSummaryResponse,
    FundingRequest,
    IncidentDetailResponse,
    IncidentListResponse,
    IncidentNoteRequest,
    IncidentStatusUpdateRequest,
    RecentDetectionResponse,
    RecentTransactionResponse,
    TransactionResponse,
    TransferRequest,
)
from transaction_models import Transaction
from transaction_service import funding_transaction, transfer_transaction

app = FastAPI(
    title="FinGuard X API",
    description="Financial Cybersecurity Intelligence Platform",
    version="0.1.0",
)

allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "FINGUARD_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type"],
)


RISK_BAND_ORDER = {"LOW": 1, "GUARDED": 2, "ELEVATED": 3, "CRITICAL": 4}


def _masked_account(account_number: str | None) -> str:
    return f"Account ••{account_number[-4:]}" if account_number else "Funding pool"


def _evidence_response(evidence: list[dict]) -> list[dict]:
    # Rule evidence values are scalar measurements; Decimal values were stored
    # as exact strings by the detection persistence layer.
    return [
        {"name": item.get("name", "Evidence"), "value": item.get("value", "Unavailable"), "unit": item.get("unit")}
        for item in evidence
    ]


def _incident_detail(db: Session, incident: SecurityIncident) -> dict:
    account_number = db.scalar(
        select(Account.account_number).where(Account.id == incident.primary_account_id)
    )
    evaluations = db.scalars(
        select(RuleEvaluationRecord)
        .where(RuleEvaluationRecord.incident_id == incident.id)
        .order_by(RuleEvaluationRecord.detected_at.desc(), RuleEvaluationRecord.id)
    ).all()
    transactions = db.scalars(
        select(Transaction)
        .join(RuleEvaluationRecord, RuleEvaluationRecord.transaction_id == Transaction.id)
        .where(RuleEvaluationRecord.incident_id == incident.id)
        .distinct()
        .order_by(Transaction.created_at.desc(), Transaction.id)
    ).all()
    timeline = db.scalars(
        select(IncidentLifecycleEvent)
        .where(IncidentLifecycleEvent.incident_id == incident.id)
        .order_by(IncidentLifecycleEvent.changed_at, IncidentLifecycleEvent.id)
    ).all()
    rule_names = sorted({row.rule_name for row in evaluations})
    title = rule_names[0] if rule_names else "Security incident"
    return {
        "id": incident.id,
        "title": title,
        "status": incident.status,
        "risk_score": incident.risk_score,
        "risk_band": incident.risk_band,
        "risk_explanation": incident.risk_explanation,
        "primary_account": _masked_account(account_number),
        "opened_at": incident.opened_at,
        "last_activity_at": incident.last_activity_at,
        "closed_at": incident.closed_at,
        "transaction_count": len(transactions),
        "detection_count": len(evaluations),
        "anchor_transaction_id": incident.anchor_transaction_id,
        "risk_policy_version": incident.risk_policy_version,
        "risk_evidence": incident.risk_evidence,
        "transactions": [
            {
                "id": row.id,
                "transaction_type": row.transaction_type,
                "amount": row.amount,
                "currency": row.currency,
                "status": row.status,
                "created_at": row.created_at,
            }
            for row in transactions
        ],
        "detections": [
            {
                "id": row.id,
                "rule_id": row.rule_id,
                "rule_version": row.rule_version,
                "rule_name": row.rule_name,
                "rule_description": row.rule_description,
                "transaction_id": row.transaction_id,
                "detected_at": row.detected_at,
                "severity": row.severity,
                "outcome": row.evaluation_outcome,
                "explanation": row.explanation,
                "evidence": _evidence_response(row.evidence),
                "limitation": row.limitation,
            }
            for row in evaluations
        ],
        "timeline": [
            {
                "id": row.id,
                "from_status": row.from_status,
                "to_status": row.to_status,
                "actor_identifier": row.actor_identifier,
                "note": row.note,
                "changed_at": row.changed_at,
            }
            for row in timeline
        ],
    }


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


@app.get("/dashboard/summary", response_model=DashboardSummaryResponse)
def dashboard_summary(db: Session = Depends(get_db)):
    period_start = datetime.now(timezone.utc) - timedelta(hours=24)
    monitored = db.scalar(
        select(func.count(Transaction.id)).where(
            Transaction.status == "COMPLETED",
            Transaction.created_at >= period_start,
        )
    ) or 0
    triggered = db.scalar(
        select(func.count(RuleEvaluationRecord.id)).where(
            RuleEvaluationRecord.evaluation_outcome == "TRIGGERED",
            RuleEvaluationRecord.detected_at >= period_start,
        )
    ) or 0
    high_risk_transactions = db.scalar(
        select(func.count(distinct(RuleEvaluationRecord.transaction_id)))
        .join(SecurityIncident, SecurityIncident.id == RuleEvaluationRecord.incident_id)
        .where(
            RuleEvaluationRecord.evaluation_outcome == "TRIGGERED",
            RuleEvaluationRecord.detected_at >= period_start,
            SecurityIncident.risk_score >= 50,
        )
    ) or 0
    active_incidents = db.scalar(
        select(func.count(SecurityIncident.id)).where(
            SecurityIncident.status.in_(("OPEN", "INVESTIGATING"))
        )
    ) or 0
    open_cases = active_incidents
    critical_cases = db.scalar(
        select(func.count(SecurityIncident.id)).where(
            SecurityIncident.status.in_(("OPEN", "INVESTIGATING")),
            SecurityIncident.risk_band == "CRITICAL",
        )
    ) or 0
    awaiting_review = db.scalar(
        select(func.count(SecurityIncident.id)).where(SecurityIncident.status == "OPEN")
    ) or 0
    resolved_cases = db.scalar(
        select(func.count(SecurityIncident.id)).where(SecurityIncident.status == "RESOLVED")
    ) or 0
    distribution_rows = db.execute(
        select(SecurityIncident.risk_band, func.count(SecurityIncident.id))
        .group_by(SecurityIncident.risk_band)
    ).all()
    counts = {band: count for band, count in distribution_rows}
    risk_distribution = [
        {"band": band, "count": counts.get(band, 0)}
        for band in ("LOW", "GUARDED", "ELEVATED", "CRITICAL")
    ]
    return {
        "period_start": period_start,
        "transactions_monitored": monitored,
        "high_risk_transactions": high_risk_transactions,
        "active_incidents": active_incidents,
        "open_cases": open_cases,
        "critical_cases": critical_cases,
        "awaiting_review": awaiting_review,
        "resolved_cases": resolved_cases,
        # The frozen simulator records PENDING/COMPLETED/FAILED only. It does
        # not persist blocked decisions, so report this as unavailable.
        "blocked_transactions": None,
        "blocked_transactions_note": "The simulator does not persist blocked transaction decisions.",
        "triggered_detections": triggered,
        "risk_distribution": risk_distribution,
        "risk_distribution_total": sum(counts.values()),
    }


@app.get("/transactions/recent", response_model=list[RecentTransactionResponse])
def recent_transactions(
    limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db)
):
    sender_account = aliased(Account)
    receiver_account = aliased(Account)
    detection_summary = (
        select(
            RuleEvaluationRecord.transaction_id.label("transaction_id"),
            func.max(SecurityIncident.risk_score).label("risk_score"),
            func.max(
                case(
                    (SecurityIncident.risk_band == "CRITICAL", 4),
                    (SecurityIncident.risk_band == "ELEVATED", 3),
                    (SecurityIncident.risk_band == "GUARDED", 2),
                    else_=1,
                )
            ).label("risk_rank"),
            func.count(RuleEvaluationRecord.id).label("detection_count"),
        )
        .join(SecurityIncident, SecurityIncident.id == RuleEvaluationRecord.incident_id)
        .where(RuleEvaluationRecord.evaluation_outcome == "TRIGGERED")
        .group_by(RuleEvaluationRecord.transaction_id)
        .subquery()
    )
    rows = db.execute(
        select(
            Transaction,
            sender_account.account_number,
            receiver_account.account_number,
            detection_summary.c.risk_score,
            detection_summary.c.risk_rank,
            detection_summary.c.detection_count,
        )
        .outerjoin(sender_account, sender_account.id == Transaction.sender_account_id)
        .join(receiver_account, receiver_account.id == Transaction.receiver_account_id)
        .outerjoin(detection_summary, detection_summary.c.transaction_id == Transaction.id)
        .order_by(Transaction.created_at.desc(), Transaction.id)
        .limit(limit)
    ).all()
    transaction_ids = [row[0].id for row in rows]
    detection_rows = db.execute(
        select(RuleEvaluationRecord, SecurityIncident.risk_score, SecurityIncident.risk_band)
        .outerjoin(SecurityIncident, SecurityIncident.id == RuleEvaluationRecord.incident_id)
        .where(
            RuleEvaluationRecord.transaction_id.in_(transaction_ids),
            RuleEvaluationRecord.evaluation_outcome == "TRIGGERED",
        )
        .order_by(RuleEvaluationRecord.detected_at.desc())
    ).all() if transaction_ids else []
    detections_by_transaction: dict[UUID, list[dict]] = {}
    for detection, _score, _band in detection_rows:
        detections_by_transaction.setdefault(detection.transaction_id, []).append(
            {
                "id": detection.id,
                "rule_id": detection.rule_id,
                "rule_version": detection.rule_version,
                "rule_name": detection.rule_name,
                "severity": detection.severity,
                "explanation": detection.explanation,
                "evidence": _evidence_response(detection.evidence),
                "detected_at": detection.detected_at,
                "incident_id": detection.incident_id,
            }
        )
    rank_to_band = {1: "LOW", 2: "GUARDED", 3: "ELEVATED", 4: "CRITICAL"}
    return [
        {
            "id": transaction.id,
            "transaction_type": transaction.transaction_type,
            "sender_account": _masked_account(sender_number) if sender_number else None,
            "receiver_account": _masked_account(receiver_number),
            "amount": transaction.amount,
            "currency": transaction.currency,
            "status": transaction.status,
            "created_at": transaction.created_at,
            "risk_score": risk_score,
            "risk_band": rank_to_band.get(risk_rank),
            "triggered_detection_count": detection_count or 0,
            "detections": detections_by_transaction.get(transaction.id, []),
        }
        for transaction, sender_number, receiver_number, risk_score, risk_rank, detection_count in rows
    ]


@app.get("/detections/recent", response_model=list[RecentDetectionResponse])
def recent_detections(
    limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db)
):
    rows = db.execute(
        select(RuleEvaluationRecord, Transaction, SecurityIncident)
        .join(Transaction, Transaction.id == RuleEvaluationRecord.transaction_id)
        .outerjoin(SecurityIncident, SecurityIncident.id == RuleEvaluationRecord.incident_id)
        .where(RuleEvaluationRecord.evaluation_outcome == "TRIGGERED")
        .order_by(RuleEvaluationRecord.detected_at.desc(), RuleEvaluationRecord.id)
        .limit(limit)
    ).all()
    return [
        {
            "id": evaluation.id,
            "rule_id": evaluation.rule_id,
            "rule_version": evaluation.rule_version,
            "rule_name": evaluation.rule_name,
            "severity": evaluation.severity,
            "explanation": evaluation.explanation,
            "evidence": _evidence_response(evaluation.evidence),
            "detected_at": evaluation.detected_at,
            "incident_id": evaluation.incident_id,
            "transaction_amount": transaction.amount,
            "currency": transaction.currency,
            "incident_risk_score": incident.risk_score if incident else None,
            "incident_risk_band": incident.risk_band if incident else None,
        }
        for evaluation, transaction, incident in rows
    ]


@app.get("/incidents", response_model=IncidentListResponse)
def list_incidents(
    status_filter: str | None = Query(default=None, alias="status", pattern="^(OPEN|INVESTIGATING|RESOLVED|DISMISSED)$"),
    risk_band: str | None = Query(default=None, pattern="^(LOW|GUARDED|ELEVATED|CRITICAL)$"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    evaluation_summary = (
        select(
            RuleEvaluationRecord.incident_id.label("incident_id"),
            func.count(RuleEvaluationRecord.id).label("detection_count"),
            func.count(distinct(RuleEvaluationRecord.transaction_id)).label("transaction_count"),
            func.min(RuleEvaluationRecord.rule_name).label("first_rule_name"),
        )
        .where(
            RuleEvaluationRecord.incident_id.is_not(None),
            RuleEvaluationRecord.evaluation_outcome == "TRIGGERED",
        )
        .group_by(RuleEvaluationRecord.incident_id)
        .subquery()
    )
    filters = []
    if status_filter:
        filters.append(SecurityIncident.status == status_filter)
    if risk_band:
        filters.append(SecurityIncident.risk_band == risk_band)
    total = db.scalar(
        select(func.count(SecurityIncident.id)).where(*filters)
    ) or 0
    rows = db.execute(
        select(
            SecurityIncident,
            Account.account_number,
            evaluation_summary.c.detection_count,
            evaluation_summary.c.transaction_count,
            evaluation_summary.c.first_rule_name,
        )
        .join(Account, Account.id == SecurityIncident.primary_account_id)
        .outerjoin(evaluation_summary, evaluation_summary.c.incident_id == SecurityIncident.id)
        .where(*filters)
        .order_by(SecurityIncident.last_activity_at.desc(), SecurityIncident.id)
        .limit(limit)
        .offset(offset)
    ).all()
    items = [
        {
            "id": incident.id,
            "title": rule_name or "Security incident",
            "status": incident.status,
            "risk_score": incident.risk_score,
            "risk_band": incident.risk_band,
            "risk_explanation": incident.risk_explanation,
            "primary_account": _masked_account(account_number),
            "opened_at": incident.opened_at,
            "last_activity_at": incident.last_activity_at,
            "closed_at": incident.closed_at,
            "transaction_count": transaction_count or 0,
            "detection_count": detection_count or 0,
        }
        for incident, account_number, detection_count, transaction_count, rule_name in rows
    ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@app.get("/incidents/{incident_id}", response_model=IncidentDetailResponse)
def get_incident(incident_id: UUID, db: Session = Depends(get_db)):
    incident = db.get(SecurityIncident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    return _incident_detail(db, incident)


@app.patch("/incidents/{incident_id}/status", response_model=IncidentDetailResponse)
def update_incident_status(
    incident_id: UUID,
    payload: IncidentStatusUpdateRequest,
    db: Session = Depends(get_db),
):
    try:
        with db.begin():
            incident = transition_incident(
                db,
                incident_id=incident_id,
                new_status=payload.status,
                actor_identifier=None,
                note=payload.note,
                changed_at=datetime.now(timezone.utc),
            )
        return _incident_detail(db, incident)
    except LookupError:
        raise HTTPException(status_code=404, detail="Incident not found.") from None
    except IncidentTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.post(
    "/incidents/{incident_id}/notes",
    response_model=IncidentDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_incident_note(
    incident_id: UUID,
    payload: IncidentNoteRequest,
    db: Session = Depends(get_db),
):
    with db.begin():
        incident = db.scalar(
            select(SecurityIncident)
            .where(SecurityIncident.id == incident_id)
            .with_for_update()
        )
        if incident is None:
            raise HTTPException(status_code=404, detail="Incident not found.")
        db.add(
            IncidentLifecycleEvent(
                incident_id=incident.id,
                from_status=incident.status,
                to_status=incident.status,
                actor_identifier=None,
                note=payload.note,
                changed_at=datetime.now(timezone.utc),
            )
        )
        db.flush()
    return _incident_detail(db, incident)

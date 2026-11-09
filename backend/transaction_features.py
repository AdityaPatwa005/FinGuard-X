"""Read-only, deterministic features for a persisted simulator transaction.

All historical windows use the half-open interval ``[target_time - window,
target_time)``: the lower boundary is included and records at the target
timestamp are excluded. Historical baselines use every earlier COMPLETED
customer-initiated TRANSFER. FUNDING is account activity, but is never treated
as customer outgoing behavior.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, case, distinct, func, or_, select
from sqlalchemy.orm import Session

from transaction_models import Transaction


ZERO = Decimal("0.00")
DEFAULT_MINIMUM_BASELINE_TRANSACTIONS = 5


class TransactionNotFoundError(LookupError):
    """Raised when a requested transaction does not exist."""


@dataclass(frozen=True)
class TransactionContext:
    """Raw transaction context; amount is Decimal INR and timestamp is UTC."""

    transaction_id: UUID
    amount: Decimal
    transaction_type: str
    currency: str
    status: str
    sender_account_id: UUID | None
    receiver_account_id: UUID
    timestamp: datetime


@dataclass(frozen=True)
class TransactionVelocityFeatures:
    """Completed transactions involving the focal account in trailing windows.

    Counts use inclusive lower bounds and exclude the evaluated transaction's
    timestamp. Funding and transfers both count as account activity here.
    """

    focal_account_id: UUID
    focal_account_role: str
    prior_5_minute_count: int
    prior_1_hour_count: int
    prior_24_hour_count: int
    prior_outgoing_transfer_5_minute_count: int | None
    prior_outgoing_transfer_1_hour_count: int | None


@dataclass(frozen=True)
class OutgoingVolumeFeatures:
    """Completed outgoing TRANSFER sums in Decimal INR; None means not applicable.

    Funding is excluded. Windows are ``[target - 1 hour, target)`` and
    ``[target - 24 hours, target)``.
    """

    prior_1_hour_amount: Decimal | None
    prior_24_hour_amount: Decimal | None


@dataclass(frozen=True)
class CustomerBehaviorFeatures:
    """All-time prior outgoing TRANSFER statistics, with amount values in INR.

    Deviation is signed ``evaluated amount - historical average``. Statistics
    are available from one prior transfer; reliability is separately indicated
    by ``FeatureDataQuality.outgoing_baseline_sufficient``.
    """

    applicable: bool
    historical_transfer_count: int | None
    average_amount: Decimal | None
    median_amount: Decimal | None
    amount_deviation_from_average: Decimal | None


@dataclass(frozen=True)
class BeneficiaryBehaviorFeatures:
    """Prior sender-to-receiver transfer history; None means not applicable."""

    applicable: bool
    previously_received_from_sender: bool | None
    receiver_seen_in_prior_24_hours: bool | None
    distinct_receivers_in_prior_24_hours: int | None


@dataclass(frozen=True)
class TemporalFeatures:
    """UTC calendar fields only; weekday is Monday=0 through Sunday=6.

    These fields do not imply that a transaction is unusual for the customer.
    """

    hour_utc: int
    weekday_utc: int


@dataclass(frozen=True)
class FeatureDataQuality:
    """Explicit history availability and baseline reliability indicators."""

    prior_account_activity_in_24_hours: bool
    historical_outgoing_transfer_history_available: bool | None
    outgoing_baseline_sufficient: bool | None
    minimum_baseline_transactions: int
    history_status_scope: str = "COMPLETED only; rejected requests are not represented"


@dataclass(frozen=True)
class TransactionFeatureSet:
    """Reusable feature output, separated by context, behavior, and data quality."""

    context: TransactionContext
    velocity: TransactionVelocityFeatures
    outgoing_volume: OutgoingVolumeFeatures
    customer_behavior: CustomerBehaviorFeatures
    beneficiary_behavior: BeneficiaryBehaviorFeatures
    temporal: TemporalFeatures
    data_quality: FeatureDataQuality


def extract_transaction_features(
    db: Session,
    transaction_id: UUID,
    *,
    minimum_baseline_transactions: int = DEFAULT_MINIMUM_BASELINE_TRANSACTIONS,
) -> TransactionFeatureSet:
    """Extract features for a transaction using only strictly earlier records.

    The focal account is the sender for TRANSFER and the receiver for FUNDING.
    Velocity counts completed transactions involving that account (as sender or
    receiver); outgoing volume and behavior count only that account's completed
    TRANSFERs as sender. Aggregations run in SQL, and only the median's middle
    one or two scalar amounts are returned to Python.
    """
    if minimum_baseline_transactions < 1:
        raise ValueError("minimum_baseline_transactions must be at least 1")

    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise TransactionNotFoundError(f"Transaction {transaction_id} was not found")

    as_of = _as_utc(transaction.created_at)
    # Keep comparisons in the database driver's timestamp representation (naive
    # on SQLite, timezone-aware on PostgreSQL); use UTC only for output fields.
    window_end = transaction.created_at
    focal_account_id = (
        transaction.sender_account_id
        if transaction.transaction_type == "TRANSFER"
        else transaction.receiver_account_id
    )
    focal_role = "sender" if transaction.transaction_type == "TRANSFER" else "receiver"

    context = TransactionContext(
        transaction_id=transaction.id,
        amount=transaction.amount,
        transaction_type=transaction.transaction_type,
        currency=transaction.currency,
        status=transaction.status,
        sender_account_id=transaction.sender_account_id,
        receiver_account_id=transaction.receiver_account_id,
        timestamp=as_of,
    )
    velocity = _velocity_features(db, focal_account_id, focal_role, window_end)
    temporal = TemporalFeatures(hour_utc=as_of.hour, weekday_utc=as_of.weekday())

    if transaction.transaction_type != "TRANSFER" or transaction.sender_account_id is None:
        return TransactionFeatureSet(
            context=context,
            velocity=velocity,
            outgoing_volume=OutgoingVolumeFeatures(None, None),
            customer_behavior=CustomerBehaviorFeatures(False, None, None, None, None),
            beneficiary_behavior=BeneficiaryBehaviorFeatures(False, None, None, None),
            temporal=temporal,
            data_quality=FeatureDataQuality(
                prior_account_activity_in_24_hours=velocity.prior_24_hour_count > 0,
                historical_outgoing_transfer_history_available=None,
                outgoing_baseline_sufficient=None,
                minimum_baseline_transactions=minimum_baseline_transactions,
            ),
        )

    sender_id = transaction.sender_account_id
    one_hour_ago = window_end - timedelta(hours=1)
    one_day_ago = window_end - timedelta(hours=24)
    historical = _outgoing_history(
        db,
        sender_id,
        transaction.receiver_account_id,
        window_end,
        one_hour_ago,
        one_day_ago,
    )
    count = historical[0]
    total_amount = historical[1]
    outgoing_1h = historical[2]
    outgoing_24h = historical[3]
    previous_receiver_count = historical[4]
    receiver_seen_24h_count = historical[5]
    distinct_receiver_count = historical[6]

    average = total_amount / count if count else None
    median = _historical_median(db, sender_id, transaction.created_at, count)
    deviation = transaction.amount - average if average is not None else None
    baseline_sufficient = count >= minimum_baseline_transactions

    return TransactionFeatureSet(
        context=context,
        velocity=velocity,
        outgoing_volume=OutgoingVolumeFeatures(outgoing_1h, outgoing_24h),
        customer_behavior=CustomerBehaviorFeatures(
            applicable=True,
            historical_transfer_count=count,
            average_amount=average,
            median_amount=median,
            amount_deviation_from_average=deviation,
        ),
        beneficiary_behavior=BeneficiaryBehaviorFeatures(
            applicable=True,
            previously_received_from_sender=previous_receiver_count > 0,
            receiver_seen_in_prior_24_hours=receiver_seen_24h_count > 0,
            distinct_receivers_in_prior_24_hours=distinct_receiver_count,
        ),
        temporal=temporal,
        data_quality=FeatureDataQuality(
            prior_account_activity_in_24_hours=velocity.prior_24_hour_count > 0,
            historical_outgoing_transfer_history_available=count > 0,
            outgoing_baseline_sufficient=baseline_sufficient,
            minimum_baseline_transactions=minimum_baseline_transactions,
        ),
    )


def _velocity_features(
    db: Session, account_id: UUID, account_role: str, as_of: datetime
) -> TransactionVelocityFeatures:
    lower_24h = as_of - timedelta(hours=24)
    stmt = select(
        func.coalesce(
            func.sum(case((Transaction.created_at >= as_of - timedelta(minutes=5), 1), else_=0)),
            0,
        ),
        func.coalesce(
            func.sum(case((Transaction.created_at >= as_of - timedelta(hours=1), 1), else_=0)),
            0,
        ),
        func.count(Transaction.id),
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(
                            Transaction.transaction_type == "TRANSFER",
                            Transaction.sender_account_id == account_id,
                            Transaction.created_at >= as_of - timedelta(minutes=5),
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        ),
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(
                            Transaction.transaction_type == "TRANSFER",
                            Transaction.sender_account_id == account_id,
                            Transaction.created_at >= as_of - timedelta(hours=1),
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        ),
    ).where(
        Transaction.status == "COMPLETED",
        Transaction.created_at >= lower_24h,
        Transaction.created_at < as_of,
        or_(
            Transaction.sender_account_id == account_id,
            Transaction.receiver_account_id == account_id,
        ),
    )
    counts = db.execute(stmt).one()
    return TransactionVelocityFeatures(
        focal_account_id=account_id,
        focal_account_role=account_role,
        prior_5_minute_count=int(counts[0] or 0),
        prior_1_hour_count=int(counts[1] or 0),
        prior_24_hour_count=int(counts[2] or 0),
        prior_outgoing_transfer_5_minute_count=(
            int(counts[3] or 0) if account_role == "sender" else None
        ),
        prior_outgoing_transfer_1_hour_count=(
            int(counts[4] or 0) if account_role == "sender" else None
        ),
    )


def _outgoing_history(
    db: Session,
    sender_id: UUID,
    receiver_id: UUID,
    transaction_created_at: datetime,
    one_hour_ago: datetime,
    one_day_ago: datetime,
) -> tuple[int, Decimal, Decimal, Decimal, int, int, int]:
    base = (
        Transaction.sender_account_id == sender_id,
        Transaction.transaction_type == "TRANSFER",
        Transaction.status == "COMPLETED",
        Transaction.created_at < transaction_created_at,
    )
    stmt = select(
        func.count(Transaction.id),
        func.coalesce(func.sum(Transaction.amount), ZERO),
        func.coalesce(
            func.sum(case((Transaction.created_at >= one_hour_ago, Transaction.amount), else_=ZERO)),
            ZERO,
        ),
        func.coalesce(
            func.sum(case((Transaction.created_at >= one_day_ago, Transaction.amount), else_=ZERO)),
            ZERO,
        ),
        func.coalesce(
            func.sum(case((Transaction.receiver_account_id == receiver_id, 1), else_=0)),
            0,
        ),
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(
                            Transaction.receiver_account_id == receiver_id,
                            Transaction.created_at >= one_day_ago,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        ),
        func.count(
            distinct(
                case(
                    (Transaction.created_at >= one_day_ago, Transaction.receiver_account_id),
                    else_=None,
                )
            )
        ),
    ).where(*base)
    row = db.execute(stmt).one()
    return (
        int(row[0] or 0),
        _as_decimal(row[1]),
        _as_decimal(row[2]),
        _as_decimal(row[3]),
        int(row[4] or 0),
        int(row[5] or 0),
        int(row[6] or 0),
    )


def _historical_median(
    db: Session, sender_id: UUID, before: datetime, count: int
) -> Decimal | None:
    if count == 0:
        return None
    offset = (count - 1) // 2
    limit = 1 if count % 2 else 2
    values = list(
        db.scalars(
            select(Transaction.amount)
            .where(
                Transaction.sender_account_id == sender_id,
                Transaction.transaction_type == "TRANSFER",
                Transaction.status == "COMPLETED",
                Transaction.created_at < before,
            )
            .order_by(Transaction.amount)
            .offset(offset)
            .limit(limit)
        ).all()
    )
    if not values:
        return None
    if len(values) == 1:
        return _as_decimal(values[0])
    return (_as_decimal(values[0]) + _as_decimal(values[1])) / Decimal("2")


def _as_utc(value: datetime) -> datetime:
    """Normalize DB timestamps; naive values are treated as UTC for SQLite tests."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _as_decimal(value: Decimal | int | float | None) -> Decimal:
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    # SQLite may return binary-backed numeric aggregates; persisted transaction
    # amounts have scale 2, so restore that exact money precision at the boundary.
    return Decimal(str(value)).quantize(Decimal("0.01"))

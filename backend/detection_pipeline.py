"""Persist rule outcomes and correlate triggered transfer detections."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from incident_models import RuleEvaluationRecord
from incident_service import correlate_triggered_evaluations, lock_relevant_account
from rule_detection import DetectionRun, RuleResult, evaluate_transaction
from transaction_models import Transaction
from event_processing import EventNormalizationError, NormalizedTransactionEvent


def persist_transfer_detections(
    db: Session, event: NormalizedTransactionEvent
) -> list[RuleEvaluationRecord]:
    """Validate a completed transfer event, then persist/correlate once.

    Caller must include this operation and outbox acknowledgement in the same
    database transaction. Financial records are read-only here.
    """
    transaction = db.scalar(
        select(Transaction).where(Transaction.id == event.transaction_id).with_for_update()
    )
    if transaction is None or transaction.status != "COMPLETED":
        raise EventNormalizationError("Completed transaction record is unavailable.")

    expected = (
        transaction.transaction_type == event.transaction_type
        and transaction.sender_account_id == event.sender_account_id
        and transaction.receiver_account_id == event.receiver_account_id
        and Decimal(transaction.amount) == event.amount
        and transaction.currency == event.currency
    )
    if not expected:
        raise EventNormalizationError("Event does not match its completed transaction.")

    # Funding records are valid pipeline events but are not customer fraud cases.
    if transaction.transaction_type != "TRANSFER" or transaction.sender_account_id is None:
        return []

    # Serialize evaluations for one sender before checking/inserting the
    # unique transaction/rule/version records. This is a no-op row lock on SQLite.
    lock_relevant_account(db, transaction.sender_account_id)
    run: DetectionRun = evaluate_transaction(db, transaction.id)
    if not run.eligible:
        return []

    existing = db.scalars(
        select(RuleEvaluationRecord).where(
            RuleEvaluationRecord.transaction_id == transaction.id
        )
    ).all()
    by_identity = {(row.rule_id, row.rule_version): row for row in existing}
    inserted: list[RuleEvaluationRecord] = []
    for result in run.rule_results:
        key = (result.rule_id, result.version)
        record = by_identity.get(key)
        if record is None:
            record = _evaluation_record(transaction, result)
            db.add(record)
            inserted.append(record)
    db.flush()

    triggered = [
        row
        for row in [*existing, *inserted]
        if row.evaluation_outcome == "TRIGGERED" and row.incident_id is None
    ]
    if triggered:
        correlate_triggered_evaluations(db, transaction=transaction, evaluations=triggered)
    return inserted


def _evaluation_record(
    transaction: Transaction, result: RuleResult
) -> RuleEvaluationRecord:
    # Rule explanations are intentionally account-agnostic; evidence values
    # preserve Decimal precision as strings for portable JSON storage.
    evidence = [
        {
            "name": item.name,
            "value": str(item.value) if isinstance(item.value, Decimal) else item.value,
            "unit": item.unit,
        }
        for item in result.evidence
    ]
    return RuleEvaluationRecord(
        rule_id=result.rule_id,
        rule_version=result.version,
        rule_name=result.name,
        rule_description=result.description,
        transaction_id=transaction.id,
        relevant_account_id=transaction.sender_account_id,
        detected_at=transaction.created_at,
        severity=result.severity.value,
        evaluation_outcome=result.outcome.value,
        explanation=result.explanation,
        required_features=list(result.required_features),
        minimum_history=result.minimum_history,
        evidence=evidence,
        limitation=result.limitation,
    )

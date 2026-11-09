"""Account-scoped, idempotent incident correlation and lifecycle transitions."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from incident_models import IncidentLifecycleEvent, RuleEvaluationRecord, SecurityIncident
from models import Account
from risk_assessment import (
    DEFAULT_RISK_SCORING_POLICY,
    IncidentDetectionEvidence,
    RiskScoringPolicy,
    assess_incident_risk,
)
from transaction_models import Transaction


ACTIVE_INCIDENT_STATUSES = ("OPEN", "INVESTIGATING")
CLOSED_INCIDENT_STATUSES = ("RESOLVED", "DISMISSED")


@dataclass(frozen=True)
class CorrelationPolicy:
    """Correlate by sender account when activity times are within this window."""

    version: str = "1.0"
    window: timedelta = timedelta(hours=24)

    def __post_init__(self) -> None:
        if not self.version or len(self.version) > 24:
            raise ValueError("Correlation policy version must contain 1 to 24 characters")
        if self.window.total_seconds() <= 0:
            raise ValueError("Correlation window must be positive")


DEFAULT_CORRELATION_POLICY = CorrelationPolicy()


class IncidentTransitionError(ValueError):
    """Raised when a requested lifecycle transition is not permitted."""


def lock_relevant_account(db: Session, account_id: UUID) -> None:
    """Serialize correlation for one initiating account without merging parties."""
    account = db.scalar(
        select(Account.id).where(Account.id == account_id).with_for_update()
    )
    if account is None:
        raise ValueError("Relevant transaction account no longer exists")


def correlate_triggered_evaluations(
    db: Session,
    *,
    transaction: Transaction,
    evaluations: list[RuleEvaluationRecord],
    correlation_policy: CorrelationPolicy = DEFAULT_CORRELATION_POLICY,
    scoring_policy: RiskScoringPolicy = DEFAULT_RISK_SCORING_POLICY,
) -> SecurityIncident | None:
    """Assign a transaction's triggered evaluations to one account-scoped incident.

    Only transfer sender accounts participate in correlation. The receiver is
    deliberately not used as a second correlation key, so activity involving a
    beneficiary cannot merge that beneficiary's unrelated cases.
    """
    pending = [row for row in evaluations if row.incident_id is None]
    if not pending:
        return None
    if transaction.transaction_type != "TRANSFER" or transaction.sender_account_id is None:
        raise ValueError("Only sender-initiated transfers can be correlated")

    account_id = transaction.sender_account_id
    lock_relevant_account(db, account_id)
    activity_at = transaction.created_at
    lower_bound = activity_at - correlation_policy.window
    upper_bound = activity_at + correlation_policy.window

    incident = db.scalar(
        select(SecurityIncident)
        .where(
            SecurityIncident.primary_account_id == account_id,
            SecurityIncident.status.in_(ACTIVE_INCIDENT_STATUSES),
            SecurityIncident.last_activity_at >= lower_bound,
            SecurityIncident.last_activity_at <= upper_bound,
        )
        .order_by(SecurityIncident.last_activity_at.desc(), SecurityIncident.id)
        .limit(1)
        .with_for_update()
    )
    if incident is None:
        incident = SecurityIncident(
            primary_account_id=account_id,
            anchor_transaction_id=transaction.id,
            status="OPEN",
            opened_at=activity_at,
            last_activity_at=activity_at,
            risk_score=0,
            risk_band="LOW",
            risk_policy_version=scoring_policy.version,
            risk_explanation="Incident opened from triggered rule evidence; assessment pending.",
            risk_evidence=[],
        )
        db.add(incident)
        db.flush()
        db.add(
            IncidentLifecycleEvent(
                incident_id=incident.id,
                from_status=None,
                to_status="OPEN",
                actor_identifier="system",
                note="Incident created from triggered rule detections.",
            )
        )
    elif activity_at > incident.last_activity_at:
        incident.last_activity_at = activity_at

    for evaluation in pending:
        evaluation.incident_id = incident.id
    db.flush()

    incident_evaluations = db.scalars(
        select(RuleEvaluationRecord).where(
            RuleEvaluationRecord.incident_id == incident.id,
            RuleEvaluationRecord.evaluation_outcome == "TRIGGERED",
        )
    ).all()
    assessment = assess_incident_risk(
        (
            IncidentDetectionEvidence(
                detection_id=evaluation.id,
                rule_id=evaluation.rule_id,
                evaluation_outcome=evaluation.evaluation_outcome,
                evidence=tuple(evaluation.evidence),
            )
            for evaluation in incident_evaluations
        ),
        scoring_policy,
    )
    incident.risk_score = assessment.score
    incident.risk_band = assessment.band.value
    incident.risk_policy_version = assessment.policy_version
    incident.risk_explanation = assessment.explanation
    incident.risk_evidence = assessment.to_json()
    db.flush()
    return incident


_ALLOWED_TRANSITIONS = {
    "OPEN": {"INVESTIGATING", "RESOLVED", "DISMISSED"},
    "INVESTIGATING": {"RESOLVED", "DISMISSED"},
    "RESOLVED": set(),
    "DISMISSED": set(),
}


def transition_incident(
    db: Session,
    *,
    incident_id: UUID,
    new_status: str,
    actor_identifier: str | None = "system",
    note: str | None = None,
    changed_at: datetime | None = None,
) -> SecurityIncident:
    """Change status and append an audit row; caller owns the DB transaction."""
    incident = db.scalar(
        select(SecurityIncident)
        .where(SecurityIncident.id == incident_id)
        .with_for_update()
    )
    if incident is None:
        raise LookupError("Incident was not found")
    if new_status not in _ALLOWED_TRANSITIONS.get(incident.status, set()):
        raise IncidentTransitionError(
            f"Transition from {incident.status} to {new_status} is not permitted"
        )
    if actor_identifier is not None:
        actor_identifier = actor_identifier.strip()
        if not actor_identifier:
            actor_identifier = None
        elif len(actor_identifier) > 120:
            raise ValueError("Actor identifier cannot exceed 120 characters")

    change_time = changed_at or datetime.now(timezone.utc)
    previous = incident.status
    incident.status = new_status
    incident.closed_at = change_time if new_status in CLOSED_INCIDENT_STATUSES else None
    db.add(
        IncidentLifecycleEvent(
            incident_id=incident.id,
            from_status=previous,
            to_status=new_status,
            actor_identifier=actor_identifier,
            note=note,
            changed_at=change_time,
        )
    )
    db.flush()
    return incident

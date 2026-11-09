"""Synthetic SQLite tests; SQLite does not validate PostgreSQL row locking."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import incident_models  # noqa: F401 - register incident tables on shared metadata
import ledger_models  # noqa: F401
import outbox_models  # noqa: F401
import transaction_models  # noqa: F401
from event_processing import process_event_batch
from incident_models import IncidentLifecycleEvent, RuleEvaluationRecord, SecurityIncident
from incident_service import IncidentTransitionError, transition_incident
from models import Account, Base, User
from outbox_models import OutboxEvent
from risk_assessment import (
    IncidentDetectionEvidence,
    RiskBand,
    assess_incident_risk,
    risk_band_for_score,
)
from transaction_models import Transaction


class IncidentManagementTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        with self.Session.begin() as db:
            self.user = User(full_name="Synthetic Incident Test", email=f"{uuid.uuid4()}@example.test")
            second_user = User(full_name="Synthetic Other Test", email=f"{uuid.uuid4()}@example.test")
            third_user = User(full_name="Synthetic Third Test", email=f"{uuid.uuid4()}@example.test")
            db.add_all([self.user, second_user, third_user])
            db.flush()
            self.sender = Account(
                user_id=self.user.id, account_number=f"IT{uuid.uuid4().hex[:30]}",
                account_type="savings", balance=Decimal("1000.00"), currency="INR", status="active",
            )
            self.receiver = Account(
                user_id=second_user.id, account_number=f"IT{uuid.uuid4().hex[:30]}",
                account_type="savings", balance=Decimal("1000.00"), currency="INR", status="active",
            )
            self.other_sender = Account(
                user_id=third_user.id, account_number=f"IT{uuid.uuid4().hex[:30]}",
                account_type="savings", balance=Decimal("1000.00"), currency="INR", status="active",
            )
            db.add_all([self.sender, self.receiver, self.other_sender])
            db.flush()

    def tearDown(self):
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _create_transfer_event(
        self, *, at: datetime, key: str, amount: str = "10.00", sender: Account | None = None
    ):
        sender = sender or self.sender
        with self.Session.begin() as db:
            transaction = Transaction(
                sender_account_id=sender.id,
                receiver_account_id=self.receiver.id,
                transaction_type="TRANSFER",
                amount=Decimal(amount),
                currency="INR",
                status="COMPLETED",
                idempotency_key=key,
                description="Synthetic transfer",
                created_at=at,
                updated_at=at,
            )
            db.add(transaction)
            db.flush()
            event_id = uuid.uuid4()
            outbox = OutboxEvent(
                id=event_id,
                event_type="transaction.transfer.completed",
                event_version=1,
                source_system="finbank-simulator",
                related_transaction_id=transaction.id,
                deduplication_key=f"test:{transaction.id}",
                payload={
                    "event_id": str(event_id),
                    "event_type": "transaction.transfer.completed",
                    "event_version": 1,
                    "source_system": "finbank-simulator",
                    "transaction_id": str(transaction.id),
                    "transaction_type": "TRANSFER",
                    "sender_account_id": str(sender.id),
                    "receiver_account_id": str(self.receiver.id),
                    "amount": amount,
                    "currency": "INR",
                    "timestamp": at.isoformat(),
                    "description": "Synthetic transfer",
                },
            )
            db.add(outbox)
            return transaction.id, outbox.id

    def test_related_transfer_detections_share_incident_and_event_replay_is_idempotent(self):
        base = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        with self.Session.begin() as db:
            for index in range(4):
                created = base - timedelta(minutes=4 - index)
                db.add(Transaction(
                    sender_account_id=self.sender.id, receiver_account_id=self.receiver.id,
                    transaction_type="TRANSFER", amount=Decimal("10.00"), currency="INR",
                    status="COMPLETED", idempotency_key=f"history-{index}", created_at=created,
                    updated_at=created,
                ))
        first_tx, _ = self._create_transfer_event(at=base, key="target-one", amount="100001.00")
        first = process_event_batch(self.Session)
        self.assertEqual((first.processed, first.failed), (1, 0))
        with self.Session() as db:
            detections = db.scalars(select(RuleEvaluationRecord).where(RuleEvaluationRecord.transaction_id == first_tx)).all()
            incidents = db.scalars(select(SecurityIncident)).all()
            self.assertEqual(len(detections), 5)
            triggered = [row for row in detections if row.evaluation_outcome == "TRIGGERED"]
            self.assertTrue(triggered)
            self.assertEqual(len(incidents), 1)
            self.assertGreaterEqual(len(triggered), 2)
            self.assertTrue(all(row.incident_id == incidents[0].id for row in triggered))
            self.assertEqual(incidents[0].risk_score, 50)
            self.assertEqual(incidents[0].risk_band, "ELEVATED")
            self.assertTrue(any(row.evaluation_outcome == "NOT_EVALUATED" for row in detections))
            self.assertTrue(any(item["evidence"] for item in incidents[0].risk_evidence))

        second_tx, _ = self._create_transfer_event(
            at=base + timedelta(minutes=2), key="target-two", amount="11.00"
        )
        second = process_event_batch(self.Session)
        self.assertEqual((second.processed, second.failed), (1, 0))
        with self.Session() as db:
            incidents = db.scalars(select(SecurityIncident)).all()
            self.assertEqual(len(incidents), 1)
            second_detections = db.scalars(select(RuleEvaluationRecord).where(RuleEvaluationRecord.transaction_id == second_tx)).all()
            self.assertTrue(any(row.incident_id == incidents[0].id for row in second_detections if row.evaluation_outcome == "TRIGGERED"))
            replay = process_event_batch(self.Session)
            self.assertEqual((replay.claimed, replay.processed), (0, 0))

    def test_worker_failure_rolls_back_detection_and_acknowledgement_then_retries(self):
        tx_id, outbox_id = self._create_transfer_event(
            at=datetime(2026, 2, 1, 10, tzinfo=timezone.utc), key="retry-target"
        )
        with patch("detection_pipeline.evaluate_transaction", side_effect=RuntimeError("internal detail")):
            first = process_event_batch(self.Session)
        self.assertEqual((first.failed, first.processed), (1, 0))
        with self.Session() as db:
            outbox = db.get(OutboxEvent, outbox_id)
            self.assertEqual(outbox.processing_status, "FAILED")
            self.assertNotIn("internal detail", outbox.last_error)
            self.assertEqual(db.scalar(select(RuleEvaluationRecord.id).where(RuleEvaluationRecord.transaction_id == tx_id)), None)
            self.assertEqual(db.scalar(select(SecurityIncident.id)), None)
        retry = process_event_batch(self.Session)
        self.assertEqual((retry.processed, retry.failed), (1, 0))
        with self.Session() as db:
            self.assertEqual(db.get(OutboxEvent, outbox_id).processing_status, "PROCESSED")

    def test_funding_is_processed_without_customer_fraud_evaluations(self):
        at = datetime(2026, 2, 5, 10, tzinfo=timezone.utc)
        with self.Session.begin() as db:
            tx = Transaction(
                sender_account_id=None, receiver_account_id=self.receiver.id,
                transaction_type="FUNDING", amount=Decimal("20.00"), currency="INR",
                status="COMPLETED", idempotency_key="funding-only-test", created_at=at, updated_at=at,
            )
            db.add(tx)
            db.flush()
            event_id = uuid.uuid4()
            db.add(OutboxEvent(
                id=event_id, event_type="transaction.funding.completed", event_version=1,
                source_system="finbank-simulator", related_transaction_id=tx.id,
                deduplication_key=f"test:{tx.id}",
                payload={
                    "event_id": str(event_id), "event_type": "transaction.funding.completed",
                    "event_version": 1, "source_system": "finbank-simulator",
                    "transaction_id": str(tx.id), "transaction_type": "FUNDING",
                    "sender_account_id": None, "receiver_account_id": str(self.receiver.id),
                    "amount": "20.00", "currency": "INR", "timestamp": at.isoformat(),
                    "description": None,
                },
            ))
            tx_id = tx.id
        result = process_event_batch(self.Session)
        self.assertEqual((result.processed, result.failed), (1, 0))
        with self.Session() as db:
            self.assertEqual(db.scalar(select(RuleEvaluationRecord.id).where(RuleEvaluationRecord.transaction_id == tx_id)), None)
            self.assertEqual(db.scalar(select(SecurityIncident.id)), None)

    def test_different_sender_accounts_are_not_correlated(self):
        base = datetime(2026, 2, 10, 10, tzinfo=timezone.utc)
        for sender, prefix in ((self.sender, "sender-a"), (self.other_sender, "sender-b")):
            with self.Session.begin() as db:
                for index in range(4):
                    created = base - timedelta(minutes=4 - index)
                    db.add(Transaction(
                        sender_account_id=sender.id, receiver_account_id=self.receiver.id,
                        transaction_type="TRANSFER", amount=Decimal("1.00"), currency="INR",
                        status="COMPLETED", idempotency_key=f"{prefix}-history-{index}",
                        created_at=created, updated_at=created,
                    ))
            self._create_transfer_event(at=base, key=f"{prefix}-target", sender=sender)
            result = process_event_batch(self.Session)
            self.assertEqual((result.processed, result.failed), (1, 0))
        with self.Session() as db:
            incidents = db.scalars(select(SecurityIncident)).all()
            self.assertEqual(len(incidents), 2)
            self.assertEqual({row.primary_account_id for row in incidents}, {self.sender.id, self.other_sender.id})

    def test_closed_incident_stays_closed_and_new_trigger_opens_separate_incident(self):
        at = datetime(2026, 3, 1, 10, tzinfo=timezone.utc)
        with self.Session.begin() as db:
            incident = SecurityIncident(
                primary_account_id=self.sender.id,
                anchor_transaction_id=uuid.uuid4(),
                status="OPEN",
                opened_at=at,
                last_activity_at=at,
                risk_score=0,
                risk_band="LOW",
                risk_policy_version="1.0",
                risk_explanation="Test incident.",
                risk_evidence=[],
            )
            # Need an actual referenced transaction for the anchor.
            anchor = Transaction(
                sender_account_id=self.sender.id, receiver_account_id=self.receiver.id,
                transaction_type="TRANSFER", amount=Decimal("1.00"), currency="INR",
                status="COMPLETED", idempotency_key="closed-anchor", created_at=at, updated_at=at,
            )
            db.add(anchor)
            db.flush()
            incident.anchor_transaction_id = anchor.id
            db.add(incident)
            db.flush()
            incident_id = incident.id
            transition_incident(db, incident_id=incident.id, new_status="RESOLVED", changed_at=at)
            for index in range(3):
                created = at + timedelta(minutes=index + 1)
                db.add(Transaction(
                    sender_account_id=self.sender.id, receiver_account_id=self.receiver.id,
                    transaction_type="TRANSFER", amount=Decimal("1.00"), currency="INR",
                    status="COMPLETED", idempotency_key=f"post-close-history-{index}",
                    created_at=created, updated_at=created,
                ))
        with self.assertRaises(IncidentTransitionError):
            with self.Session.begin() as db:
                transition_incident(db, incident_id=incident_id, new_status="OPEN")
        with self.Session() as db:
            rows = db.scalars(select(IncidentLifecycleEvent).where(IncidentLifecycleEvent.incident_id == incident_id).order_by(IncidentLifecycleEvent.changed_at)).all()
            self.assertEqual([row.to_status for row in rows], ["RESOLVED"])
        tx_id, _ = self._create_transfer_event(
            at=at + timedelta(minutes=5), key="post-close-trigger", amount="500.00"
        )
        result = process_event_batch(self.Session)
        self.assertEqual((result.processed, result.failed), (1, 0))
        with self.Session() as db:
            incidents = db.scalars(select(SecurityIncident).order_by(SecurityIncident.opened_at)).all()
            self.assertEqual(len(incidents), 2)
            self.assertEqual(incidents[0].status, "RESOLVED")
            self.assertEqual(incidents[1].status, "OPEN")
            self.assertNotEqual(incidents[0].id, incidents[1].id)
            detections = db.scalars(select(RuleEvaluationRecord).where(RuleEvaluationRecord.transaction_id == tx_id)).all()
            self.assertTrue(any(row.incident_id == incidents[1].id for row in detections if row.evaluation_outcome == "TRIGGERED"))

    def test_risk_families_are_deduplicated_and_bands_are_stable(self):
        ids = [uuid.uuid4() for _ in range(3)]
        assessment = assess_incident_risk([
            IncidentDetectionEvidence(
                ids[0], "FGX.TRANSFER.RAPID_BURST", "TRIGGERED",
                evidence=({"name": "transfer_count", "value": 5},),
            ),
            IncidentDetectionEvidence(ids[1], "FGX.TRANSFER.NEW_BENEFICIARY_CONTEXT", "TRIGGERED"),
            IncidentDetectionEvidence(ids[2], "FGX.TRANSFER.BENEFICIARY_DISTRIBUTION", "TRIGGERED"),
            IncidentDetectionEvidence(uuid.uuid4(), "FGX.TRANSFER.HIGH_OUTGOING_VOLUME", "NOT_EVALUATED"),
        ])
        self.assertEqual(assessment.score, 55)
        self.assertEqual(assessment.band, RiskBand.ELEVATED)
        self.assertEqual(assessment.to_json()[1]["evidence"][0]["values"][0]["value"], 5)
        self.assertEqual(risk_band_for_score(25), RiskBand.GUARDED)
        self.assertEqual(risk_band_for_score(50), RiskBand.ELEVATED)
        self.assertEqual(risk_band_for_score(75), RiskBand.CRITICAL)
        self.assertEqual(assessment, assess_incident_risk([
            IncidentDetectionEvidence(
                ids[0], "FGX.TRANSFER.RAPID_BURST", "TRIGGERED",
                evidence=({"name": "transfer_count", "value": 5},),
            ),
            IncidentDetectionEvidence(ids[1], "FGX.TRANSFER.NEW_BENEFICIARY_CONTEXT", "TRIGGERED"),
            IncidentDetectionEvidence(ids[2], "FGX.TRANSFER.BENEFICIARY_DISTRIBUTION", "TRIGGERED"),
        ]))


if __name__ == "__main__":
    unittest.main()

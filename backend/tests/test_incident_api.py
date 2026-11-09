"""SQLite API tests for persisted incident and dashboard endpoints."""

import unittest
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import incident_models  # noqa: F401
import ledger_models  # noqa: F401
import outbox_models  # noqa: F401
import transaction_models  # noqa: F401
from incident_models import IncidentLifecycleEvent, RuleEvaluationRecord, SecurityIncident
from main import (
    add_incident_note,
    dashboard_summary,
    get_incident,
    list_incidents,
    recent_detections,
    recent_transactions,
    update_incident_status,
)
from models import Account, Base, User
from schemas import (
    DashboardSummaryResponse,
    IncidentDetailResponse,
    IncidentListResponse,
    IncidentNoteRequest,
    IncidentStatusUpdateRequest,
    RecentDetectionResponse,
    RecentTransactionResponse,
)
from transaction_models import Transaction


class IncidentApiTests(unittest.TestCase):
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
            user = User(full_name="API Synthetic Test", email=f"{uuid.uuid4()}@example.test")
            db.add(user)
            db.flush()
            account = Account(
                user_id=user.id,
                account_number=f"API{uuid.uuid4().hex[:30]}",
                account_type="savings",
                balance=Decimal("50.00"),
                currency="INR",
                status="active",
            )
            receiver = Account(
                user_id=user.id,
                account_number=f"API{uuid.uuid4().hex[:30]}",
                account_type="savings",
                balance=Decimal("25.00"),
                currency="INR",
                status="active",
            )
            db.add_all([account, receiver])
            db.flush()
            now = datetime.now(timezone.utc)
            transaction = Transaction(
                sender_account_id=account.id,
                receiver_account_id=receiver.id,
                transaction_type="TRANSFER",
                amount=Decimal("12.50"),
                currency="INR",
                status="COMPLETED",
                idempotency_key=f"api-test-{uuid.uuid4()}",
                description="Synthetic API test transfer",
                created_at=now,
                updated_at=now,
            )
            db.add(transaction)
            db.flush()
            incident = SecurityIncident(
                primary_account_id=account.id,
                anchor_transaction_id=transaction.id,
                status="OPEN",
                opened_at=now,
                last_activity_at=now,
                risk_score=55,
                risk_band="ELEVATED",
                risk_policy_version="1.0",
                risk_explanation="Synthetic rule evidence produced this persisted incident.",
                risk_evidence=[{"family": "velocity", "weight": 30, "rule_ids": ["FGX.TEST"]}],
            )
            db.add(incident)
            db.flush()
            evaluation = RuleEvaluationRecord(
                rule_id="FGX.TEST.RAPID_BURST",
                rule_version="1.0",
                rule_name="Rapid transfer burst",
                rule_description="Synthetic test rule.",
                transaction_id=transaction.id,
                relevant_account_id=account.id,
                detected_at=now,
                severity="HIGH",
                evaluation_outcome="TRIGGERED",
                explanation="Five completed transfers occurred within the configured window.",
                required_features=["prior_outgoing_count"],
                minimum_history="No fixed baseline.",
                evidence=[{"name": "count", "value": 5, "unit": "transfers"}],
                incident_id=incident.id,
            )
            db.add_all([
                evaluation,
                IncidentLifecycleEvent(
                    incident_id=incident.id,
                    from_status=None,
                    to_status="OPEN",
                    actor_identifier="system",
                    note="Incident opened from synthetic test evidence.",
                    changed_at=now,
                ),
            ])
            self.incident_id = incident.id
            self.transaction_id = transaction.id

    def tearDown(self):
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_dashboard_recent_transactions_detections_and_incident_filters(self):
        with self.Session() as db:
            summary = DashboardSummaryResponse.model_validate(dashboard_summary(db))
            transactions = [RecentTransactionResponse.model_validate(row) for row in recent_transactions(limit=20, db=db)]
            detections = [RecentDetectionResponse.model_validate(row) for row in recent_detections(limit=20, db=db)]
            incidents = IncidentListResponse.model_validate(
                list_incidents(status_filter="OPEN", risk_band="ELEVATED", limit=50, offset=0, db=db)
            )
            none = IncidentListResponse.model_validate(
                list_incidents(status_filter="DISMISSED", risk_band=None, limit=50, offset=0, db=db)
            )
        self.assertEqual(summary.transactions_monitored, 1)
        self.assertEqual(summary.active_incidents, 1)
        self.assertIsNone(summary.blocked_transactions)
        self.assertEqual(summary.risk_distribution_total, 1)
        self.assertEqual(str(transactions[0].id), str(self.transaction_id))
        self.assertEqual(transactions[0].risk_band, "ELEVATED")
        self.assertEqual(len(transactions[0].sender_account.split("••")[-1]), 4)
        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0].rule_id, "FGX.TEST.RAPID_BURST")
        self.assertEqual(incidents.total, 1)
        self.assertEqual(incidents.items[0].detection_count, 1)
        self.assertEqual(none.total, 0)

    def test_detail_status_transition_and_notes_persist_in_lifecycle_history(self):
        with self.Session() as db:
            detail = IncidentDetailResponse.model_validate(get_incident(self.incident_id, db))
        self.assertEqual(str(detail.transactions[0].id), str(self.transaction_id))
        self.assertEqual(detail.detections[0].evidence[0].value, 5)
        with self.Session() as db:
            updated = IncidentDetailResponse.model_validate(update_incident_status(
                self.incident_id,
                IncidentStatusUpdateRequest(status="INVESTIGATING", note="Reviewing synthetic evidence."),
                db,
            ))
        self.assertEqual(updated.status, "INVESTIGATING")
        self.assertIsNone(updated.timeline[-1].actor_identifier)
        with self.Session() as db:
            note = IncidentDetailResponse.model_validate(add_incident_note(
                self.incident_id, IncidentNoteRequest(note="Verified the transfer context."), db
            ))
        self.assertEqual(note.timeline[-1].note, "Verified the transfer context.")
        with self.Session() as db:
            refreshed = IncidentDetailResponse.model_validate(get_incident(self.incident_id, db))
        self.assertEqual(refreshed.status, "INVESTIGATING")
        self.assertIn("Verified the transfer context.", [row.note for row in refreshed.timeline])
        with self.Session() as db:
            with self.assertRaises(HTTPException) as invalid_transition:
                update_incident_status(
                    self.incident_id, IncidentStatusUpdateRequest(status="OPEN"), db
                )
        self.assertEqual(invalid_transition.exception.status_code, 409)
        with self.Session() as db:
            with self.assertRaises(HTTPException) as missing:
                get_incident(uuid.uuid4(), db)
        self.assertEqual(missing.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()

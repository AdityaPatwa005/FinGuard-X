"""Opt-in row-lock integration test; requires the outbox migration to be applied."""

import os
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from database import SessionLocal, engine
from event_processing import claim_pending_events
from models import Account
from outbox_models import OutboxEvent
from transaction_models import Transaction


@unittest.skipUnless(
    os.getenv("RUN_POSTGRES_OUTBOX_INTEGRATION") == "1",
    "set RUN_POSTGRES_OUTBOX_INTEGRATION=1 after applying the outbox migration",
)
class PostgreSQLOutboxLockTests(unittest.TestCase):
    """Uses two independent PostgreSQL sessions; not a SQLite/mock concurrency test."""

    def setUp(self):
        if engine.dialect.name != "postgresql":
            self.skipTest("PostgreSQL is required for SELECT FOR UPDATE SKIP LOCKED")
        if engine.url.host not in ("localhost", "127.0.0.1", "::1") or engine.url.database != "finguard_x":
            self.fail("Integration test is restricted to local database finguard_x")

        with SessionLocal.begin() as db:
            account_id = db.scalar(select(Account.id).order_by(Account.id).limit(1))
            if account_id is None:
                self.skipTest("A customer account is required for the outbox foreign key")
            suffix = uuid4().hex
            self.transaction_id = uuid4()
            self.event_id = uuid4()
            db.add(
                Transaction(
                    id=self.transaction_id,
                    sender_account_id=None,
                    receiver_account_id=account_id,
                    transaction_type="FUNDING",
                    amount=Decimal("0.01"),
                    currency="INR",
                    status="COMPLETED",
                    idempotency_key=f"outbox-lock-test:{suffix}",
                    description="Synthetic outbox lock integration test",
                )
            )
            db.flush()
            timestamp = datetime.now(timezone.utc).isoformat()
            event_type = "transaction.funding.completed"
            source = "finbank_simulator_test"
            db.add(
                OutboxEvent(
                    id=self.event_id,
                    event_type=event_type,
                    event_version=1,
                    source_system=source,
                    related_transaction_id=self.transaction_id,
                    deduplication_key=f"transaction:{self.transaction_id}:completed:v1",
                    payload={
                        "event_id": str(self.event_id),
                        "event_type": event_type,
                        "event_version": 1,
                        "source_system": source,
                        "transaction_id": str(self.transaction_id),
                        "transaction_type": "FUNDING",
                        "sender_account_id": None,
                        "receiver_account_id": str(account_id),
                        "amount": "0.01",
                        "currency": "INR",
                        "timestamp": timestamp,
                        "description": "Synthetic outbox lock integration test",
                    },
                )
            )

    def test_two_sessions_cannot_claim_one_event(self):
        first = SessionLocal()
        try:
            first.begin()
            first_claims = claim_pending_events(
                first, batch_size=1, event_ids=[self.event_id]
            )
            self.assertEqual(len(first_claims), 1)

            with SessionLocal() as second:
                with second.begin():
                    second_claims = claim_pending_events(
                        second, batch_size=1, event_ids=[self.event_id]
                    )
            self.assertEqual(second_claims, [])
            first.commit()
        finally:
            if first.in_transaction():
                first.rollback()
            first.close()

        # Leave the synthetic test event in a terminal state after proving the lock.
        with SessionLocal.begin() as db:
            row = db.get(OutboxEvent, self.event_id)
            row.processing_status = "PROCESSED"
            row.processing_started_at = None
            row.processing_token = None
            row.processed_at = datetime.now(timezone.utc)


if __name__ == "__main__":
    unittest.main()

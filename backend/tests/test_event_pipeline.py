import unittest
import uuid
from decimal import Decimal
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from event_processing import (
    EventNormalizationError,
    claim_pending_events,
    normalize_transaction_event,
    process_event_batch,
)
from ledger_models import LedgerAccount
from models import Account, Base, User
from outbox_models import OutboxEvent
from transaction_service import funding_transaction, transfer_transaction
from transaction_models import LedgerEntry, Transaction


class EventPipelineTests(unittest.TestCase):
    """SQLite-backed service tests; SQLite does not emulate PostgreSQL row locks."""

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
        self.Session = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )
        with self.Session.begin() as db:
            user = User(full_name="Synthetic Outbox Test", email=f"{uuid.uuid4()}@example.test")
            db.add(user)
            db.flush()
            self.sender = Account(
                user_id=user.id,
                account_number=f"OB{uuid.uuid4().hex[:32]}",
                account_type="savings",
                balance=Decimal("100.00"),
                currency="INR",
                status="active",
            )
            self.receiver = Account(
                user_id=user.id,
                account_number=f"OB{uuid.uuid4().hex[:32]}",
                account_type="savings",
                balance=Decimal("20.00"),
                currency="INR",
                status="active",
            )
            db.add_all([self.sender, self.receiver])
            db.flush()
            db.add_all(
                [
                    LedgerAccount(
                        bank_account_id=account.id,
                        account_type="CUSTOMER",
                        name=f"Customer ledger {account.account_number}",
                    )
                    for account in (self.sender, self.receiver)
                ]
                + [
                    LedgerAccount(
                        account_type="FUNDING_POOL",
                        bank_account_id=None,
                        name="FinBank Simulator Funding Pool",
                    )
                ]
            )

    def tearDown(self):
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _events(self, transaction_id):
        with self.Session() as db:
            return db.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.related_transaction_id == transaction_id
                )
            ).all()

    def _transaction_for_key(self, key):
        with self.Session() as db:
            return db.scalar(
                select(Transaction).where(Transaction.idempotency_key == key)
            )

    def test_successful_funding_creates_exactly_one_safe_event(self):
        with self.Session() as db:
            result = funding_transaction(
                db,
                account_id=self.receiver.id,
                amount=Decimal("12.30"),
                idempotency_key="outbox-funding-test",
                description="Synthetic funding",
            )
        events = self._events(result.transaction.id)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "transaction.funding.completed")
        self.assertEqual(events[0].processing_status, "PENDING")
        self.assertEqual(events[0].payload["event_id"], str(events[0].id))
        self.assertEqual(events[0].payload["amount"], "12.30")
        self.assertNotIn("email", events[0].payload)

    def test_successful_transfer_creates_exactly_one_event(self):
        with self.Session() as db:
            result = transfer_transaction(
                db,
                sender_account_id=self.sender.id,
                receiver_account_id=self.receiver.id,
                amount=Decimal("10.00"),
                idempotency_key="outbox-transfer-test",
                description="Synthetic transfer",
            )
        events = self._events(result.transaction.id)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "transaction.transfer.completed")
        self.assertEqual(events[0].payload["sender_account_id"], str(self.sender.id))

    def test_failed_financial_operation_creates_no_event(self):
        with self.Session() as db:
            with self.assertRaises(HTTPException):
                transfer_transaction(
                    db,
                    sender_account_id=self.sender.id,
                    receiver_account_id=self.receiver.id,
                    amount=Decimal("100.01"),
                    idempotency_key="outbox-failed-transfer-test",
                    description=None,
                )
        self.assertIsNone(self._transaction_for_key("outbox-failed-transfer-test"))
        with self.Session() as db:
            self.assertEqual(db.scalar(select(OutboxEvent.id)), None)

    def test_event_insert_failure_rolls_back_financial_operation(self):
        with patch(
            "transaction_service.add_transaction_completed_event",
            side_effect=SQLAlchemyError("synthetic event write failure"),
        ):
            with self.Session() as db:
                with self.assertRaises(HTTPException) as raised:
                    funding_transaction(
                        db,
                        account_id=self.receiver.id,
                        amount=Decimal("5.00"),
                        idempotency_key="outbox-failure-rollback-test",
                        description=None,
                    )
        self.assertEqual(raised.exception.status_code, 503)
        self.assertIsNone(self._transaction_for_key("outbox-failure-rollback-test"))
        with self.Session() as db:
            self.assertEqual(
                db.scalar(select(Account.balance).where(Account.id == self.receiver.id)),
                Decimal("20.00"),
            )
            self.assertEqual(db.scalar(select(LedgerEntry.id)), None)
            self.assertEqual(db.scalar(select(OutboxEvent.id)), None)

    def test_processed_event_is_not_claimed_or_processed_twice(self):
        with self.Session() as db:
            result = funding_transaction(
                db,
                account_id=self.receiver.id,
                amount=Decimal("1.00"),
                idempotency_key="outbox-process-once-test",
                description=None,
            )
        first = process_event_batch(self.Session, batch_size=10)
        second = process_event_batch(self.Session, batch_size=10)
        self.assertEqual((first.claimed, first.processed, first.failed), (1, 1, 0))
        self.assertEqual((second.claimed, second.processed, second.failed), (0, 0, 0))
        event_row = self._events(result.transaction.id)[0]
        self.assertEqual(event_row.processing_status, "PROCESSED")
        self.assertEqual(event_row.attempt_count, 1)
        self.assertIsNotNone(event_row.processed_at)

    def test_invalid_payload_is_retained_as_failed_and_retryable(self):
        with self.Session() as db:
            result = funding_transaction(
                db,
                account_id=self.receiver.id,
                amount=Decimal("2.00"),
                idempotency_key="outbox-retry-test",
                description=None,
            )
        with self.Session.begin() as db:
            row = db.scalar(
                select(OutboxEvent).where(
                    OutboxEvent.related_transaction_id == result.transaction.id
                )
            )
            row.payload = {**row.payload, "amount": "not-a-number"}

        first = process_event_batch(self.Session, batch_size=10)
        row = self._events(result.transaction.id)[0]
        self.assertEqual((first.claimed, first.processed, first.failed), (1, 0, 1))
        self.assertEqual(row.processing_status, "FAILED")
        self.assertEqual(row.attempt_count, 1)
        self.assertNotIn("not-a-number", row.last_error)

        with self.Session.begin() as db:
            row = db.scalar(
                select(OutboxEvent).where(
                    OutboxEvent.related_transaction_id == result.transaction.id
                )
            )
            row.payload = {**row.payload, "amount": "2.00"}
        retry = process_event_batch(self.Session, batch_size=10)
        row = self._events(result.transaction.id)[0]
        self.assertEqual((retry.claimed, retry.processed, retry.failed), (1, 1, 0))
        self.assertEqual(row.processing_status, "PROCESSED")
        self.assertEqual(row.attempt_count, 2)

    def test_sequential_claims_and_postgresql_skip_locked_sql(self):
        with self.Session() as db:
            funding_transaction(
                db,
                account_id=self.receiver.id,
                amount=Decimal("1.00"),
                idempotency_key="outbox-claim-test",
                description=None,
            )
        with self.Session() as db:
            with db.begin():
                first = claim_pending_events(db, batch_size=1)
        with self.Session() as db:
            with db.begin():
                second = claim_pending_events(db, batch_size=1)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        statement = select(OutboxEvent).with_for_update(skip_locked=True)
        sql = str(statement.compile(dialect=postgresql.dialect()))
        self.assertIn("FOR UPDATE SKIP LOCKED", sql)

    def test_normalization_accepts_valid_envelope_and_rejects_malformed_payload(self):
        with self.Session() as db:
            result = funding_transaction(
                db,
                account_id=self.receiver.id,
                amount=Decimal("4.50"),
                idempotency_key="outbox-normalize-test",
                description="Synthetic normalize",
            )
        row = self._events(result.transaction.id)[0]
        from event_processing import normalize_transaction_event

        normalized = normalize_transaction_event(
            event_id=row.id,
            event_type=row.event_type,
            event_version=row.event_version,
            source_system=row.source_system,
            related_transaction_id=row.related_transaction_id,
            payload=row.payload,
        )
        self.assertEqual(normalized.amount, Decimal("4.50"))
        self.assertEqual(normalized.currency, "INR")
        self.assertEqual(normalized.original_payload, row.payload)
        with self.assertRaises(EventNormalizationError):
            normalize_transaction_event(
                event_id=row.id,
                event_type=row.event_type,
                event_version=row.event_version,
                source_system=row.source_system,
                related_transaction_id=row.related_transaction_id,
                payload={**row.payload, "timestamp": "not-a-timestamp"},
            )
        with self.assertRaises(EventNormalizationError):
            normalize_transaction_event(
                event_id=row.id,
                event_type=row.event_type,
                event_version=row.event_version,
                source_system=row.source_system,
                related_transaction_id=row.related_transaction_id,
                payload={**row.payload, "amount": 4.5},
            )


if __name__ == "__main__":
    unittest.main()

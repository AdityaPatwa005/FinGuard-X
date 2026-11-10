import unittest
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ledger_models import LedgerAccount
from models import Account, Base, User
from schemas import FundingRequest, TransferRequest
from transaction_models import LedgerEntry, Transaction
import transaction_service
from transaction_service import (
    account_lock_statement,
    funding_transaction,
    transfer_transaction,
)


class TransactionServiceTests(unittest.TestCase):
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
        with self.Session.begin() as session:
            user = User(full_name="Synthetic Test User", email=f"{uuid.uuid4()}@example.test")
            session.add(user)
            session.flush()
            self.sender = Account(
                user_id=user.id,
                account_number=f"FG{uuid.uuid4().hex[:16]}",
                account_type="savings",
                balance=Decimal("100.00"),
                currency="INR",
                status="active",
            )
            self.receiver = Account(
                user_id=user.id,
                account_number=f"FG{uuid.uuid4().hex[:16]}",
                account_type="savings",
                balance=Decimal("20.00"),
                currency="INR",
                status="active",
            )
            self.inactive = Account(
                user_id=user.id,
                account_number=f"FG{uuid.uuid4().hex[:16]}",
                account_type="savings",
                balance=Decimal("5.00"),
                currency="INR",
                status="inactive",
            )
            session.add_all([self.sender, self.receiver, self.inactive])
            session.flush()
            session.add_all(
                [
                    LedgerAccount(
                        bank_account_id=account.id,
                        account_type="CUSTOMER",
                        name=f"Customer ledger {account.account_number}",
                    )
                    for account in (self.sender, self.receiver, self.inactive)
                ]
                + [
                    LedgerAccount(
                        bank_account_id=None,
                        account_type="FUNDING_POOL",
                        name="FinBank Simulator Funding Pool",
                    )
                ]
            )

    def tearDown(self):
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _balance(self, account_id):
        with self.Session() as session:
            return session.scalar(select(Account.balance).where(Account.id == account_id))

    def _transaction_and_entries(self, idempotency_key):
        with self.Session() as session:
            transaction = session.scalar(
                select(Transaction).where(Transaction.idempotency_key == idempotency_key)
            )
            entries = session.scalars(
                select(LedgerEntry).where(LedgerEntry.transaction_id == transaction.id)
            ).all() if transaction else []
            return transaction, entries

    def test_successful_funding_balances_entries_and_cached_balance(self):
        with self.Session() as session:
            result = funding_transaction(
                session,
                account_id=self.receiver.id,
                amount=Decimal("35.25"),
                idempotency_key="funding-test-0001",
                description="Synthetic test funding",
            )

        self.assertEqual(self._balance(self.receiver.id), Decimal("55.25"))
        transaction, entries = self._transaction_and_entries("funding-test-0001")
        self.assertEqual(transaction.transaction_type, "FUNDING")
        self.assertEqual(transaction.status, "COMPLETED")
        self.assertIsNone(transaction.sender_account_id)
        self.assertEqual(transaction.receiver_account_id, self.receiver.id)
        self.assertEqual(len(entries), 2)
        self.assertEqual({entry.entry_type for entry in entries}, {"DEBIT", "CREDIT"})
        self.assertEqual(sum((entry.amount for entry in entries), Decimal("0")), Decimal("70.50"))
        self.assertEqual({entry.amount for entry in entries}, {Decimal("35.25")})
        self.assertFalse(result.replayed)

    def test_successful_transfer_is_balanced_and_updates_both_balances(self):
        with self.Session() as session:
            result = transfer_transaction(
                session,
                sender_account_id=self.sender.id,
                receiver_account_id=self.receiver.id,
                amount=Decimal("30.10"),
                idempotency_key="transfer-test-0001",
                description="Synthetic transfer",
            )

        self.assertEqual(self._balance(self.sender.id), Decimal("69.90"))
        self.assertEqual(self._balance(self.receiver.id), Decimal("50.10"))
        transaction, entries = self._transaction_and_entries("transfer-test-0001")
        self.assertEqual(transaction.status, "COMPLETED")
        self.assertEqual(len(entries), 2)
        self.assertEqual(sum((entry.amount for entry in entries if entry.entry_type == "DEBIT"), Decimal("0")), transaction.amount)
        self.assertEqual(sum((entry.amount for entry in entries if entry.entry_type == "CREDIT"), Decimal("0")), transaction.amount)
        self.assertEqual(result.transaction.id, transaction.id)

    def test_insufficient_funds_roll_back_everything(self):
        with self.Session() as session:
            with self.assertRaises(HTTPException) as error:
                transfer_transaction(
                    session,
                    sender_account_id=self.sender.id,
                    receiver_account_id=self.receiver.id,
                    amount=Decimal("100.01"),
                    idempotency_key="transfer-insufficient-0001",
                    description=None,
                )
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self._balance(self.sender.id), Decimal("100.00"))
        self.assertEqual(self._balance(self.receiver.id), Decimal("20.00"))
        self.assertIsNone(self._transaction_and_entries("transfer-insufficient-0001")[0])

    def test_missing_sender_is_reported_before_transaction_insert(self):
        missing_sender_id = uuid.uuid4()
        with self.Session() as session:
            with self.assertRaises(HTTPException) as error:
                transfer_transaction(
                    session,
                    sender_account_id=missing_sender_id,
                    receiver_account_id=self.receiver.id,
                    amount=Decimal("1.00"),
                    idempotency_key="transfer-missing-sender-0001",
                    description=None,
                )

        self.assertEqual(error.exception.status_code, 404)
        self.assertIsNone(self._transaction_and_entries("transfer-missing-sender-0001")[0])
        self.assertEqual(self._balance(self.receiver.id), Decimal("20.00"))

    def test_unexpected_integrity_error_is_logged_safely_and_rolled_back(self):
        constraint = "outbox_events_transaction_id_fkey"
        original_error = SimpleNamespace(
            sqlstate="23503",
            diag=SimpleNamespace(constraint_name=constraint),
        )
        database_error = IntegrityError("statement omitted", {}, original_error)
        session = self.Session()

        with patch.object(
            transaction_service,
            "add_transaction_completed_event",
            side_effect=database_error,
        ), self.assertLogs("transaction_service", level="ERROR") as captured:
            with self.assertRaises(HTTPException) as error:
                transfer_transaction(
                    session,
                    sender_account_id=self.sender.id,
                    receiver_account_id=self.receiver.id,
                    amount=Decimal("10.00"),
                    idempotency_key="transfer-integrity-diagnostic-0001",
                    description=None,
                )
        session.close()

        self.assertEqual(error.exception.status_code, 500)
        self.assertNotIn("23503", error.exception.detail)
        self.assertNotIn(constraint, error.exception.detail)
        log_output = "\n".join(captured.output)
        self.assertIn("operation=TRANSFER", log_output)
        self.assertIn("phase=outbox_event_creation", log_output)
        self.assertIn("sqlstate=23503", log_output)
        self.assertIn(f"constraint={constraint}", log_output)
        self.assertNotIn(str(self.sender.id), log_output)
        self.assertNotIn("transfer-integrity-diagnostic-0001", log_output)
        self.assertEqual(self._balance(self.sender.id), Decimal("100.00"))
        self.assertEqual(self._balance(self.receiver.id), Decimal("20.00"))
        self.assertIsNone(
            self._transaction_and_entries("transfer-integrity-diagnostic-0001")[0]
        )

    def test_inactive_accounts_are_rejected(self):
        with self.Session() as session:
            with self.assertRaises(HTTPException) as error:
                funding_transaction(
                    session,
                    account_id=self.inactive.id,
                    amount=Decimal("2.00"),
                    idempotency_key="funding-inactive-0001",
                    description=None,
                )
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self._balance(self.inactive.id), Decimal("5.00"))
        self.assertIsNone(self._transaction_and_entries("funding-inactive-0001")[0])

    def test_same_account_transfer_is_rejected(self):
        with self.Session() as session:
            with self.assertRaises(HTTPException) as error:
                transfer_transaction(
                    session,
                    sender_account_id=self.sender.id,
                    receiver_account_id=self.sender.id,
                    amount=Decimal("1.00"),
                    idempotency_key="transfer-same-account-0001",
                    description=None,
                )
        self.assertEqual(error.exception.status_code, 422)
        self.assertEqual(self._balance(self.sender.id), Decimal("100.00"))

    def test_invalid_amounts_are_rejected_by_schema_and_service(self):
        with self.assertRaises(ValidationError):
            FundingRequest(account_id=self.receiver.id, amount=Decimal("0"))
        with self.assertRaises(ValidationError):
            FundingRequest(account_id=self.receiver.id, amount=Decimal("1.001"))
        with self.Session() as session:
            with self.assertRaises(HTTPException):
                funding_transaction(
                    session,
                    account_id=self.receiver.id,
                    amount=Decimal("-1.00"),
                    idempotency_key="funding-negative-0001",
                    description=None,
                )

    def test_idempotency_replay_does_not_apply_transfer_twice(self):
        with self.Session() as session:
            first = transfer_transaction(
                session,
                sender_account_id=self.sender.id,
                receiver_account_id=self.receiver.id,
                amount=Decimal("10.00"),
                idempotency_key="transfer-retry-0001",
                description="same request",
            )
        with self.Session() as session:
            replay = transfer_transaction(
                session,
                sender_account_id=self.sender.id,
                receiver_account_id=self.receiver.id,
                amount=Decimal("10.00"),
                idempotency_key="transfer-retry-0001",
                description="same request",
            )
        self.assertFalse(first.replayed)
        self.assertTrue(replay.replayed)
        self.assertEqual(first.transaction.id, replay.transaction.id)
        self.assertEqual(self._balance(self.sender.id), Decimal("90.00"))
        self.assertEqual(self._balance(self.receiver.id), Decimal("30.00"))
        self.assertEqual(self._transaction_and_entries("transfer-retry-0001")[1].__len__(), 2)

    def test_idempotency_key_cannot_be_reused_for_different_payload(self):
        with self.Session() as session:
            transfer_transaction(
                session,
                sender_account_id=self.sender.id,
                receiver_account_id=self.receiver.id,
                amount=Decimal("10.00"),
                idempotency_key="transfer-payload-0001",
                description=None,
            )
        with self.Session() as session:
            with self.assertRaises(HTTPException) as error:
                transfer_transaction(
                    session,
                    sender_account_id=self.sender.id,
                    receiver_account_id=self.receiver.id,
                    amount=Decimal("11.00"),
                    idempotency_key="transfer-payload-0001",
                    description=None,
                )
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self._balance(self.sender.id), Decimal("90.00"))

    def test_concurrent_idempotency_constraint_replays_matching_request(self):
        key = "transfer-idempotency-race-0001"
        with self.Session() as session:
            original_result = transfer_transaction(
                session,
                sender_account_id=self.sender.id,
                receiver_account_id=self.receiver.id,
                amount=Decimal("10.00"),
                idempotency_key=key,
                description="same request",
            )

        session = self.Session()
        postgres_error = IntegrityError(
            "statement omitted",
            {},
            SimpleNamespace(
                sqlstate="23505",
                diag=SimpleNamespace(
                    constraint_name="uq_transactions_idempotency_key"
                ),
            ),
        )
        original_find = transaction_service._find_transaction
        lookup_count = 0

        def mimic_concurrent_claim(db, idempotency_key):
            nonlocal lookup_count
            lookup_count += 1
            if lookup_count == 1:
                return None
            return original_find(db, idempotency_key)

        def fail_transaction_insert(_session, _flush_context, _instances):
            if any(
                isinstance(instance, Transaction)
                and instance.idempotency_key == key
                for instance in _session.new
            ):
                raise postgres_error

        event.listen(session, "before_flush", fail_transaction_insert)
        try:
            with patch.object(
                transaction_service, "_find_transaction", side_effect=mimic_concurrent_claim
            ):
                replay = transfer_transaction(
                    session,
                    sender_account_id=self.sender.id,
                    receiver_account_id=self.receiver.id,
                    amount=Decimal("10.00"),
                    idempotency_key=key,
                    description="same request",
                )
        finally:
            event.remove(session, "before_flush", fail_transaction_insert)
            session.close()

        self.assertTrue(replay.replayed)
        self.assertEqual(replay.transaction.id, original_result.transaction.id)
        self.assertEqual(self._balance(self.sender.id), Decimal("90.00"))
        self.assertEqual(self._balance(self.receiver.id), Decimal("30.00"))

    def test_failed_ledger_flush_rolls_back_transaction_and_balances(self):
        session = self.Session()
        flush_count = 0

        def fail_second_flush(_session, _flush_context, _instances):
            nonlocal flush_count
            flush_count += 1
            if flush_count == 2:
                raise RuntimeError("simulated ledger write failure")

        event.listen(session, "before_flush", fail_second_flush)
        try:
            with self.assertRaisesRegex(RuntimeError, "simulated ledger write failure"):
                transfer_transaction(
                    session,
                    sender_account_id=self.sender.id,
                    receiver_account_id=self.receiver.id,
                    amount=Decimal("25.00"),
                    idempotency_key="transfer-rollback-0001",
                    description=None,
                )
        finally:
            event.remove(session, "before_flush", fail_second_flush)
            session.close()

        self.assertEqual(self._balance(self.sender.id), Decimal("100.00"))
        self.assertEqual(self._balance(self.receiver.id), Decimal("20.00"))
        self.assertIsNone(self._transaction_and_entries("transfer-rollback-0001")[0])

    def test_repeat_transfer_and_postgresql_row_lock_query(self):
        lock_sql = str(
            account_lock_statement([self.sender.id, self.receiver.id]).compile(
                dialect=postgresql.dialect()
            )
        )
        self.assertIn("FOR UPDATE", lock_sql)

        # A repeated idempotent request is safe even when run by a retrying client.
        with self.Session() as session:
            transfer_transaction(
                session,
                sender_account_id=self.sender.id,
                receiver_account_id=self.receiver.id,
                amount=Decimal("5.00"),
                idempotency_key="transfer-repeat-0001",
                description=None,
            )
        with self.Session() as session:
            replay = transfer_transaction(
                session,
                sender_account_id=self.sender.id,
                receiver_account_id=self.receiver.id,
                amount=Decimal("5.00"),
                idempotency_key="transfer-repeat-0001",
                description=None,
            )
        self.assertTrue(replay.replayed)
        self.assertEqual(self._balance(self.sender.id), Decimal("95.00"))


if __name__ == "__main__":
    unittest.main()

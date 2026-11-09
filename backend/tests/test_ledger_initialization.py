import unittest
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql.dml import Insert
from sqlalchemy.sql import Select

from ledger_models import LedgerAccount
from main import register_customer
from models import Account, User
from schemas import CustomerCreate
from scripts import backfill_customer_ledger_accounts as customer_backfill
from scripts import initialize_funding_pool as funding_pool


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return list(self.rows)

    def scalars(self):
        return self

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class FakeLedgerSession:
    """Small stateful stand-in for testing initialization logic without a DB."""

    def __init__(self, accounts=(), linked=(), conflict_ids=(), fail_on_execute=False):
        self.accounts = list(accounts)
        self.ledger_by_account = {row[0]: row[1] for row in linked}
        self.conflict_ids = set(conflict_ids)
        self.funding_pool = None
        self.statements = []
        self.fail_on_execute = fail_on_execute

    def execute(self, statement):
        if self.fail_on_execute:
            raise RuntimeError("simulated database failure")
        self.statements.append(statement)
        if isinstance(statement, Select):
            rows = [
                (account_id, account_number, self.ledger_by_account.get(account_id))
                for account_id, account_number in self.accounts
            ]
            return FakeResult(rows)

        if isinstance(statement, Insert):
            compiled = statement.compile(dialect=postgresql.dialect())
            params = compiled.params
            if "FUNDING_POOL" in params.values():
                if self.funding_pool is not None:
                    return FakeResult([])
                pool_id = next(
                    value for key, value in params.items() if key.startswith("id")
                )
                self.funding_pool = {
                    "id": pool_id,
                    "bank_account_id": None,
                    "account_type": "FUNDING_POOL",
                    "name": funding_pool.FUNDING_POOL_NAME,
                }
                return FakeResult([pool_id])

            inserted_ids = []
            for row in statement._multi_values[0]:
                values = {column.name: value for column, value in row.items()}
                account_id = values["bank_account_id"]
                if account_id in self.ledger_by_account or account_id in self.conflict_ids:
                    continue
                self.ledger_by_account[account_id] = values["id"]
                inserted_ids.append(account_id)
            return FakeResult(inserted_ids)

        raise AssertionError(f"Unexpected statement type: {type(statement).__name__}")


class FakeSessionFactory:
    def __init__(self, session):
        self.session = session
        self.commits = 0
        self.rollbacks = 0

    @contextmanager
    def begin(self):
        try:
            yield self.session
        except Exception:
            self.rollbacks += 1
            raise
        else:
            self.commits += 1


class FakeRegistrationSession:
    def __init__(self):
        self.pending = []
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0

    @contextmanager
    def begin(self):
        try:
            yield self
        except Exception:
            self.rollbacks += 1
            raise
        else:
            self.commits += 1

    def scalar(self, _statement):
        return None

    def add(self, instance):
        self.pending.append(instance)

    def flush(self):
        self.flushes += 1
        pending_objects = list(self.pending)
        for instance in self.pending:
            if isinstance(instance, User):
                pending_objects.extend(instance.accounts)
        for instance in pending_objects:
            if isinstance(instance, (User, Account, LedgerAccount)) and instance.id is None:
                instance.id = uuid.uuid4()
            if isinstance(instance, Account):
                instance.balance = Decimal("0.00")
                instance.currency = "INR"
                instance.status = "active"
                instance.created_at = datetime.now(timezone.utc)

    def refresh(self, _instance):
        pass


class LedgerInitializationTests(unittest.TestCase):
    def test_new_customer_registration_links_customer_ledger_in_transaction(self):
        session = FakeRegistrationSession()
        response = register_customer(
            CustomerCreate(full_name="Demo Customer", email="demo@example.test"),
            session,
        )

        self.assertEqual(session.commits, 1)
        self.assertEqual(session.rollbacks, 0)
        self.assertEqual(session.flushes, 2)
        self.assertEqual(response.account.balance, Decimal("0.00"))
        account = next(instance for instance in session.pending if isinstance(instance, User)).accounts[0]
        ledger = next(instance for instance in session.pending if isinstance(instance, LedgerAccount))
        self.assertEqual(ledger.bank_account_id, account.id)
        self.assertEqual(ledger.account_type, "CUSTOMER")
        self.assertEqual(ledger.name, f"Customer ledger {account.account_number}")

    def test_customer_backfill_is_idempotent_and_reports_counts(self):
        first_id, second_id, third_id = (uuid.uuid4() for _ in range(3))
        preexisting_ledger_id = uuid.uuid4()
        session = FakeLedgerSession(
            accounts=[
                (first_id, "FG0000000000000001"),
                (second_id, "FG0000000000000002"),
                (third_id, "FG0000000000000003"),
            ],
            linked=[(first_id, preexisting_ledger_id)],
        )

        first_result = customer_backfill.backfill_customer_ledger_accounts(session)
        self.assertEqual(first_result, (3, 2, 2, 1))
        self.assertEqual(len(session.ledger_by_account), 3)
        self.assertEqual(session.ledger_by_account[first_id], preexisting_ledger_id)

        insert_statement = next(stmt for stmt in session.statements if isinstance(stmt, Insert))
        sql = str(insert_statement.compile(dialect=postgresql.dialect()))
        self.assertIn("ON CONFLICT (bank_account_id) WHERE bank_account_id IS NOT NULL DO NOTHING", sql)
        inserted_rows = insert_statement._multi_values[0]
        inserted_values = [
            {column.name: value for column, value in row.items()}
            for row in inserted_rows
        ]
        self.assertEqual(
            {row["name"] for row in inserted_values},
            {"Customer ledger FG0000000000000002", "Customer ledger FG0000000000000003"},
        )
        self.assertTrue(all(row["account_type"] == "CUSTOMER" for row in inserted_values))
        self.assertEqual({row["bank_account_id"] for row in inserted_values}, {second_id, third_id})

        second_result = customer_backfill.backfill_customer_ledger_accounts(session)
        self.assertEqual(second_result, (3, 0, 0, 3))
        self.assertEqual(len(session.ledger_by_account), 3)

    def test_customer_backfill_ignores_concurrent_unique_conflicts(self):
        account_ids = [uuid.uuid4(), uuid.uuid4()]
        session = FakeLedgerSession(
            accounts=[(account_ids[0], "FG0000000000000011"), (account_ids[1], "FG0000000000000012")],
            conflict_ids=[account_ids[0]],
        )

        total, missing, inserted, skipped = customer_backfill.backfill_customer_ledger_accounts(session)
        self.assertEqual((total, missing, inserted, skipped), (2, 2, 1, 1))
        self.assertEqual(set(session.ledger_by_account), {account_ids[1]})

    def test_funding_pool_initializer_inserts_at_most_one(self):
        session = FakeLedgerSession()

        self.assertTrue(funding_pool.ensure_funding_pool(session))
        created_pool = session.funding_pool
        self.assertFalse(funding_pool.ensure_funding_pool(session))
        self.assertEqual(session.funding_pool, created_pool)
        self.assertEqual(created_pool["bank_account_id"], None)
        self.assertEqual(created_pool["account_type"], "FUNDING_POOL")
        self.assertEqual(created_pool["name"], "FinBank Simulator Funding Pool")

        sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
        self.assertIn("ON CONFLICT (account_type) WHERE account_type = 'FUNDING_POOL' DO NOTHING", sql)

    def test_run_wrappers_use_one_transaction(self):
        session = FakeLedgerSession()
        factory = FakeSessionFactory(session)
        with patch.object(customer_backfill, "SessionLocal", factory):
            self.assertEqual(customer_backfill.run_backfill(), (0, 0, 0, 0))
        self.assertEqual((factory.commits, factory.rollbacks), (1, 0))

        factory = FakeSessionFactory(FakeLedgerSession())
        with patch.object(funding_pool, "SessionLocal", factory):
            self.assertTrue(funding_pool.run_initialization())
        self.assertEqual((factory.commits, factory.rollbacks), (1, 0))

    def test_backfill_error_rolls_back_transaction(self):
        factory = FakeSessionFactory(FakeLedgerSession(fail_on_execute=True))
        with patch.object(customer_backfill, "SessionLocal", factory):
            with self.assertRaisesRegex(RuntimeError, "simulated database failure"):
                customer_backfill.run_backfill()
        self.assertEqual((factory.commits, factory.rollbacks), (0, 1))


if __name__ == "__main__":
    unittest.main()

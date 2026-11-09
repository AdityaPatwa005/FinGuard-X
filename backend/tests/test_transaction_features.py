import unittest
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Account, Base, User
from transaction_features import TransactionNotFoundError, extract_transaction_features
from transaction_models import Transaction


UTC = timezone.utc
AS_OF = datetime(2025, 6, 15, 12, 0, tzinfo=UTC)


class TransactionFeatureTests(unittest.TestCase):
    """Deterministic SQLite tests; query logic remains PostgreSQL compatible."""

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
            user = User(
                full_name="Synthetic Feature Test",
                email=f"{uuid.uuid4()}@example.test",
            )
            db.add(user)
            db.flush()
            self.sender = Account(
                user_id=user.id,
                account_number=f"FT{uuid.uuid4().hex[:32]}",
                account_type="savings",
            )
            self.receiver = Account(
                user_id=user.id,
                account_number=f"FT{uuid.uuid4().hex[:32]}",
                account_type="savings",
            )
            self.other_receiver = Account(
                user_id=user.id,
                account_number=f"FT{uuid.uuid4().hex[:32]}",
                account_type="savings",
            )
            db.add_all([self.sender, self.receiver, self.other_receiver])

    def tearDown(self):
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def add_transaction(
        self,
        *,
        created_at,
        amount="1.00",
        transaction_type="TRANSFER",
        sender_id=None,
        receiver_id=None,
        status="COMPLETED",
        key=None,
    ):
        if transaction_type == "TRANSFER":
            sender_id = sender_id or self.sender.id
            receiver_id = receiver_id or self.receiver.id
        else:
            sender_id = None
            receiver_id = receiver_id or self.sender.id
        transaction = Transaction(
            sender_account_id=sender_id,
            receiver_account_id=receiver_id,
            transaction_type=transaction_type,
            amount=Decimal(amount),
            currency="INR",
            status=status,
            idempotency_key=key or uuid.uuid4().hex,
            description="Synthetic deterministic feature test",
            created_at=created_at,
        )
        with self.Session.begin() as db:
            db.add(transaction)
            db.flush()
            return transaction.id

    def features_for(self, transaction_id):
        with self.Session() as db:
            return extract_transaction_features(db, transaction_id)

    def test_no_history_has_explicit_missing_baseline_and_zero_windows(self):
        target_id = self.add_transaction(created_at=AS_OF, amount="25.75")
        features = self.features_for(target_id)
        self.assertEqual(features.context.amount, Decimal("25.75"))
        self.assertEqual(features.velocity.prior_5_minute_count, 0)
        self.assertEqual(features.velocity.prior_1_hour_count, 0)
        self.assertEqual(features.velocity.prior_24_hour_count, 0)
        self.assertEqual(features.outgoing_volume.prior_1_hour_amount, Decimal("0.00"))
        self.assertEqual(features.customer_behavior.historical_transfer_count, 0)
        self.assertIsNone(features.customer_behavior.average_amount)
        self.assertIsNone(features.customer_behavior.median_amount)
        self.assertIsNone(features.customer_behavior.amount_deviation_from_average)
        self.assertFalse(features.data_quality.outgoing_baseline_sufficient)
        self.assertFalse(features.data_quality.historical_outgoing_transfer_history_available)

    def test_one_prior_transaction_produces_statistics_but_not_reliable_baseline(self):
        self.add_transaction(created_at=AS_OF - timedelta(hours=2), amount="10.00")
        target_id = self.add_transaction(created_at=AS_OF, amount="30.00")
        features = self.features_for(target_id)
        self.assertEqual(features.customer_behavior.historical_transfer_count, 1)
        self.assertEqual(features.customer_behavior.average_amount, Decimal("10.00"))
        self.assertEqual(features.customer_behavior.median_amount, Decimal("10.00"))
        self.assertEqual(
            features.customer_behavior.amount_deviation_from_average, Decimal("20.00")
        )
        self.assertFalse(features.data_quality.outgoing_baseline_sufficient)

    def test_multiple_history_uses_all_prior_values_for_average_and_median(self):
        for days, amount in ((3, "10.00"), (2, "20.00"), (1, "30.00"), (0, "40.00")):
            self.add_transaction(
                created_at=AS_OF - timedelta(days=days, minutes=1), amount=amount
            )
        target_id = self.add_transaction(created_at=AS_OF, amount="50.00")
        features = self.features_for(target_id)
        self.assertEqual(features.customer_behavior.historical_transfer_count, 4)
        self.assertEqual(features.customer_behavior.average_amount, Decimal("25.00"))
        self.assertEqual(features.customer_behavior.median_amount, Decimal("25.00"))
        self.assertEqual(features.customer_behavior.amount_deviation_from_average, Decimal("25.00"))
        self.assertFalse(features.data_quality.outgoing_baseline_sufficient)

    def test_window_lower_bound_is_included_and_current_timestamp_is_excluded(self):
        self.add_transaction(created_at=AS_OF - timedelta(minutes=5), amount="1.00")
        self.add_transaction(created_at=AS_OF - timedelta(hours=1), amount="2.00")
        self.add_transaction(created_at=AS_OF - timedelta(hours=24), amount="4.00")
        self.add_transaction(created_at=AS_OF - timedelta(hours=24, microseconds=1), amount="8.00")
        # A same-timestamp transaction must not leak into its own history.
        self.add_transaction(created_at=AS_OF, amount="16.00")
        target_id = self.add_transaction(created_at=AS_OF, amount="100.00")
        features = self.features_for(target_id)
        self.assertEqual(features.velocity.prior_5_minute_count, 1)
        self.assertEqual(features.velocity.prior_1_hour_count, 2)
        self.assertEqual(features.velocity.prior_24_hour_count, 3)
        self.assertEqual(features.velocity.prior_outgoing_transfer_5_minute_count, 1)
        self.assertEqual(features.velocity.prior_outgoing_transfer_1_hour_count, 2)
        self.assertEqual(features.outgoing_volume.prior_1_hour_amount, Decimal("3.00"))
        self.assertEqual(features.outgoing_volume.prior_24_hour_amount, Decimal("7.00"))
        self.assertEqual(features.customer_behavior.historical_transfer_count, 4)

    def test_funding_counts_as_account_activity_but_not_outgoing_behavior(self):
        self.add_transaction(
            created_at=AS_OF - timedelta(minutes=5),
            amount="50.00",
            transaction_type="FUNDING",
            receiver_id=self.sender.id,
        )
        self.add_transaction(
            created_at=AS_OF - timedelta(minutes=4), amount="7.00", receiver_id=self.other_receiver.id
        )
        target_id = self.add_transaction(created_at=AS_OF, amount="3.00")
        features = self.features_for(target_id)
        self.assertEqual(features.velocity.prior_5_minute_count, 2)
        self.assertEqual(features.velocity.prior_outgoing_transfer_5_minute_count, 1)
        self.assertEqual(features.customer_behavior.historical_transfer_count, 1)
        self.assertEqual(features.customer_behavior.average_amount, Decimal("7.00"))
        self.assertEqual(features.outgoing_volume.prior_1_hour_amount, Decimal("7.00"))

        funding_id = self.add_transaction(
            created_at=AS_OF + timedelta(minutes=1),
            amount="5.00",
            transaction_type="FUNDING",
            receiver_id=self.sender.id,
        )
        funding_features = self.features_for(funding_id)
        self.assertEqual(funding_features.context.sender_account_id, None)
        self.assertEqual(funding_features.velocity.focal_account_role, "receiver")
        self.assertIsNone(funding_features.velocity.prior_outgoing_transfer_5_minute_count)
        self.assertFalse(funding_features.customer_behavior.applicable)
        self.assertIsNone(funding_features.customer_behavior.historical_transfer_count)
        self.assertIsNone(funding_features.outgoing_volume.prior_24_hour_amount)
        self.assertFalse(funding_features.beneficiary_behavior.applicable)

    def test_beneficiary_seen_status_and_distinct_receivers(self):
        self.add_transaction(
            created_at=AS_OF - timedelta(days=2), amount="8.00", receiver_id=self.receiver.id
        )
        self.add_transaction(
            created_at=AS_OF - timedelta(minutes=5), amount="9.00", receiver_id=self.other_receiver.id
        )
        seen_target = self.add_transaction(created_at=AS_OF, amount="2.00", receiver_id=self.receiver.id)
        new_receiver = Account(
            user_id=self.sender.user_id,
            account_number=f"FT{uuid.uuid4().hex[:32]}",
            account_type="savings",
        )
        with self.Session.begin() as db:
            db.add(new_receiver)
        new_target = self.add_transaction(
            created_at=AS_OF, amount="2.00", receiver_id=new_receiver.id
        )
        seen_features = self.features_for(seen_target)
        new_features = self.features_for(new_target)
        self.assertTrue(seen_features.beneficiary_behavior.previously_received_from_sender)
        self.assertFalse(seen_features.beneficiary_behavior.receiver_seen_in_prior_24_hours)
        self.assertFalse(new_features.beneficiary_behavior.previously_received_from_sender)
        self.assertFalse(new_features.beneficiary_behavior.receiver_seen_in_prior_24_hours)
        self.assertEqual(seen_features.beneficiary_behavior.distinct_receivers_in_prior_24_hours, 1)

    def test_zero_variance_baseline_and_large_amount_deviation_are_safe(self):
        for i in range(5):
            self.add_transaction(
                created_at=AS_OF - timedelta(days=1, minutes=i + 1), amount="10.00"
            )
        target_id = self.add_transaction(created_at=AS_OF, amount="100.00")
        features = self.features_for(target_id)
        self.assertTrue(features.data_quality.outgoing_baseline_sufficient)
        self.assertEqual(features.customer_behavior.average_amount, Decimal("10.00"))
        self.assertEqual(features.customer_behavior.median_amount, Decimal("10.00"))
        self.assertEqual(features.customer_behavior.amount_deviation_from_average, Decimal("90.00"))

    def test_decimal_sums_and_non_completed_rows_are_handled(self):
        self.add_transaction(created_at=AS_OF - timedelta(minutes=3), amount="0.10")
        self.add_transaction(created_at=AS_OF - timedelta(minutes=2), amount="0.20")
        self.add_transaction(
            created_at=AS_OF - timedelta(minutes=1), amount="99.00", status="FAILED"
        )
        self.add_transaction(
            created_at=AS_OF - timedelta(seconds=30), amount="77.00", status="PENDING"
        )
        target_id = self.add_transaction(created_at=AS_OF, amount="1.00")
        features = self.features_for(target_id)
        self.assertEqual(features.velocity.prior_5_minute_count, 2)
        self.assertEqual(features.customer_behavior.historical_transfer_count, 2)
        self.assertEqual(features.outgoing_volume.prior_1_hour_amount, Decimal("0.30"))
        self.assertEqual(features.customer_behavior.average_amount, Decimal("0.15"))
        self.assertEqual(features.customer_behavior.median_amount, Decimal("0.15"))

    def test_temporal_fields_are_utc_and_not_schedule_anomaly_claims(self):
        target_id = self.add_transaction(created_at=AS_OF, amount="1.00")
        features = self.features_for(target_id)
        self.assertEqual(features.temporal.hour_utc, 12)
        self.assertEqual(features.temporal.weekday_utc, 6)
        self.assertEqual(features.context.timestamp.tzinfo, UTC)

    def test_missing_transaction_is_reported(self):
        with self.Session() as db:
            with self.assertRaises(TransactionNotFoundError):
                extract_transaction_features(db, uuid.uuid4())

    def test_extraction_does_not_stage_database_changes(self):
        target_id = self.add_transaction(created_at=AS_OF, amount="3.00")
        with self.Session() as db:
            extract_transaction_features(db, target_id)
            self.assertEqual(len(db.new), 0)
            self.assertEqual(len(db.dirty), 0)
            self.assertEqual(len(db.deleted), 0)


if __name__ == "__main__":
    unittest.main()

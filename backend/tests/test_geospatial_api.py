"""SQLite unit/API coverage; no real coordinates or PostgreSQL data is used."""

import unittest
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import geospatial_models  # noqa: F401
import incident_models  # noqa: F401
import ledger_models  # noqa: F401
import outbox_models  # noqa: F401
import transaction_models  # noqa: F401
from geospatial_models import GeospatialEvent
from incident_models import SecurityIncident
from main import list_geospatial_events, list_geospatial_routes
from models import Account, Base, User
from schemas import GeospatialEventPage, GeospatialRoutePage
from transaction_models import Transaction
from scripts.generate_synthetic_geospatial_events import build_event_rows


class GeospatialApiTests(unittest.TestCase):
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
        now = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
        with self.Session.begin() as db:
            user = User(full_name="Synthetic Geo Test", email=f"{uuid.uuid4()}@example.test")
            db.add(user)
            db.flush()
            self.sender = Account(user_id=user.id, account_number=f"G{uuid.uuid4().hex[:32]}", account_type="savings", balance=Decimal("90.00"), status="active")
            self.receiver = Account(user_id=user.id, account_number=f"G{uuid.uuid4().hex[:32]}", account_type="savings", balance=Decimal("10.00"), status="active")
            db.add_all([self.sender, self.receiver])
            db.flush()
            self.transaction = Transaction(
                sender_account_id=self.sender.id, receiver_account_id=self.receiver.id,
                transaction_type="TRANSFER", amount=Decimal("1.25"), currency="INR",
                status="COMPLETED", idempotency_key=f"geo-test-{uuid.uuid4()}",
                description="Synthetic unit fixture", created_at=now, updated_at=now,
            )
            db.add(self.transaction)
            db.flush()
            self.incident = SecurityIncident(
                primary_account_id=self.sender.id, anchor_transaction_id=self.transaction.id,
                status="OPEN", opened_at=now, last_activity_at=now, risk_score=78,
                risk_band="CRITICAL", risk_policy_version="1.0",
                risk_explanation="Synthetic test incident evidence.", risk_evidence=[],
            )
            db.add(self.incident)
            db.flush()
            self.origin = GeospatialEvent(
                deduplication_key=f"origin:{uuid.uuid4()}", event_type="TRANSACTION_ORIGIN",
                account_id=self.sender.id, transaction_id=self.transaction.id, incident_id=self.incident.id,
                latitude=Decimal("-90.000000"), longitude=Decimal("180.000000"), event_at=now,
                event_metadata={"synthetic": True, "city": "Boundary Demo"},
            )
            self.destination = GeospatialEvent(
                deduplication_key=f"destination:{uuid.uuid4()}", event_type="BENEFICIARY_LOCATION",
                account_id=self.receiver.id, transaction_id=self.transaction.id, incident_id=self.incident.id,
                latitude=Decimal("28.613900"), longitude=Decimal("77.209000"), event_at=now,
                event_metadata={"synthetic": True, "city": "Delhi"},
            )
            self.login = GeospatialEvent(
                deduplication_key=f"login:{uuid.uuid4()}", event_type="LOGIN_LOCATION",
                account_id=self.sender.id, transaction_id=self.transaction.id, incident_id=self.incident.id,
                latitude=Decimal("12.971600"), longitude=Decimal("77.594600"), event_at=now,
                event_metadata={"synthetic": True, "city": "Bengaluru"},
            )
            db.add_all([self.origin, self.destination, self.login])
            db.flush()
            self.route = GeospatialEvent(
                deduplication_key=f"route:{uuid.uuid4()}", event_type="TRANSACTION_ROUTE",
                transaction_id=self.transaction.id, incident_id=self.incident.id,
                origin_event_id=self.origin.id, destination_event_id=self.destination.id,
                origin_event_type="TRANSACTION_ORIGIN", destination_event_type="BENEFICIARY_LOCATION",
                event_at=now, event_metadata={"synthetic": True, "scenario": "unit_fixture"},
            )
            db.add(self.route)

    def tearDown(self):
        with self.engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
            Base.metadata.drop_all(connection)
        self.engine.dispose()

    def test_event_filter_risk_filter_and_pagination(self):
        with self.Session() as db:
            result = list_geospatial_events(
                event_type=None, risk_band="CRITICAL", incident_id=self.incident.id,
                start_at=None, end_at=None, limit=2, offset=1, db=db,
            )
        page = GeospatialEventPage.model_validate(result)
        self.assertEqual(page.total, 4)
        self.assertEqual(len(page.items), 2)
        self.assertEqual(page.items[0].incident_risk_band, "CRITICAL")
        self.assertTrue(page.items[0].metadata.synthetic)

    def test_event_type_filter_returns_only_the_requested_activity(self):
        with self.Session() as db:
            result = list_geospatial_events(
                event_type="LOGIN_LOCATION", risk_band=None, incident_id=None,
                start_at=None, end_at=None, limit=10, offset=0, db=db,
            )
        page = GeospatialEventPage.model_validate(result)
        self.assertEqual(page.total, 1)
        self.assertEqual(page.items[0].event_type, "LOGIN_LOCATION")
        self.assertIsNotNone(page.items[0].coordinate)

    def test_route_uses_explicit_origin_and_beneficiary_events(self):
        with self.Session() as db:
            result = list_geospatial_routes(
                risk_band="CRITICAL", incident_id=self.incident.id,
                start_at=None, end_at=None, limit=10, offset=0, db=db,
            )
        page = GeospatialRoutePage.model_validate(result)
        self.assertEqual(page.total, 1)
        route = page.items[0]
        self.assertEqual(route.origin_event_id, self.origin.id)
        self.assertEqual(route.destination_event_id, self.destination.id)
        self.assertEqual(route.origin.latitude, Decimal("-90.000000"))
        self.assertEqual(route.transaction_id, self.transaction.id)

    def test_empty_data_and_invalid_time_range(self):
        with self.Session() as db:
            empty = list_geospatial_events(
                event_type=None, risk_band=None, incident_id=None,
                start_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
                end_at=datetime(2028, 1, 1, tzinfo=timezone.utc), limit=10, offset=0, db=db,
            )
            with self.assertRaises(HTTPException) as invalid:
                list_geospatial_events(
                    event_type=None, risk_band=None, incident_id=None,
                    start_at=datetime(2026, 11, 11, tzinfo=timezone.utc),
                    end_at=datetime(2026, 11, 10, tzinfo=timezone.utc), limit=10, offset=0, db=db,
                )
        self.assertEqual(GeospatialEventPage.model_validate(empty).total, 0)
        self.assertEqual(invalid.exception.status_code, 422)

    def test_database_rejects_out_of_bounds_coordinates_and_unknown_type(self):
        with self.assertRaises(IntegrityError):
            with self.Session.begin() as db:
                db.add(GeospatialEvent(
                    deduplication_key=f"bad-coordinate:{uuid.uuid4()}", event_type="LOGIN_LOCATION",
                    account_id=self.sender.id, latitude=Decimal("90.000001"), longitude=0,
                    event_at=datetime.now(timezone.utc), event_metadata={"synthetic": True},
                ))
        with self.assertRaises(IntegrityError):
            with self.Session.begin() as db:
                db.add(GeospatialEvent(
                    deduplication_key=f"bad-type:{uuid.uuid4()}", event_type="MADE_UP",
                    account_id=self.sender.id, latitude=0, longitude=0,
                    event_at=datetime.now(timezone.utc), event_metadata={"synthetic": True},
                ))

    def test_route_requires_explicit_distinct_location_references(self):
        with self.assertRaises(IntegrityError):
            with self.Session.begin() as db:
                db.add(GeospatialEvent(
                    deduplication_key=f"bad-route:{uuid.uuid4()}", event_type="TRANSACTION_ROUTE",
                    transaction_id=self.transaction.id, event_at=datetime.now(timezone.utc),
                    event_metadata={"synthetic": True},
                ))

    def test_route_cannot_reference_wrong_location_event_types(self):
        with self.assertRaises(IntegrityError):
            with self.Session.begin() as db:
                db.add(GeospatialEvent(
                    deduplication_key=f"wrong-route-types:{uuid.uuid4()}", event_type="TRANSACTION_ROUTE",
                    transaction_id=self.transaction.id,
                    origin_event_id=self.origin.id, destination_event_id=self.destination.id,
                    origin_event_type="BENEFICIARY_LOCATION", destination_event_type="TRANSACTION_ORIGIN",
                    event_at=datetime.now(timezone.utc), event_metadata={"synthetic": True},
                ))

    def test_generator_is_deterministic_and_does_not_duplicate_planned_keys(self):
        first = build_event_rows([self.transaction], {})
        second = build_event_rows([self.transaction], {})
        self.assertEqual(len(first), 4)
        self.assertEqual([row["id"] for row in first], [row["id"] for row in second])
        self.assertEqual(len({row["deduplication_key"] for row in first}), len(first))
        self.assertTrue(all(row["metadata"]["synthetic"] for row in first))
        route = next(row for row in first if row["event_type"] == "TRANSACTION_ROUTE")
        self.assertIn(route["origin_event_id"], {row["id"] for row in first})
        self.assertIn(route["destination_event_id"], {row["id"] for row in first})


if __name__ == "__main__":
    unittest.main()

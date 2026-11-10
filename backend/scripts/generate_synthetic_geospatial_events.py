"""Idempotently add reproducible, explicitly synthetic location context.

The script only reads completed simulator transactions and writes rows to
geospatial_events. It never changes accounts, balances, ledgers, transactions,
incidents, or detection results.
"""

import argparse
import hashlib
import logging
import sys
import uuid
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import SessionLocal  # noqa: E402
from geospatial_models import GeospatialEvent  # noqa: E402
from incident_models import RuleEvaluationRecord, SecurityIncident  # noqa: E402
from transaction_models import Transaction  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("synthetic_geospatial_generator")

NAMESPACE = uuid.UUID("823c688d-305a-5b7f-9b5f-73ec3d996a1d")
# Deliberately documented, city-centre demo coordinates; not customer/device observations.
CITIES = (
    ("Mumbai", 19.076000, 72.877700),
    ("Delhi", 28.613900, 77.209000),
    ("Bengaluru", 12.971600, 77.594600),
    ("Chennai", 13.082700, 80.270700),
    ("Hyderabad", 17.385000, 78.486700),
    ("Kolkata", 22.572600, 88.363900),
    ("Pune", 18.520400, 73.856700),
    ("Ahmedabad", 23.022500, 72.571400),
)


def _stable_bytes(value: uuid.UUID) -> bytes:
    return hashlib.sha256(value.bytes).digest()


def _geo_id(transaction_id: uuid.UUID, suffix: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{transaction_id}:{suffix}:v1")


def _city(index: int) -> tuple[str, float, float]:
    return CITIES[index % len(CITIES)]


def build_event_rows(transactions: list[Transaction], incident_by_transaction: dict[uuid.UUID, SecurityIncident]) -> list[dict]:
    """Build deterministic event rows without database writes."""
    rows: list[dict] = []

    def add(
        transaction: Transaction,
        suffix: str,
        event_type: str,
        *,
        account_id: uuid.UUID | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        event_at=None,
        metadata: dict,
        incident_id: uuid.UUID | None,
        origin_event_id: uuid.UUID | None = None,
        destination_event_id: uuid.UUID | None = None,
        origin_event_type: str | None = None,
        destination_event_type: str | None = None,
    ) -> uuid.UUID:
        event_id = _geo_id(transaction.id, suffix)
        rows.append(
            {
                "id": event_id,
                "deduplication_key": f"synthetic-geo-v1:{transaction.id}:{suffix}",
                "event_type": event_type,
                "account_id": account_id,
                "transaction_id": transaction.id,
                "incident_id": incident_id,
                "origin_event_id": origin_event_id,
                "destination_event_id": destination_event_id,
                "origin_event_type": origin_event_type,
                "destination_event_type": destination_event_type,
                "latitude": latitude,
                "longitude": longitude,
                "event_at": event_at or transaction.created_at,
                "metadata": {"synthetic": True, **metadata},
            }
        )
        return event_id

    for transaction in transactions:
        digest = _stable_bytes(transaction.id)
        incident = incident_by_transaction.get(transaction.id)
        incident_id = incident.id if incident else None
        anchor_index = digest[0] % len(CITIES)
        is_transfer = transaction.transaction_type == "TRANSFER"
        actor_account_id = transaction.sender_account_id if is_transfer else transaction.receiver_account_id
        login_index = (anchor_index + (3 if digest[1] % 5 == 0 else 0)) % len(CITIES)
        login_name, login_lat, login_lon = _city(login_index)
        login_scenario = "simulated_login_origin_mismatch" if is_transfer and login_index != anchor_index else "synthetic_session_context"
        add(
            transaction,
            "login",
            "LOGIN_LOCATION",
            account_id=actor_account_id,
            latitude=login_lat,
            longitude=login_lon,
            event_at=transaction.created_at - timedelta(minutes=4),
            metadata={"city": login_name, "label": "Synthetic login context", "scenario": login_scenario},
            incident_id=incident_id,
        )

        if not is_transfer:
            destination_name, destination_lat, destination_lon = _city((anchor_index + 1) % len(CITIES))
            add(
                transaction,
                "beneficiary",
                "BENEFICIARY_LOCATION",
                account_id=transaction.receiver_account_id,
                latitude=destination_lat,
                longitude=destination_lon,
                metadata={"city": destination_name, "label": "Synthetic receiver-associated location", "scenario": "simulated_funding_destination"},
                incident_id=incident_id,
            )
            continue

        origin_name, origin_lat, origin_lon = _city(anchor_index)
        origin_scenario = "simulated_login_origin_mismatch" if login_index != anchor_index else "ordinary_simulated_transfer"
        origin_id = add(
            transaction,
            "origin",
            "TRANSACTION_ORIGIN",
            account_id=transaction.sender_account_id,
            latitude=origin_lat,
            longitude=origin_lon,
            metadata={"city": origin_name, "label": "Synthetic transaction origin", "scenario": origin_scenario},
            incident_id=incident_id,
        )
        shared_destination = digest[2] % 4 == 0
        destination_index = 0 if shared_destination else (anchor_index + 2 + digest[3] % (len(CITIES) - 1)) % len(CITIES)
        destination_name, destination_lat, destination_lon = _city(destination_index)
        destination_id = add(
            transaction,
            "beneficiary",
            "BENEFICIARY_LOCATION",
            account_id=transaction.receiver_account_id,
            latitude=destination_lat,
            longitude=destination_lon,
            metadata={
                "city": destination_name,
                "label": "Synthetic beneficiary-associated location",
                "scenario": "shared_simulated_destination" if shared_destination else "ordinary_simulated_destination",
            },
            incident_id=incident_id,
        )
        add(
            transaction,
            "route",
            "TRANSACTION_ROUTE",
            event_at=transaction.created_at,
            metadata={
                "label": "Synthetic transaction connection",
                "scenario": "simulated_login_origin_mismatch" if login_index != anchor_index else ("shared_simulated_destination" if shared_destination else "ordinary_simulated_transfer"),
            },
            incident_id=incident_id,
            origin_event_id=origin_id,
            destination_event_id=destination_id,
            origin_event_type="TRANSACTION_ORIGIN",
            destination_event_type="BENEFICIARY_LOCATION",
        )
    return rows


def run_backfill(dry_run: bool = False) -> dict[str, int]:
    with SessionLocal.begin() as db:
        transactions = db.scalars(
            select(Transaction)
            .where(Transaction.status == "COMPLETED")
            .order_by(Transaction.created_at, Transaction.id)
        ).all()
        transaction_ids = [row.id for row in transactions]
        incident_by_transaction: dict[uuid.UUID, SecurityIncident] = {}
        if transaction_ids:
            links = db.execute(
                select(RuleEvaluationRecord.transaction_id, SecurityIncident)
                .join(SecurityIncident, SecurityIncident.id == RuleEvaluationRecord.incident_id)
                .where(
                    RuleEvaluationRecord.transaction_id.in_(transaction_ids),
                    RuleEvaluationRecord.evaluation_outcome == "TRIGGERED",
                )
                .order_by(SecurityIncident.risk_score.desc(), SecurityIncident.last_activity_at.desc())
            ).all()
            for transaction_id, incident in links:
                incident_by_transaction.setdefault(transaction_id, incident)

        rows = build_event_rows(transactions, incident_by_transaction)
        existing_keys = set()
        if rows:
            keys = [row["deduplication_key"] for row in rows]
            existing_keys = set(db.scalars(
                select(GeospatialEvent.deduplication_key).where(GeospatialEvent.deduplication_key.in_(keys))
            ).all())
        missing = [row for row in rows if row["deduplication_key"] not in existing_keys]
        if dry_run or not missing:
            inserted = 0
        else:
            inserted = 0
            for start in range(0, len(missing), 500):
                result = db.execute(
                    insert(GeospatialEvent)
                    .values(missing[start : start + 500])
                    .on_conflict_do_nothing(index_elements=[GeospatialEvent.id])
                    .returning(GeospatialEvent.id)
                )
                inserted += len(result.scalars().all())
        return {
            "completed_transactions_checked": len(transactions),
            "events_planned": len(rows),
            "events_missing_before_insert": len(missing),
            "events_inserted": inserted,
            "events_already_present_or_conflicted": len(rows) - inserted,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report planned rows without inserting them.")
    args = parser.parse_args()
    try:
        summary = run_backfill(dry_run=args.dry_run)
        mode = "DRY RUN" if args.dry_run else "COMPLETE"
        for key, value in summary.items():
            print(f"{key.replace('_', ' ')}: {value}")
        print(f"Synthetic geospatial generation {mode}; no financial records were changed.")
        logger.info("Geospatial event generation %s", mode.lower())
        return 0
    except Exception as exc:  # sanitized: DB exception strings can include bound values
        logger.error("Geospatial event generation failed (%s); transaction rolled back.", type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

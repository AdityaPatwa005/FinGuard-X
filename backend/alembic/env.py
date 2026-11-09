from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
# Ensure the backend modules are importable when Alembic is run from another cwd.
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from database import DATABASE_URL, engine  # noqa: E402
import models 
import ledger_models # noqa: E402,F401 - imports all model declarations for metadata
import transaction_models # noqa: E402,F401 - registers transaction and ledger-entry tables
import outbox_models # noqa: E402,F401 - registers the transactional outbox table
import incident_models # noqa: E402,F401 - registers detections and incident tables
from models import Base  # noqa: E402


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Configure migrations using the URL without opening a DB connection."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Configure migrations using the shared SQLAlchemy engine connection."""
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            transaction_per_migration=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

"""Optional integration against a disposable CI database, never the user's production DB."""

import os

import pytest
from sqlalchemy import select
from sqlalchemy.engine import make_url

from alembic import command
from app.cli import migration_config
from app.config import Settings
from app.database.locking import execution_lock
from app.database.models import JobRecord
from app.database.repository import save_jobs
from app.database.session import create_database_engine, transaction
from app.processing.normalizer import normalize_arbeitnow
from tests.test_processing import posting


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_URL"), reason="Disposable PostgreSQL not configured"
)
def test_disposable_postgres_migrations_upsert_and_distributed_lock():
    url = os.environ["TEST_POSTGRES_URL"]
    assert make_url(url).database.endswith("_test"), "Integration DB must be explicitly disposable"
    settings = Settings(_env_file=None, database_url=url)
    command.upgrade(migration_config(settings), "head")
    command.check(migration_config(settings))
    engine = create_database_engine(settings)
    try:
        with execution_lock(engine):
            with pytest.raises(RuntimeError), execution_lock(engine):
                pass
        with transaction(engine) as session:
            save_jobs(session, [normalize_arbeitnow(posting(slug="postgres-test"))])
        with transaction(engine) as session:
            stats = save_jobs(session, [normalize_arbeitnow(posting(slug="postgres-test"))])
            assert stats.updated == 1
            assert session.scalar(select(JobRecord).where(JobRecord.external_id == "postgres-test"))
    finally:
        engine.dispose()

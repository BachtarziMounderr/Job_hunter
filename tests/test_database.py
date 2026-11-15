from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.cli import migration_config
from app.database.models import JobRecord, JobSource, Notification, SearchProfile
from app.database.repository import list_jobs, save_jobs, save_profile
from app.database.session import transaction
from app.processing.normalizer import normalize_arbeitnow
from app.schemas.profile import load_profile
from tests.test_processing import posting


def test_migrations_have_no_drift_and_can_roundtrip(db):
    engine, settings = db
    command.check(migration_config(settings))
    tables = set(inspect(engine).get_table_names())
    assert {
        "jobs",
        "companies",
        "job_sources",
        "search_profiles",
        "job_skills",
        "job_matches",
        "notifications",
    } <= tables
    command.downgrade(migration_config(settings), "base")
    assert "jobs" not in inspect(engine).get_table_names()
    command.upgrade(migration_config(settings), "head")
    assert "jobs" in inspect(engine).get_table_names()


def test_initial_migration_compiles_for_postgresql_without_connecting():
    from io import StringIO

    from app.config import Settings

    settings = Settings(_env_file=None, database_url="postgresql+psycopg://")
    output = StringIO()
    config = migration_config(settings)
    config.output_buffer = output
    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()
    assert "CREATE TABLE jobs" in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql
    assert "uq_jobs_source_external" in sql
    assert "CREATE TABLE notifications" in sql


def test_upsert_preserves_first_seen_and_advances_last_seen(db):
    engine, _ = db
    first_seen = datetime(2026, 1, 1, tzinfo=UTC)
    first = normalize_arbeitnow(posting(), seen_at=first_seen)
    next_seen = first_seen + timedelta(days=1)
    second = normalize_arbeitnow(posting(description="Updated"), seen_at=next_seen)
    with transaction(engine) as session:
        assert save_jobs(session, [first]).inserted == 1
    with transaction(engine) as session:
        assert save_jobs(session, [second]).updated == 1
    with transaction(engine) as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        row = session.scalar(select(JobRecord))
        assert row.first_seen_at.replace(tzinfo=UTC) == first_seen
        assert row.last_seen_at.replace(tzinfo=UTC) == next_seen
        assert row.description == "Updated"


def test_content_duplicates_preserve_provenance_and_recanonicalize_changes(db):
    engine, _ = db
    first = normalize_arbeitnow(posting())
    alias = normalize_arbeitnow(posting(slug="second-source-id"))
    with transaction(engine) as session:
        stats = save_jobs(session, [first, alias])
        assert stats.inserted == 2
        assert stats.duplicates == 1
        assert len(list_jobs(session)) == 1
    with transaction(engine) as session:
        save_jobs(session, [normalize_arbeitnow(posting(description="A changed vacancy"))])
        assert len(list_jobs(session)) == 2
        assert all(row.duplicate_of_id is None for row in session.scalars(select(JobRecord)))


def test_transaction_rolls_back_all_changes(db):
    engine, _ = db
    with pytest.raises(RuntimeError), transaction(engine) as session:
        save_jobs(session, [normalize_arbeitnow(posting())])
        raise RuntimeError("simulate a failure")
    with transaction(engine) as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 0
        assert session.scalar(select(func.count()).select_from(JobSource)) == 0


def test_unique_source_identity_is_enforced_by_database(db):
    engine, _ = db
    with transaction(engine) as session:
        save_jobs(session, [normalize_arbeitnow(posting())])
    with pytest.raises(IntegrityError), transaction(engine) as session:
        existing = session.scalar(select(JobRecord))
        values = {
            column.name: getattr(existing, column.name)
            for column in JobRecord.__table__.columns
            if column.name != "id"
        }
        session.add(JobRecord(**values))
        session.flush()


def test_profile_revision_and_notification_uniqueness(db):
    engine, settings = db
    profile = load_profile(settings.profile_path)
    with transaction(engine) as session:
        first_hash = save_profile(session, profile).content_hash
        profile.skills.append("New skill")
        assert save_profile(session, profile).content_hash != first_hash
        assert session.scalar(select(func.count()).select_from(SearchProfile)) == 1
        save_jobs(session, [normalize_arbeitnow(posting())])
        job_id = session.scalar(select(JobRecord.id))
        profile_id = session.scalar(select(SearchProfile.id))
        session.add(
            Notification(job_id=job_id, profile_id=profile_id, channel="telegram", status="pending")
        )
    with pytest.raises(IntegrityError), transaction(engine) as session:
        session.add(
            Notification(job_id=job_id, profile_id=profile_id, channel="telegram", status="pending")
        )

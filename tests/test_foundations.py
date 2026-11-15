from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.schemas.job import Job
from app.schemas.profile import load_profile


def test_default_configuration_and_profile(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    settings = Settings(_env_file=None)
    assert settings.database_url.get_secret_value() == "sqlite:///data/job_hunter.db"
    profile = load_profile(Path("profiles/default.json"))
    assert profile.residence_country == "DZ"
    assert "Python" in profile.skills
    assert profile.work_authorization_countries == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"arbeitnow_max_pages": 0},
        {"http_max_attempts": 0},
        {"database_url": "invalid"},
        {"database_url": "mysql://localhost/db"},
    ],
)
def test_invalid_configuration(overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)


def test_settings_redact_credentials():
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://user:secret@host/db")
    assert "secret" not in repr(settings)


def job_data():
    return dict(
        source_name="test",
        external_id="1",
        title="Python Developer",
        application_url="https://example.com/jobs/1",
        content_hash="a" * 64,
    )


def test_valid_job_preserves_unknown_fields():
    job = Job(**job_data())
    assert job.country is None
    assert job.remote_eligibility == "unknown"
    assert job.required_skills == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": " "},
        {"application_url": "javascript:alert(1)"},
        {"content_hash": "invalid"},
        {"published_at": "2026-01-01T00:00:00"},
        {"first_seen_at": datetime.now(UTC) + timedelta(days=1)},
    ],
)
def test_job_rejects_invalid_data(overrides):
    with pytest.raises(ValidationError):
        Job(**(job_data() | overrides))

import json
import logging
from pathlib import Path

import pytest

from app.config import Settings
from app.schemas.profile import load_profile
from scripts import scheduled_run


def test_cloud_settings_error_identifies_secret_without_disclosing_value(monkeypatch, caplog):
    def invalid_settings():
        return Settings(_env_file=None, database_url="private-invalid-connection")

    monkeypatch.setattr(scheduled_run, "Settings", invalid_settings)
    # Keep the schema available while substituting the settings factory.
    invalid_settings.model_fields = Settings.model_fields
    with caplog.at_level(logging.INFO):
        assert scheduled_run.run() == 1
    assert "DATABASE_URL" in caplog.text
    assert "postgresql+psycopg://" in caplog.text
    assert "private-invalid-connection" not in caplog.text


@pytest.mark.parametrize("profile_error", ["field", "unknown_field", "json", "array", "empty"])
def test_cloud_profiles_errors_are_actionable_and_private(monkeypatch, caplog, profile_error):
    profile = load_profile(Path("profiles/default.json")).model_dump()
    if profile_error == "field":
        profile["residence_country"] = "private-country-input"
    if profile_error == "unknown_field":
        profile["private-unknown-field"] = "private-field-value"
    payload = json.dumps([profile])
    if profile_error == "json":
        payload = '{"private-json-input":'
    elif profile_error == "array":
        payload = json.dumps(profile)
    elif profile_error == "empty":
        payload = "[]"
    settings = Settings(
        _env_file=None,
        pipeline_enabled=True,
        database_url="postgresql+psycopg://user:private-password@localhost/db",
        profiles_json=payload,
    )
    monkeypatch.setattr(scheduled_run, "Settings", lambda: settings)
    with caplog.at_level(logging.INFO):
        assert scheduled_run.run() == 1
    assert "PROFILES_JSON" in caplog.text
    if profile_error == "field":
        assert "residence_country" in caplog.text
    for private in ["private-", profile["name"], profile["resume_text"] or "never-in-logs"]:
        assert private not in caplog.text


@pytest.mark.parametrize("check_only", [False, True])
def test_cloud_valid_configuration_runs_migrations_then_pipeline(monkeypatch, caplog, check_only):
    settings = Settings(
        _env_file=None,
        pipeline_enabled=True,
        database_url="postgresql+psycopg://user:private-password@localhost/db",
        profiles_json=json.dumps([load_profile(Path("profiles/default.json")).model_dump()]),
        notifications_enabled=True,
        telegram_bot_token="private-token",
        telegram_chat_id="1234",
        llm_enabled=True,
        llm_provider="groq",
        groq_api_key="",
    )
    calls = []
    monkeypatch.setattr(scheduled_run, "Settings", lambda: settings)
    monkeypatch.setattr(scheduled_run, "main", lambda args: calls.append(args) or 0)
    with caplog.at_level(logging.INFO):
        assert scheduled_run.run(check_only=check_only) == 0
    assert calls == [["init-db"], ["doctor"] if check_only else ["run", "--notify"]]
    assert "GROQ_API_KEY is missing" in caplog.text
    assert "1 enabled profiles" in caplog.text
    assert "private-" not in caplog.text

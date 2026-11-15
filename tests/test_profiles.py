import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import ScoreWeights, Settings
from app.profiles import load_profiles, sanitize_resume
from app.schemas.profile import load_profile


def test_sanitize_resume_removes_header_and_contacts():
    text = sanitize_resume(
        "PRIVATE NAME\n+213 555 123 456\nProfile\nPython dev\n"
        "mail@example.com https://example.com\nfeature engineer-\ning"
    )
    assert "PRIVATE NAME" not in text
    assert "mail@example.com" not in text
    assert "https://" not in text
    assert "engineering" in text


def test_three_profiles_from_injected_json_are_distinct(tmp_path):
    base = load_profile(Path("profiles/default.json")).model_dump()
    raw = [base | {"name": label, "profile_id": label} for label in ["ai", "data", "web"]]
    settings = Settings(_env_file=None, profiles_json=json.dumps(raw))
    assert len(load_profiles(settings)) == 3
    with pytest.raises(ValueError):
        load_profiles(Settings(_env_file=None, profiles_json=json.dumps(raw + [raw[0]])))


def test_weights_cannot_silently_change_total_scale():
    with pytest.raises(ValidationError):
        ScoreWeights(semantic=0.9)
    assert sum(ScoreWeights().model_dump().values()) == pytest.approx(1)


def test_empty_secrets_are_optional():
    settings = Settings(_env_file=None, telegram_bot_token="", profiles_json="", qwen_api_key="")
    assert settings.telegram_bot_token is None
    assert settings.profiles_json is None

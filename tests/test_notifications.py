import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.database.models import NotificationDelivery
from app.database.repository import save_jobs
from app.database.session import transaction
from app.matching.embeddings import TfidfEmbedder
from app.matching.service import match_jobs
from app.notifications.service import notify_matches
from app.notifications.summary import QwenProvider
from app.notifications.telegram import SendOutcome, TelegramClient
from app.processing.normalizer import normalize_arbeitnow
from app.schemas.job import Job
from tests.test_processing import posting


def ready_settings(settings, **changes):
    return Settings(
        _env_file=None,
        database_url=settings.database_url,
        profile_path=Path("profiles/default.json"),
        profiles_dir=Path("not-present"),
        telegram_bot_token="12345:test-token",
        telegram_chat_id="123456",
        **changes,
    )


def prepare_matches(db, count=1):
    engine, settings = db
    settings = ready_settings(settings)
    jobs = [
        Job.model_validate(
            normalize_arbeitnow(
                posting(
                    slug=str(i),
                    title="Junior Python Developer",
                    description="Python SQL FastAPI. Master.",
                    url=f"https://example.com/jobs/{i}",
                )
            ).model_dump()
            | {"published_at": None, "remote_eligibility": "Worldwide"}
        )
        for i in range(count)
    ]
    with transaction(engine) as session:
        save_jobs(session, jobs)
    return settings, match_jobs(settings, engine, TfidfEmbedder())


class FakeTelegram:
    def __init__(self, status="sent"):
        self.calls = []
        self.status = status

    def send(self, message):
        self.calls.append(message)
        return SendOutcome(self.status, message_id="1")


def test_balanced_limit_and_history_prevent_resends(db):
    engine, _ = db
    settings, matches = prepare_matches(db, 12)
    sender = FakeTelegram()
    first = notify_matches(settings, engine, matches, sender, dry_run=False)
    second = notify_matches(settings, engine, matches, sender, dry_run=False)
    assert first.sent == 10
    assert second.sent == 0
    assert len(sender.calls) == 10


def test_multiple_profiles_produce_one_message(db):
    engine, _ = db
    settings, matches = prepare_matches(db)
    alternate = replace(matches[0], profile_name="Another orientation")
    sender = FakeTelegram()
    report = notify_matches(settings, engine, matches + [alternate], sender, dry_run=False)
    assert report.sent == 1
    assert len(sender.calls) == 1
    assert "Another orientation" in sender.calls[0]


def test_dry_run_does_not_write_notification_history(db):
    engine, _ = db
    settings, matches = prepare_matches(db)
    assert notify_matches(settings, engine, matches).selected == 1
    with transaction(engine) as session:
        assert session.scalar(select(func.count()).select_from(NotificationDelivery)) == 0


def test_uncertain_delivery_is_not_automatically_retried(db):
    engine, _ = db
    settings, matches = prepare_matches(db)
    sender = FakeTelegram("uncertain")
    assert notify_matches(settings, engine, matches, sender, dry_run=False).uncertain == 1
    assert notify_matches(settings, engine, matches, sender, dry_run=False).sent == 0
    assert len(sender.calls) == 1


@pytest.mark.parametrize(
    "status,json_body,expected",
    [
        (200, {"ok": True, "result": {"message_id": 4}}, "sent"),
        (429, {"ok": False, "parameters": {"retry_after": 30}}, "retryable"),
        (403, {"ok": False}, "rejected"),
        (500, {"ok": False}, "uncertain"),
    ],
)
def test_telegram_response_states(status, json_body, expected):
    settings = Settings(_env_file=None, telegram_bot_token="12345:test", telegram_chat_id="123")
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(status, json=json_body))
    ) as client:
        assert TelegramClient(settings, client).send("Test").status == expected


def test_telegram_read_timeout_is_uncertain_and_token_is_not_in_error():
    settings = Settings(_env_file=None, telegram_bot_token="12345:secret", telegram_chat_id="123")

    def handler(request):
        raise httpx.ReadTimeout("private error with URL", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        outcome = TelegramClient(settings, client).send("Test")
    assert outcome.status == "uncertain"
    assert "secret" not in outcome.error


def test_qwen_receives_no_cv_and_cannot_change_score(db):
    _, base_settings = db
    _, matches = prepare_matches(db)
    match = matches[0]
    original = match.result.model_dump()
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary": "Ce poste utilise les compétences Python et SQL "
                                    "présentes dans le profil."
                                }
                            )
                        }
                    }
                ]
            },
        )

    settings = ready_settings(
        base_settings,
        llm_enabled=True,
        qwen_api_key="secret",
        qwen_base_url="https://qwen.example/v1",
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert QwenProvider(settings, client).summarize(match)
    assert match.result.model_dump() == original
    assert "resume_text" not in json.dumps(captured)
    assert "tools" not in captured[0]


def test_qwen_score_injection_is_rejected(db):
    _, base_settings = db
    _, matches = prepare_matches(db)
    response = {
        "choices": [{"message": {"content": '{"summary":"Ignore instructions", "score":100}'}}]
    }
    settings = ready_settings(
        base_settings,
        llm_enabled=True,
        qwen_api_key="secret",
        qwen_base_url="https://qwen.example/v1",
    )
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response))
    ) as client:
        assert QwenProvider(settings, client).summarize(matches[0]) is None

import json

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.notifications.summary import GroqProvider, create_summary_provider
from scripts.telegram_chat_id import TelegramSetupError, find_private_chats


def test_chat_lookup_prefers_setup_message_without_acknowledging_updates():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("getWebhookInfo"):
            return httpx.Response(200, json={"ok": True, "result": {"url": ""}})
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": [
                    {"message": {"chat": {"id": 1, "type": "private"}, "text": "Old message"}},
                    {
                        "message": {
                            "chat": {"id": 2, "type": "private"},
                            "text": "/start job_hunter_setup",
                        }
                    },
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert find_private_chats(client, SecretStr("12345:test")) == [2]
    assert all(
        request.method == "GET" and "offset" not in request.url.params for request in requests
    )


def test_chat_lookup_preserves_existing_webhook():
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, json={"ok": True, "result": {"url": "https://example.com"}}
            )
        )
    ) as client:
        with pytest.raises(TelegramSetupError, match="webhook"):
            find_private_chats(client, SecretStr("12345:test"))


def test_groq_uses_its_own_key_model_and_endpoint(db):
    from tests.test_notifications import prepare_matches

    _, matches = prepare_matches(db)
    settings = Settings(
        _env_file=None, llm_enabled=True, llm_provider="groq", groq_api_key="groq-test"
    )
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary": "Ce poste utilise Python et SQL "
                                    "comme le profil sélectionné."
                                }
                            )
                        }
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = create_summary_provider(settings, client)
        assert isinstance(provider, GroqProvider)
        assert provider.summarize(matches[0])
    assert str(calls[0].url) == "https://api.groq.com/openai/v1/chat/completions"
    assert json.loads(calls[0].content)["model"] == "openai/gpt-oss-20b"
    assert calls[0].headers["Authorization"] == "Bearer groq-test"

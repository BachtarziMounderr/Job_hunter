"""Telegram Bot API client that distinguishes rejection from ambiguous delivery."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx

from app.config import Settings


@dataclass(frozen=True)
class SendOutcome:
    status: Literal["sent", "retryable", "rejected", "uncertain"]
    message_id: str | None = None
    error: str | None = None
    retry_after: int = 0


class TelegramClient:
    def __init__(self, settings: Settings, client: httpx.Client) -> None:
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            raise ValueError("Configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID first")
        self.settings = settings
        self.client = client

    def send(self, message: str) -> SendOutcome:
        """One HTTP attempt. Retrying an uncertain response can duplicate a message."""
        return self._request(
            "sendMessage",
            json={
                "chat_id": self.settings.telegram_chat_id.get_secret_value(),
                "text": message[:3900],
                "link_preview_options": {"is_disabled": True},
            },
        )

    def send_document(self, path: Path, caption: str, buttons: list[list[dict]]) -> SendOutcome:
        """Upload the entire report as one Telegram message, with direct job buttons."""
        import json

        data = {
            "chat_id": self.settings.telegram_chat_id.get_secret_value(),
            "caption": caption[:1000],
        }
        if buttons:
            data["reply_markup"] = json.dumps({"inline_keyboard": buttons})
        with path.open("rb") as document:
            return self._request(
                "sendDocument",
                data=data,
                files={"document": (path.name, document, "text/html")},
            )

    def _request(self, method: str, **kwargs) -> SendOutcome:
        token = self.settings.telegram_bot_token.get_secret_value()
        try:
            response = self.client.post(
                f"https://api.telegram.org/bot{token}/{method}",
                **kwargs,
                timeout=self.settings.http_timeout_seconds,
                follow_redirects=False,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            return SendOutcome("retryable", error="Telegram connection could not be established")
        except httpx.TransportError:
            return SendOutcome(
                "uncertain", error="Telegram response was lost; delivery is uncertain"
            )
        try:
            payload = response.json()
        except ValueError:
            return SendOutcome("uncertain", error="Telegram returned an unreadable response")
        if not isinstance(payload, dict):
            return SendOutcome("uncertain", error="Telegram returned an invalid response")
        if response.status_code == 200 and payload.get("ok") is True:
            result = payload.get("result")
            if isinstance(result, dict) and isinstance(result.get("message_id"), int):
                return SendOutcome("sent", message_id=str(result["message_id"]))
            return SendOutcome("uncertain", error="Telegram accepted without a message identifier")
        if response.status_code == 429 or payload.get("error_code") == 429:
            parameters = payload.get("parameters", {})
            retry_after = parameters.get("retry_after", 60) if isinstance(parameters, dict) else 60
            if not isinstance(retry_after, int) or retry_after < 0:
                retry_after = 60
            return SendOutcome(
                "retryable",
                error="Telegram rate limited the request",
                retry_after=min(retry_after, 86400),
            )
        if 400 <= response.status_code < 500 and payload.get("ok") is False:
            return SendOutcome(
                "rejected", error=f"Telegram rejected request (HTTP {response.status_code})"
            )
        return SendOutcome("uncertain", error="Telegram server response does not confirm delivery")

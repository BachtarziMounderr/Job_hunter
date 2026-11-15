"""Read recent private chat IDs without exposing the bot token or consuming updates."""

import argparse
import json
import logging
from pathlib import Path

import httpx
from pydantic import SecretStr, ValidationError

from app.config import Settings


class TelegramSetupError(RuntimeError):
    """Only safe, credential-free diagnostics may cross this boundary."""


def find_private_chats(client: httpx.Client, token: SecretStr) -> list[int]:
    """Do not delete webhooks, send messages, or confirm any update with an offset."""
    root = "https://api.telegram.org/bot" + token.get_secret_value()

    def read(method: str, params: dict | None = None):
        try:
            response = client.get(
                root + "/" + method, params=params, timeout=20, follow_redirects=False
            )
            if response.status_code != 200:
                raise TelegramSetupError(f"Telegram HTTP {response.status_code}. Vérifie le jeton.")
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("ok") is not True:
                raise TelegramSetupError("Telegram a refusé la lecture. Vérifie le jeton.")
            return payload.get("result")
        except (httpx.HTTPError, ValueError):
            raise TelegramSetupError("Réponse Telegram indisponible ou illisible.") from None

    webhook = read("getWebhookInfo")
    if not isinstance(webhook, dict):
        raise TelegramSetupError("Réponse Telegram inattendue.")
    if webhook.get("url"):
        raise TelegramSetupError(
            "Ce bot utilise un webhook existant. Lis chat.id dans ses mises à jour ; "
            "le script ne modifie pas ce webhook."
        )
    updates = read("getUpdates", {"timeout": 0, "limit": 100})
    if not isinstance(updates, list):
        raise TelegramSetupError("Liste des messages Telegram invalide.")
    private_messages = [item.get("message", {}) for item in updates if isinstance(item, dict)]
    private_messages = [
        message
        for message in private_messages
        if isinstance(message, dict)
        and isinstance(message.get("chat"), dict)
        and message["chat"].get("type") == "private"
    ]
    marked = [
        message
        for message in private_messages
        if str(message.get("text", "")).startswith("/start job_hunter_setup")
    ]
    return sorted(
        {
            message["chat"]["id"]
            for message in (marked or private_messages)
            if isinstance(message["chat"].get("id"), int)
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Trouver TELEGRAM_CHAT_ID sans afficher le jeton")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        settings = Settings(_env_file=args.env_file)
        if not settings.telegram_bot_token:
            raise TelegramSetupError(
                "Renseigne TELEGRAM_BOT_TOKEN dans .env, puis relance le script."
            )
        with httpx.Client() as client:
            ids = find_private_chats(client, settings.telegram_bot_token)
        if not ids:
            logging.error("Envoie /start job_hunter_setup à ton bot, puis relance le script.")
            return 1
        print(json.dumps({"private_chat_ids": ids}))
        if len(ids) == 1:
            print(f"TELEGRAM_CHAT_ID={ids[0]}")
        return 0
    except TelegramSetupError as exc:
        logging.error("%s", exc)
        return 1
    except ValidationError:
        logging.error("Configuration invalide. Vérifie .env ; aucune valeur privée n'est affichée.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

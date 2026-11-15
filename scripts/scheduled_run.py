"""Cloud entry point with persistent history, private profiles, and explicit configuration."""

import logging

from app.cli import main
from app.config import Settings
from app.profiles import load_profiles


def _run() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = Settings()
    if not settings.pipeline_enabled:
        logging.info(
            "Pipeline disabled. Complete secrets and profiles, then set PIPELINE_ENABLED=true."
        )
        return 0
    if not settings.database_url.get_secret_value().startswith("postgresql+psycopg://"):
        logging.error("Scheduled cloud runs require PostgreSQL for durable notification history.")
        return 1
    if not settings.profiles_json and not list(settings.profiles_dir.glob("*.json")):
        logging.error("Configure private profiles using PROFILES_JSON or PROFILES_DIR first.")
        return 1
    load_profiles(settings)
    if settings.notifications_enabled and not (
        settings.telegram_bot_token and settings.telegram_chat_id
    ):
        logging.error(
            "Set both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID before enabling notifications."
        )
        return 1
    code = main(["init-db"])
    if code:
        return code
    return main(["run", "--notify"] if settings.notifications_enabled else ["run"])


def run() -> int:
    """Do not expose configuration values or private profile input in failure traces."""
    try:
        return _run()
    except Exception as exc:
        logging.error(
            "Scheduled run failed (%s). Inspect configuration with doctor.", type(exc).__name__
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(run())

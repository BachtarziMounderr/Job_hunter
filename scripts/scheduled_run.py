"""Cloud entry point with persistent history, private profiles, and explicit configuration."""

import argparse
import json
import logging

from pydantic import ValidationError

from app.cli import main
from app.config import Settings
from app.profiles import load_profiles
from app.schemas.profile import CandidateProfile


def _validation_error(exc: ValidationError, *, profiles: bool = False) -> None:
    """Report known schema fields only; even unknown field names can contain private input."""
    allowed = CandidateProfile.model_fields if profiles else Settings.model_fields
    for error in exc.errors(include_input=False, include_context=False, include_url=False):
        root = error["loc"][0] if error["loc"] else None
        field = root if root in allowed else "<unknown field>"
        name = f"PROFILES_JSON.{field}" if profiles else field.upper()
        logging.error("Invalid configuration: %s (%s).", name, error["type"])
        if not profiles and root in {"database_url", "migration_database_url"}:
            logging.error(
                "Use a postgresql+psycopg:// URL. Paste only the URL into the GitHub secret, "
                "without NAME= or surrounding quotes."
            )


def _run(check_only: bool = False) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        settings = Settings()
    except ValidationError as exc:
        _validation_error(exc)
        return 1
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
    try:
        profiles = load_profiles(settings)
    except ValidationError as exc:
        _validation_error(exc, profiles=True)
        return 1
    except json.JSONDecodeError as exc:
        logging.error(
            "Invalid PROFILES_JSON: malformed JSON at line %s, column %s. "
            "Paste the full JSON array without PROFILES_JSON= or surrounding quotes.",
            exc.lineno,
            exc.colno,
        )
        return 1
    except ValueError:
        logging.error(
            "Invalid PROFILES_JSON: provide a JSON array with at least one enabled profile "
            "and unique profile identifiers and names."
        )
        return 1
    if settings.notifications_enabled and not (
        settings.telegram_bot_token and settings.telegram_chat_id
    ):
        logging.error(
            "Set both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID before enabling notifications."
        )
        return 1
    if settings.llm_enabled:
        key = settings.groq_api_key if settings.llm_provider == "groq" else settings.qwen_api_key
        if not key:
            logging.warning(
                "%s_API_KEY is missing: summaries will use the local fallback.",
                settings.llm_provider.upper(),
            )
    logging.info("Configuration validated: %s enabled profiles.", len(profiles))
    code = main(["init-db"])
    if code:
        return code
    if check_only:
        return main(["doctor"])
    return main(["run", "--notify"] if settings.notifications_enabled else ["run"])


def run(check_only: bool = False) -> int:
    """Do not expose configuration values or private profile input in failure traces."""
    try:
        return _run(check_only=check_only)
    except Exception as exc:
        logging.error(
            "Scheduled run failed (%s). Inspect configuration with doctor.", type(exc).__name__
        )
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run or validate the cloud pipeline")
    parser.add_argument(
        "--check-only", action="store_true", help="Migrate and diagnose; no search/send"
    )
    raise SystemExit(run(check_only=parser.parse_args().check_only))

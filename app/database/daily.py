"""Daily idempotence, protected by the existing execution lock and durable before sends."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.config import Settings
from app.database.models import DailySearchRun
from app.database.session import transaction


def claim_daily_run(settings: Settings, engine) -> str | None:
    key = "algeria:" + datetime.now(ZoneInfo(settings.notification_timezone)).date().isoformat()
    with transaction(engine) as session:
        row = session.get(DailySearchRun, key)
        if row and row.status in {"completed", "report_sending", "uncertain"}:
            return None
        if row is None:
            session.add(DailySearchRun(run_key=key, status="running"))
        else:
            row.status, row.started_at = "running", datetime.now(UTC)
    return key


def set_daily_status(engine, key: str, status: str, message_id=None) -> None:
    with transaction(engine) as session:
        row = session.get(DailySearchRun, key)
        row.status = status
        row.report_message_id = message_id
        if status in {"completed", "failed", "uncertain"}:
            row.finished_at = datetime.now(UTC)


def abandon_daily_run(engine, key: str) -> None:
    with transaction(engine) as session:
        row = session.get(DailySearchRun, key)
        if row and row.status in {"running", "report_sending"}:
            row.status = "uncertain" if row.status == "report_sending" else "failed"
            row.finished_at = datetime.now(UTC)

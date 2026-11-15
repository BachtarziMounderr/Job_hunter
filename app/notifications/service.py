"""Balanced delivery across profiles with durable reservations and a shared daily cap."""

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.database.models import Notification, NotificationDelivery
from app.database.session import transaction
from app.matching.service import RankedMatch
from app.notifications.summary import LLMProvider, format_message
from app.notifications.telegram import TelegramClient


def select_opportunities(matches: list[RankedMatch], settings: Settings) -> list[list[RankedMatch]]:
    groups: dict[int, list[RankedMatch]] = {}
    for match in sorted(matches, key=lambda item: (-item.result.total_score, -item.job_id)):
        if (
            match.result.eligible_for_notification
            and match.result.total_score >= settings.minimum_match_score
        ):
            groups.setdefault(match.job_id, []).append(match)
    return list(groups.values())


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _job_key(match: RankedMatch) -> str:
    # Stable through description/profile changes and most canonical-row changes.
    return hashlib.sha256(str(match.job.application_url).encode()).hexdigest()


@dataclass
class DeliveryReport:
    selected: int = 0
    sent: int = 0
    skipped: int = 0
    failed: int = 0
    uncertain: int = 0
    previews: list[str] = field(default_factory=list)


def notify_matches(
    settings: Settings,
    engine: Engine,
    matches: list[RankedMatch],
    telegram: TelegramClient | None = None,
    provider: LLMProvider | None = None,
    *,
    dry_run: bool = True,
) -> DeliveryReport:
    """Reserve before sending; never automatically resend 'sending' or uncertain deliveries.

    Telegram has no idempotency key. A lost response is quarantined rather than retried.
    This favors avoiding duplicates over guaranteed delivery. No exactly-once claim.
    """
    groups = select_opportunities(matches, settings)
    report = DeliveryReport()
    if dry_run:
        for group in groups[: settings.max_notifications_per_day]:
            report.previews.append(format_message(group))
        report.selected = len(report.previews)
        return report
    if telegram is None or not settings.telegram_chat_id:
        raise ValueError("Telegram is not configured")
    recipient = hashlib.sha256(settings.telegram_chat_id.get_secret_value().encode()).hexdigest()
    now = datetime.now(UTC)
    local_date = now.astimezone(ZoneInfo(settings.notification_timezone)).date()
    midnight = datetime.combine(local_date, time.min, ZoneInfo(settings.notification_timezone))
    lower, upper = midnight.astimezone(UTC), (midnight + timedelta(days=1)).astimezone(UTC)
    with transaction(engine) as session:
        used = (
            session.scalar(
                select(func.count())
                .select_from(NotificationDelivery)
                .where(
                    NotificationDelivery.recipient_hash == recipient,
                    NotificationDelivery.last_attempt_at >= lower,
                    NotificationDelivery.last_attempt_at < upper,
                )
            )
            or 0
        )
    budget = max(0, settings.max_notifications_per_day - used)
    for group in groups:
        if report.selected >= budget:
            break
        best = group[0]
        key = _job_key(best)
        try:
            with transaction(engine) as session:
                delivery = session.scalar(
                    select(NotificationDelivery)
                    .where(
                        NotificationDelivery.recipient_hash == recipient,
                        NotificationDelivery.job_key == key,
                    )
                    .with_for_update()
                )
                if delivery and (
                    delivery.status in {"sent", "sending", "uncertain", "pending"}
                    or delivery.attempts >= settings.notification_max_attempts
                    or (delivery.next_attempt_at and _utc(delivery.next_attempt_at) > now)
                ):
                    report.skipped += 1
                    continue
                if delivery is None:
                    delivery = NotificationDelivery(
                        recipient_hash=recipient,
                        job_key=key,
                        job_id=best.job_id,
                        match_ids=[item.match_id for item in group],
                        status="pending",
                        attempts=0,
                    )
                    session.add(delivery)
                    session.flush()
                # Persist 'sending' before touching the external API. An interrupted process
                # leaves a quarantined record instead of automatically duplicating the send.
                delivery.status = "sending"
                delivery.last_attempt_at = now
                delivery.attempts += 1
                delivery_id = delivery.id
        except IntegrityError:
            report.skipped += 1
            continue
        report.selected += 1
        summary = None
        if provider:
            try:
                summary = provider.summarize(best)
            except Exception:
                # Presentation cannot block delivery or influence the selected results.
                summary = None
        outcome = telegram.send(format_message(group, summary))
        with transaction(engine) as session:
            delivery = session.get(NotificationDelivery, delivery_id)
            delivery.last_error = outcome.error
            if outcome.status == "sent":
                delivery.status = "sent"
                delivery.sent_at = now
                delivery.telegram_message_id = outcome.message_id
                report.sent += 1
                for item in group:
                    history = session.scalar(
                        select(Notification).where(
                            Notification.job_id == item.job_id,
                            Notification.profile_id == item.profile_id,
                            Notification.channel == "telegram",
                        )
                    )
                    if history is None:
                        session.add(
                            Notification(
                                job_id=item.job_id,
                                profile_id=item.profile_id,
                                match_id=item.match_id,
                                channel="telegram",
                                status="sent",
                                attempts=1,
                                sent_at=now,
                            )
                        )
            elif outcome.status in {"retryable", "rejected"}:
                delivery.status = "failed"
                delivery.next_attempt_at = now + timedelta(seconds=max(60, outcome.retry_after))
                if outcome.status == "rejected":
                    delivery.attempts = settings.notification_max_attempts
                report.failed += 1
            else:
                delivery.status = "uncertain"
                report.uncertain += 1
    return report

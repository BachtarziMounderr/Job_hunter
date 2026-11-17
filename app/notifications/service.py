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
from app.matching.skills import fold_text
from app.notifications.summary import LLMProvider, format_message
from app.notifications.telegram import TelegramClient
from app.processing.locality import locality_key


def select_opportunities(matches: list[RankedMatch], settings: Settings) -> list[list[RankedMatch]]:
    groups: dict[str, list[RankedMatch]] = {}
    for match in sorted(matches, key=lambda item: (-item.result.total_score, -item.job_id)):
        if (
            match.result.eligible_for_notification
            and match.result.total_score >= settings.minimum_match_score
        ):
            key = _job_key(match, local_only=settings.search_scope == "algeria")
            group = groups.setdefault(key, [])
            if not any(item.profile_name == match.profile_name for item in group):
                group.append(match)
    return list(groups.values())


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _job_key(match: RankedMatch, category="recommended", local_only=False) -> str:
    # Stable through description/profile changes and most canonical-row changes.
    identity = str(match.job.application_url)
    if local_only and match.job.company:
        identity = "|".join(
            [
                fold_text(match.job.company),
                fold_text(match.job.title),
                locality_key(match.job.location),
            ]
        )
    if category == "review":
        identity = "review:" + identity
    return hashlib.sha256(identity.encode()).hexdigest()


def select_reviews(matches: list[RankedMatch], settings: Settings) -> list[list[RankedMatch]]:
    if settings.search_scope != "algeria":
        return []
    recommended = {
        _job_key(group[0], local_only=True) for group in select_opportunities(matches, settings)
    }
    groups = {}
    for match in sorted(matches, key=lambda m: -m.result.total_score):
        if (
            match.job.country != "DZ"
            or match.result.geographic_status != "eligible"
            or match.result.exclusion_codes
        ):
            continue
        if match.result.total_score < settings.review_minimum_score:
            continue
        key = _job_key(match, local_only=True)
        if key not in recommended:
            group = groups.setdefault(key, [])
            if not any(item.profile_name == match.profile_name for item in group):
                group.append(match)
    return list(groups.values())


def review_message(group: list[RankedMatch]) -> str:
    best = group[0]
    reasons = best.result.review_reasons or ["Score inférieur au seuil de recommandation"]
    return "\n".join(
        [
            "Job Hunter — À VÉRIFIER — Algérie",
            best.job.title[:250],
            best.job.company or "Entreprise non précisée",
            "Lieu : " + (best.job.location or "Algérie"),
            f"Profil : {best.profile_name} ; score indicatif {best.result.total_score:.1f}/100",
            "Compétences communes : "
            + (", ".join(best.result.matched_skills[:6]) or "à confirmer"),
            "À vérifier : " + "; ".join(reasons),
            "Cette piste nécessite une vérification avant candidature.",
            str(best.job.application_url),
        ]
    )[:3900]


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
    category: str = "recommended",
) -> DeliveryReport:
    """Reserve before sending; never automatically resend 'sending' or uncertain deliveries.

    Telegram has no idempotency key. A lost response is quarantined rather than retried.
    This favors avoiding duplicates over guaranteed delivery. No exactly-once claim.
    """
    groups = (
        select_reviews(matches, settings)
        if category == "review"
        else select_opportunities(matches, settings)
    )
    formatter = review_message if category == "review" else format_message
    report = DeliveryReport()
    per_run_limit = (
        min(settings.max_notifications_per_day, settings.max_review_notifications)
        if category == "review"
        else settings.max_notifications_per_day
    )
    if dry_run:
        for group in groups[:per_run_limit]:
            report.previews.append(formatter(group))
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
    budget = min(per_run_limit, max(0, settings.max_notifications_per_day - used))
    for group in groups:
        if report.selected >= budget:
            break
        best = group[0]
        key = _job_key(best, category, settings.search_scope == "algeria")
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
        if provider and category != "review":
            try:
                summary = provider.summarize(best)
            except Exception:
                # Presentation cannot block delivery or influence the selected results.
                summary = None
        outcome = telegram.send(
            review_message(group) if category == "review" else format_message(group, summary)
        )
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

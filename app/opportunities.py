"""Durable single-user inbox shared by the CLI, daily runner and dashboard API."""

from dataclasses import asdict
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, or_, select, update

from app.config import Settings
from app.database.models import (
    JobMatch,
    NotificationDelivery,
    Opportunity,
    SearchExecution,
    SearchProfile,
)
from app.database.session import transaction
from app.matching.service import RankedMatch, load_matching_jobs
from app.notifications.service import _job_key
from app.pipeline import PipelineReport
from app.results import ResultEntry, result_entries
from app.schemas.match import MatchResult


def entry_key(entry: ResultEntry, settings: Settings) -> str:
    return _job_key(entry.best, local_only=settings.search_scope == "algeria")


def bootstrap_inbox(settings: Settings, engine):
    """Import pre-dashboard scores once, acknowledging the old reports without resending."""
    with transaction(engine) as session:
        empty = session.scalar(select(Opportunity.id).limit(1)) is None
    if not empty:
        return
    matches = saved_rankings(settings, engine)
    sync_opportunities(settings, engine, matches, bootstrap=True)
    if matches:
        now = datetime.now(UTC)
        with transaction(engine) as session:
            session.add(
                SearchExecution(
                    id=str(uuid4()),
                    mode="bootstrap",
                    status="success",
                    started_at=now,
                    finished_at=now,
                    details={"note": "Import des scores enregistrés, sans nouvelle collecte."},
                )
            )


def snapshot(entry: ResultEntry) -> dict:
    match, job = entry.best, entry.best.job
    return {
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "source": job.source_name,
        "application_url": entry.url,
        "category": entry.category,
        "best_profile": match.profile_name,
        "score": match.result.total_score,
        "matched_skills": match.result.matched_skills,
        "missing_skills": match.result.missing_skills,
        "review_reasons": match.result.review_reasons,
        "published_at": job.published_at.isoformat() if job.published_at else None,
        "source_last_seen_at": job.last_seen_at.isoformat(),
        "profiles": [{"name": m.profile_name, **m.result.model_dump()} for m in entry.profiles],
    }


def sync_opportunities(
    settings: Settings, engine, matches: list[RankedMatch], *, bootstrap=False
) -> list[str]:
    entries = [e for e in result_entries(matches, settings) if e.category != "excluded" and e.url]
    keys = [entry_key(e, settings) for e in entries]
    new = []
    now = datetime.now(UTC)
    with transaction(engine) as session:
        compared_ids = {m.job_id for m in matches}
        if compared_ids:
            session.execute(
                update(Opportunity)
                .where(
                    Opportunity.job_id.in_(compared_ids),
                    Opportunity.identity_key.not_in(keys),
                )
                .values(is_current=False)
            )
        rows = list(
            session.scalars(
                select(Opportunity)
                .where(
                    or_(
                        Opportunity.identity_key.in_(keys),
                        Opportunity.snapshot["application_url"]
                        .as_string()
                        .in_([e.url for e in entries]),
                    )
                )
                .with_for_update()
            )
        )
        existing = {row.identity_key: row for row in rows}
        by_url = {row.snapshot.get("application_url"): row for row in rows}
        previous = set(
            session.scalars(
                select(NotificationDelivery.job_id).where(
                    NotificationDelivery.status.in_(["sent", "sending", "uncertain"]),
                    NotificationDelivery.job_id.in_([e.best.job_id for e in entries]),
                )
            )
        )
        for entry, key in zip(entries, keys, strict=True):
            row = existing.get(key) or by_url.get(entry.url)
            if row is None:
                announced = bootstrap or entry.best.job_id in previous
                row = Opportunity(
                    identity_key=key,
                    job_id=entry.best.job_id,
                    notification_status="sent" if announced else "pending",
                    notified_at=now if announced else None,
                    snapshot=snapshot(entry),
                )
                session.add(row)
                existing[key] = row
                by_url[entry.url] = row
                if not announced:
                    new.append(key)
            else:
                row.identity_key = key
                existing[key] = row
                row.job_id, row.snapshot, row.updated_at = entry.best.job_id, snapshot(entry), now
                row.is_current = True
                if row.notification_status == "pending" and entry.best.job_id in previous:
                    row.notification_status, row.notified_at = "sent", now
    return new


def pending_entries(settings: Settings, engine, matches: list[RankedMatch]) -> list[ResultEntry]:
    with transaction(engine) as session:
        keys = set(
            session.scalars(
                select(Opportunity.identity_key).where(
                    Opportunity.status == "available",
                    Opportunity.notification_status == "pending",
                    Opportunity.is_current.is_(True),
                )
            )
        )
    return [
        e
        for e in result_entries(matches, settings)
        if entry_key(e, settings) in keys and e.category != "excluded" and e.url
    ]


def reserve_announcements(settings: Settings, engine, entries: list[ResultEntry]) -> list[str]:
    keys = [entry_key(e, settings) for e in entries]
    if keys:
        with transaction(engine) as session:
            rows = list(
                session.scalars(
                    select(Opportunity)
                    .where(
                        Opportunity.identity_key.in_(keys),
                        Opportunity.notification_status == "pending",
                        Opportunity.status == "available",
                        Opportunity.is_current.is_(True),
                    )
                    .with_for_update()
                )
            )
            keys = [row.identity_key for row in rows]
            for row in rows:
                row.notification_status = "sending"
    return keys


def finish_announcements(engine, keys: list[str], outcome: str):
    if not keys:
        return
    state = (
        "sent"
        if outcome == "sent"
        else "pending"
        if outcome in {"rejected", "retryable"}
        else "uncertain"
    )
    with transaction(engine) as session:
        session.execute(
            update(Opportunity)
            .where(
                Opportunity.identity_key.in_(keys),
                Opportunity.notification_status == "sending",
            )
            .values(
                notification_status=state,
                notified_at=datetime.now(UTC) if state == "sent" else None,
            )
        )


def begin_search(engine, mode: str) -> str:
    key = str(uuid4())
    with transaction(engine) as session:
        session.add(SearchExecution(id=key, mode=mode, status="running"))
    return key


def complete_search(engine, key: str, collection: PipelineReport, comparisons: int, new_count: int):
    with transaction(engine) as session:
        row = session.get(SearchExecution, key)
        row.status = {0: "success", 1: "failure", 2: "partial"}[collection.exit_code]
        row.finished_at = datetime.now(UTC)
        row.details = {
            "collection": asdict(collection),
            "comparisons": comparisons,
            "new_count": new_count,
        }


def fail_unfinished_search(engine, key: str):
    with transaction(engine) as session:
        row = session.get(SearchExecution, key)
        if row and row.status == "running":
            row.status, row.finished_at = "failure", datetime.now(UTC)
            row.details = {
                "error": "Recherche interrompue ; consulter les journaux GitHub ou locaux."
            }


def saved_rankings(settings: Settings, engine) -> list[RankedMatch]:
    """Bootstrap from persisted scores without an LLM or an embedding model download."""
    jobs = dict(load_matching_jobs(engine, settings))
    if not jobs:
        return []
    latest = (
        select(
            JobMatch.id,
            func.row_number()
            .over(
                partition_by=(JobMatch.job_id, JobMatch.profile_id),
                order_by=(JobMatch.created_at.desc(), JobMatch.id.desc()),
            )
            .label("rn"),
        )
        .where(JobMatch.job_id.in_(jobs))
        .subquery()
    )
    with transaction(engine) as session:
        rows = session.execute(
            select(JobMatch, SearchProfile.name)
            .join(SearchProfile, JobMatch.profile_id == SearchProfile.id)
            .join(latest, JobMatch.id == latest.c.id)
            .where(
                latest.c.rn == 1,
                JobMatch.profile_content_hash == SearchProfile.content_hash,
            )
        )
        matches = []
        for record, name in rows:
            job = jobs[record.job_id]
            if record.job_content_hash != job.content_hash:
                continue
            fields = {k: v for k, v in record.details.items() if k in MatchResult.model_fields}
            matches.append(
                RankedMatch(
                    record.job_id,
                    record.profile_id,
                    record.id,
                    name,
                    job,
                    MatchResult.model_validate(fields),
                )
            )
    return matches

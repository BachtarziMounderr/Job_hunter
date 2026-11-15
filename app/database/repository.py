"""Persistence operations. The caller owns the transaction and serializes writers."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select, tuple_
from sqlalchemy.orm import Session

from app.database.models import Company, JobRecord, JobSkill, JobSource, SearchProfile
from app.processing.deduplicator import deduplicate
from app.schemas.job import Job, utc_now
from app.schemas.profile import CandidateProfile


@dataclass
class PersistenceStats:
    inserted: int = 0
    updated: int = 0
    duplicates: int = 0


def _aware(value: datetime) -> datetime:
    # SQLite drops timezone offsets; all application timestamps are persisted in UTC.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _get_source(session: Session, name: str) -> JobSource:
    source = session.scalar(select(JobSource).where(JobSource.name == name))
    if source is None:
        source = JobSource(
            name=name, base_url=("https://www.arbeitnow.com" if name == "arbeitnow" else None)
        )
        session.add(source)
        session.flush()
    return source


def save_profile(session: Session, profile: CandidateProfile) -> SearchProfile:
    """Persist the validated profile and a stable revision fingerprint."""
    data = profile.model_dump(mode="json")
    digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    record = session.scalar(select(SearchProfile).where(SearchProfile.name == profile.name))
    if record is None:
        record = SearchProfile(name=profile.name, data=data, content_hash=digest)
        session.add(record)
    elif record.content_hash != digest:
        record.data = data
        record.content_hash = digest
        record.updated_at = utc_now()
    session.flush()
    return record


def save_jobs(session: Session, jobs: list[Job]) -> PersistenceStats:
    """Upsert source identities and mark exact content duplicates without losing provenance.

    Every source identity has at most one row. Duplicate content across identities
    points to the oldest active row; callers list only canonical rows by default.
    Updated canonical jobs trigger regrouping for both their old and new content.
    """
    jobs = deduplicate(jobs)
    stats = PersistenceStats()
    if not jobs:
        return stats
    source_names = {job.source_name for job in jobs}
    sources = {
        item.name: item
        for item in session.scalars(
            select(JobSource).where(JobSource.name.in_(source_names)),
        )
    }
    for name in source_names - sources.keys():
        sources[name] = JobSource(
            name=name,
            base_url={
                "arbeitnow": "https://www.arbeitnow.com",
                "jobicy": "https://jobicy.com",
            }.get(name),
        )
        session.add(sources[name])
    company_names = {job.company.casefold(): job.company for job in jobs if job.company}
    companies = {
        item.normalized_name: item
        for item in session.scalars(
            select(Company).where(Company.normalized_name.in_(company_names)),
        )
    }
    for key in company_names.keys() - companies.keys():
        companies[key] = Company(name=company_names[key], normalized_name=key)
        session.add(companies[key])
    session.flush()
    identities = [(sources[job.source_name].id, job.external_id) for job in jobs]
    existing = {
        (item.source_id, item.external_id): item
        for item in session.scalars(
            select(JobRecord).where(
                tuple_(JobRecord.source_id, JobRecord.external_id).in_(identities)
            ),
        )
    }
    touched_hashes: set[str] = set()
    touched: list[tuple[JobRecord, Job]] = []
    for job in jobs:
        source = sources[job.source_name]
        record = existing.get((source.id, job.external_id))
        if record is None:
            record = JobRecord(
                source_id=source.id,
                external_id=job.external_id,
                first_seen_at=job.first_seen_at.astimezone(UTC),
            )
            session.add(record)
            stats.inserted += 1
        else:
            touched_hashes.add(record.content_hash)
            stats.updated += 1
        values = job.model_dump(
            exclude={
                "source_name",
                "external_id",
                "company",
                "required_skills",
                "first_seen_at",
            }
        )
        values["application_url"] = str(job.application_url)
        values["remote_type"] = job.remote_type.value
        values["status"] = job.status.value
        values["last_seen_at"] = max(
            _aware(record.last_seen_at) if record.last_seen_at else job.last_seen_at,
            job.last_seen_at,
        ).astimezone(UTC)
        if job.published_at:
            values["published_at"] = job.published_at.astimezone(UTC)
        for key, value in values.items():
            setattr(record, key, value)
        record.company_id = companies[job.company.casefold()].id if job.company else None
        touched_hashes.add(job.content_hash)
        touched.append((record, job))
    session.flush()
    touched_ids = [record.id for record, _ in touched]
    session.execute(delete(JobSkill).where(JobSkill.job_id.in_(touched_ids)))
    session.add_all(
        JobSkill(job_id=record.id, skill=skill)
        for record, job in touched
        for skill in sorted(set(job.required_skills))
    )
    groups: dict[str, list[JobRecord]] = {}
    for record in session.scalars(
        select(JobRecord)
        .where(
            JobRecord.content_hash.in_(touched_hashes),
        )
        .order_by(JobRecord.id)
    ):
        groups.setdefault(record.content_hash, []).append(record)
    for group in groups.values():
        active = [item for item in group if item.status == "active"]
        canonical = active[0] if active else group[0]
        for item in group:
            item.duplicate_of_id = canonical.id if item.id != canonical.id else None
    session.flush()
    stats.duplicates = sum(record.duplicate_of_id is not None for record, _ in touched)
    return stats


def mark_source_success(session: Session, name: str) -> None:
    """Record successful retrieval, without expiring jobs absent from a bounded feed."""
    _get_source(session, name).last_success_at = utc_now()


def list_jobs(session: Session, *, limit: int = 20) -> list[dict]:
    """Return active canonical postings for local inspection, newest seen first."""
    rows = session.execute(
        select(JobRecord, JobSource.name, Company.name)
        .join(
            JobSource,
            JobRecord.source_id == JobSource.id,
        )
        .outerjoin(Company, JobRecord.company_id == Company.id)
        .where(
            JobRecord.status == "active",
            JobRecord.duplicate_of_id.is_(None),
        )
        .order_by(JobRecord.first_seen_at.desc(), JobRecord.id.desc())
        .limit(limit)
    )
    return [
        {
            "id": job.id,
            "title": job.title,
            "company": company,
            "source": source,
            "location": job.location,
            "remote_type": job.remote_type,
            "remote_eligibility": job.remote_eligibility,
            "url": job.application_url,
            "attribution": "https://www.arbeitnow.com" if source == "arbeitnow" else source,
        }
        for job, source, company in rows
    ]

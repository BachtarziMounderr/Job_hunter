"""Match all configured profiles, persist immutable score snapshots, and rank jobs."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import Engine, func, or_, select

from app.config import Settings
from app.database.models import Company, JobMatch, JobRecord, JobSkill, JobSource
from app.database.repository import save_profile
from app.database.session import transaction
from app.matching.embeddings import Embedder, cosine_matrix, create_embedder
from app.matching.scoring import score_job
from app.matching.skills import extract_skills
from app.profiles import load_profiles
from app.schemas.job import Job
from app.schemas.match import MatchResult
from app.schemas.profile import CandidateProfile


def _utc(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def profile_text(profile: CandidateProfile) -> str:
    # No candidate name, email, phone or profile URL goes into the embedding text.
    return "\n".join(
        [
            "Target roles: " + "; ".join(profile.target_roles),
            "Skills: " + "; ".join(profile.skills),
            "Education: " + "; ".join(profile.education),
            profile.resume_text,
        ]
    )


def job_text(job: Job) -> str:
    return f"{job.title}\n{' '.join(job.source_tags)}\n{job.description[:8000]}"


def load_matching_jobs(engine: Engine, settings: Settings) -> list[tuple[int, Job]]:
    cutoff = datetime.now(UTC) - timedelta(days=settings.job_max_age_days)
    with transaction(engine) as session:
        rows = session.execute(
            select(JobRecord, JobSource.name, Company.name)
            .join(JobSource, JobRecord.source_id == JobSource.id)
            .outerjoin(Company, JobRecord.company_id == Company.id)
            .where(
                JobRecord.status == "active",
                JobRecord.duplicate_of_id.is_(None),
                or_(
                    JobRecord.published_at >= cutoff,
                    (JobRecord.published_at.is_(None) & (JobRecord.first_seen_at >= cutoff)),
                ),
            )
            .order_by(
                func.coalesce(JobRecord.published_at, JobRecord.first_seen_at).desc(),
                JobRecord.id.desc(),
            )
            .limit(settings.matching_max_jobs)
        )
        jobs = []
        for record, source, company in rows:
            skills = extract_skills(record.title + " " + record.description)
            fields = {
                column.name: getattr(record, column.name)
                for column in JobRecord.__table__.columns
                if column.name not in {"id", "source_id", "company_id", "duplicate_of_id"}
            }
            for key in ["published_at", "first_seen_at", "last_seen_at"]:
                fields[key] = _utc(fields[key])
            jobs.append(
                (
                    record.id,
                    Job.model_validate(
                        fields
                        | {
                            "source_name": source,
                            "company": company,
                            "required_skills": skills,
                        }
                    ),
                )
            )
        return jobs


@dataclass(frozen=True)
class RankedMatch:
    job_id: int
    profile_id: int
    match_id: int
    profile_name: str
    job: Job
    result: MatchResult


def match_jobs(
    settings: Settings, engine: Engine, embedder: Embedder | None = None
) -> list[RankedMatch]:
    """Vectorize locally, calculate Python scores, and preserve each scoring revision."""
    profiles = load_profiles(settings)
    jobs = load_matching_jobs(engine, settings)
    if not jobs:
        return []
    backend = embedder or create_embedder(settings)
    vectors = backend.encode(
        [profile_text(p) for p in profiles] + [job_text(job) for _, job in jobs]
    )
    similarities = cosine_matrix(vectors[: len(profiles)], vectors[len(profiles) :])
    rules_hash = hashlib.sha256(
        b"".join(
            (Path(__file__).parent / file).read_bytes()
            for file in ["scoring.py", "classifiers.py", "geography.py", "skills.py", "service.py"]
        )
    ).hexdigest()
    signature = json.dumps(
        {
            "algorithm": "matching-v2",
            "rules_hash": rules_hash,
            "embedding": backend.version,
            "weights": settings.score_weights.model_dump(),
        },
        sort_keys=True,
    )
    engine_version = "v2:" + hashlib.sha256(signature.encode()).hexdigest()
    results = []
    with transaction(engine) as session:
        records = [save_profile(session, profile) for profile in profiles]
        job_ids = [job_id for job_id, _ in jobs]
        profile_ids = [record.id for record in records]
        previous = {
            (item.job_id, item.profile_id, item.job_content_hash, item.profile_content_hash): item
            for item in session.scalars(
                select(JobMatch).where(
                    JobMatch.job_id.in_(job_ids),
                    JobMatch.profile_id.in_(profile_ids),
                    JobMatch.engine_version == engine_version,
                )
            )
        }
        existing_skills = set(
            session.execute(
                select(JobSkill.job_id, JobSkill.skill).where(
                    JobSkill.job_id.in_(job_ids),
                )
            ).all()
        )
        pending_results = []
        for index, (job_id, job) in enumerate(jobs):
            session.add_all(
                JobSkill(job_id=job_id, skill=skill)
                for skill in job.required_skills
                if (job_id, skill) not in existing_skills
            )
            for profile_index, (profile, record) in enumerate(zip(profiles, records, strict=True)):
                result = score_job(
                    job, profile, float(similarities[profile_index, index]), settings.score_weights
                )
                match = previous.get((job_id, record.id, job.content_hash, record.content_hash))
                if match is None:
                    match = JobMatch(
                        job_id=job_id,
                        profile_id=record.id,
                        job_content_hash=job.content_hash,
                        profile_content_hash=record.content_hash,
                        engine_version=engine_version,
                        total_score=result.total_score,
                        details=result.model_dump()
                        | {
                            "embedding_version": backend.version,
                            "weights": settings.score_weights.model_dump(),
                        },
                    )
                    session.add(match)
                pending_results.append((job_id, record.id, match, profile.name, job, result))
        session.flush()
        results = [
            RankedMatch(job_id, profile_id, match.id, name, job, result)
            for job_id, profile_id, match, name, job, result in pending_results
        ]
    return sorted(
        results, key=lambda match: (-match.result.total_score, -match.job_id, match.profile_id)
    )


def ranking_output(
    matches: list[RankedMatch], *, limit: int = 20, include_blocked: bool = False
) -> list[dict]:
    """Show one best profile per job; keep other matching profile scores visible."""
    groups: dict[int, list[RankedMatch]] = {}
    for match in matches:
        if include_blocked or match.result.eligible_for_notification:
            groups.setdefault(match.job_id, []).append(match)
    output = []
    for group in groups.values():
        best = group[0]
        output.append(
            {
                "job_id": best.job_id,
                "title": best.job.title,
                "company": best.job.company,
                "url": str(best.job.application_url),
                "source": best.job.source_name,
                "best_profile": best.profile_name,
                "match": best.result.model_dump(),
                "other_profiles": [
                    {"name": item.profile_name, "score": item.result.total_score}
                    for item in group[1:]
                ],
            }
        )
    return output[:limit]

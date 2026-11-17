"""Collection orchestration with one transaction per source and visible failures."""

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Engine, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.collectors.base import Collector
from app.config import Settings
from app.database.models import JobRecord, JobSource
from app.database.repository import mark_source_success, save_jobs, save_profile
from app.database.session import transaction
from app.matching.local_policy import local_role
from app.processing.locality import algeria_status
from app.profiles import load_profiles
from app.schemas.job import Job

logger = logging.getLogger(__name__)


@dataclass
class PipelineSource:
    collector: Collector
    normalize: Callable[[dict[str, Any]], Job]


@dataclass
class PipelineReport:
    sources_completed: int = 0
    sources_failed: int = 0
    records_received: int = 0
    invalid_records: int = 0
    inserted: int = 0
    updated: int = 0
    duplicates: int = 0
    limited_sources: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    out_of_scope_records: int = 0
    irrelevant_records: int = 0
    source_details: dict[str, dict] = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        if self.sources_failed or self.invalid_records:
            return 2 if self.sources_completed or self.inserted or self.updated else 1
        return 0


def run_pipeline(
    settings: Settings,
    engine: Engine,
    sources: Iterable[PipelineSource],
) -> PipelineReport:
    """Collect independently; never infer expiration from a partial source snapshot."""
    profiles = load_profiles(settings)
    report = PipelineReport()
    with transaction(engine) as session:
        for profile in profiles:
            save_profile(session, profile)
    for source in sources:
        name = source.collector.name
        if settings.search_scope == "algeria" and name in {"arbeitnow", "jobicy"}:
            raise ValueError("Legacy sources are excluded from the Algeria search")
        try:
            result = source.collector.collect()
        except Exception as exc:
            # Intentional connector isolation boundary; do not log payloads/credentials.
            logger.error("Connector %s raised %s", name, type(exc).__name__)
            report.sources_failed += 1
            report.errors.append(f"{name}: connector raised {type(exc).__name__}")
            report.source_details[name] = {
                "received": 0,
                "accepted": 0,
                "pages": 0,
                "error": "Connector failed",
            }
            continue
        report.records_received += len(result.records) + result.malformed_records
        report.invalid_records += result.malformed_records
        if result.truncated:
            report.limited_sources.append(name)
        jobs = []
        invalid_before = report.invalid_records
        for raw in result.records:
            try:
                job = source.normalize(raw)
                if settings.search_scope == "algeria":
                    if algeria_status(job) != "eligible":
                        report.out_of_scope_records += 1
                        continue
                    if not any(local_role(job, profile)[0] for profile in profiles):
                        report.irrelevant_records += 1
                        continue
                jobs.append(job)
            except (ValidationError, ValueError, TypeError):
                report.invalid_records += 1
                logger.warning("Skipping malformed %s posting", name)
        try:
            with transaction(engine) as session:
                stats = save_jobs(session, jobs)
                if result.error is None and result.pages_fetched:
                    mark_source_success(session, name)
                if (
                    name.startswith(("lever:", "greenhouse:", "ayrade:"))
                    and not result.error
                    and not result.truncated
                    and result.pages_fetched
                    and report.invalid_records == invalid_before
                    and not result.malformed_records
                ):
                    source_id = session.scalar(select(JobSource.id).where(JobSource.name == name))
                    if source_id is not None:
                        session.execute(
                            update(JobRecord)
                            .where(
                                JobRecord.source_id == source_id,
                                JobRecord.external_id.not_in([job.external_id for job in jobs]),
                            )
                            .values(status="expired")
                        )
        except SQLAlchemyError:
            logger.error("Transaction failed for source %s; rolled back", name)
            report.sources_failed += 1
            report.errors.append(f"{name}: database transaction failed")
            report.source_details[name] = {
                "received": len(result.records),
                "accepted": 0,
                "pages": result.pages_fetched,
                "error": "Database transaction failed",
            }
            continue
        report.inserted += stats.inserted
        report.updated += stats.updated
        report.duplicates += stats.duplicates
        if result.error:
            report.sources_failed += 1
            report.errors.append(f"{name}: {result.error}")
        else:
            report.sources_completed += 1
        report.source_details[name] = {
            "received": len(result.records),
            "accepted": len(jobs),
            "pages": result.pages_fetched,
            "error": result.error,
        }
    if not report.sources_completed and not report.sources_failed:
        report.sources_failed = 1
        report.errors.append("No source configured")
    return report

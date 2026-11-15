"""Collection orchestration with one transaction per source and visible failures."""

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.collectors.base import Collector
from app.config import Settings
from app.database.repository import mark_source_success, save_jobs, save_profile
from app.database.session import transaction
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
        try:
            result = source.collector.collect()
        except Exception as exc:
            # Intentional connector isolation boundary; do not log payloads/credentials.
            logger.error("Connector %s raised %s", name, type(exc).__name__)
            report.sources_failed += 1
            report.errors.append(f"{name}: connector raised {type(exc).__name__}")
            continue
        report.records_received += len(result.records) + result.malformed_records
        report.invalid_records += result.malformed_records
        if result.truncated:
            report.limited_sources.append(name)
        jobs = []
        for raw in result.records:
            try:
                jobs.append(source.normalize(raw))
            except (ValidationError, ValueError, TypeError):
                report.invalid_records += 1
                logger.warning("Skipping malformed %s posting", name)
        try:
            with transaction(engine) as session:
                stats = save_jobs(session, jobs)
                if result.error is None and result.pages_fetched:
                    mark_source_success(session, name)
        except SQLAlchemyError:
            logger.error("Transaction failed for source %s; rolled back", name)
            report.sources_failed += 1
            report.errors.append(f"{name}: database transaction failed")
            continue
        report.inserted += stats.inserted
        report.updated += stats.updated
        report.duplicates += stats.duplicates
        if result.error:
            report.sources_failed += 1
            report.errors.append(f"{name}: {result.error}")
        else:
            report.sources_completed += 1
    return report

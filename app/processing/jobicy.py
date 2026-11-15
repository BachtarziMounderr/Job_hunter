"""Normalize Jobicy's documented fields, preserving the canonical Jobicy URL."""

from datetime import datetime
from typing import Any

from app.processing.deduplicator import content_hash
from app.processing.normalizer import clean_text, normalize_arbeitnow
from app.schemas.job import Job


def normalize_jobicy(raw: dict[str, Any]) -> Job:
    external_id = raw.get("id")
    if isinstance(external_id, bool) or not isinstance(external_id, int) or external_id < 1:
        raise ValueError("Jobicy requires a positive integer job id")
    normalized = normalize_arbeitnow(
        {
            "slug": str(external_id),
            "title": raw.get("jobTitle"),
            "url": raw.get("url"),
            "company_name": raw.get("companyName"),
            "description": raw.get("jobDescription"),
            "location": raw.get("jobGeo"),
            "remote": True,
            "tags": raw.get("jobIndustry"),
            "job_types": raw.get("jobType"),
        }
    )
    published_at = None
    if isinstance(raw.get("pubDate"), str):
        try:
            date = datetime.fromisoformat(raw["pubDate"])
            published_at = date if date.tzinfo else None
        except ValueError:
            pass
    scope = clean_text(raw["jobGeo"]) if isinstance(raw.get("jobGeo"), str) else "unknown"
    level = clean_text(raw["jobLevel"]) if isinstance(raw.get("jobLevel"), str) else "unknown"
    data = normalized.model_dump() | {
        "source_name": "jobicy",
        "remote_eligibility": scope or "unknown",
        "experience_level": level or "unknown",
        "published_at": published_at,
    }
    # Eligibility and seniority affect matching, so include them in the revision hash.
    data["content_hash"] = content_hash(
        **{
            key: (str(value) if key == "application_url" else value)
            for key, value in data.items()
            if key
            not in {
                "source_name",
                "external_id",
                "content_hash",
                "first_seen_at",
                "last_seen_at",
                "published_at",
                "status",
            }
        }
    )
    return Job.model_validate(data)

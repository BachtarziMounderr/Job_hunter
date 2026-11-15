"""Normalize source facts without classifying skills or geographic eligibility."""

import logging
import re
import unicodedata
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.processing.deduplicator import content_hash
from app.schemas.job import Job, RemoteType, utc_now

logger = logging.getLogger(__name__)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in {"script", "style"}:
            self.hidden_depth += 1
        if not self.hidden_depth:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden_depth = max(0, self.hidden_depth - 1)
        self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)


def clean_text(value: str) -> str:
    """Strip markup and normalize Unicode/whitespace; output is plain text."""
    parser = _TextExtractor()
    parser.feed(value)
    parser.close()
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", "".join(parser.parts))).strip()


def _optional_text(value: Any) -> str | None:
    return (clean_text(value) or None) if isinstance(value, str) else None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned = [_optional_text(item) for item in value]
    return list(dict.fromkeys(item for item in cleaned if item))


class _ArbeitnowRequiredFields(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    slug: str = Field(min_length=1, max_length=512)
    title: str = Field(min_length=1, max_length=512)
    url: HttpUrl


def normalize_arbeitnow(raw: dict[str, Any], *, seen_at: datetime | None = None) -> Job:
    """Validate identity, clean optional fields, and retain only supported source facts."""
    required = _ArbeitnowRequiredFields.model_validate(raw)
    observed = seen_at or utc_now()
    title = clean_text(required.title)
    company = _optional_text(raw.get("company_name"))
    description = _optional_text(raw.get("description")) or ""
    location = _optional_text(raw.get("location"))
    remote = raw.get("remote")
    remote_type = RemoteType.REMOTE if remote is True else RemoteType.UNKNOWN
    published_at = None
    timestamp = raw.get("created_at")
    if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
        try:
            published_at = datetime.fromtimestamp(timestamp, UTC)
        except (ValueError, OverflowError, OSError):
            logger.warning("Invalid Arbeitnow publication timestamp; stored as unknown")
    tags = _string_list(raw.get("tags"))
    job_types = _string_list(raw.get("job_types"))
    fingerprint = content_hash(
        title=title,
        company=company,
        description=description,
        location=location,
        remote_type=remote_type.value,
        employment_type=job_types,
        source_tags=tags,
        application_url=str(required.url),
    )
    return Job(
        source_name="arbeitnow",
        external_id=required.slug,
        title=title,
        company=company,
        description=description,
        location=location,
        remote_type=remote_type,
        employment_type=job_types,
        source_tags=tags,
        published_at=published_at,
        application_url=required.url,
        first_seen_at=observed,
        last_seen_at=observed,
        content_hash=fingerprint,
    )

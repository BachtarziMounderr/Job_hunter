"""Normalize verified company feeds and personal alert snippets to the same job schema."""

import hashlib
import re
import unicodedata
from datetime import UTC, datetime
from html.parser import HTMLParser

from app.processing.deduplicator import content_hash
from app.processing.locality import location_country
from app.schemas.job import Job


class BlockText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "li", "div", "br", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "li", "div", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def clean_job_text(html: str) -> str:
    parser = BlockText()
    parser.feed(html)
    return "\n".join(
        line
        for raw in unicodedata.normalize("NFKC", "".join(parser.parts)).splitlines()
        if (line := re.sub(r"[ \t]+", " ", raw).strip())
    )


def normalize_career(raw: dict) -> Job:
    description = clean_job_text(raw.get("description", ""))
    location = raw.get("location") or None
    published = raw.get("published_at")
    if isinstance(published, (int, float)):
        published = datetime.fromtimestamp(published / 1000, UTC)
    elif isinstance(published, str):
        try:
            published = datetime.fromisoformat(published.replace("Z", "+00:00"))
            if published.tzinfo is None:
                published = None
        except ValueError:
            published = None
    data = {
        "source_name": raw["source_name"],
        "external_id": str(
            raw.get("external_id") or hashlib.sha256(raw["url"].encode()).hexdigest()
        ),
        "title": clean_job_text(raw["title"]),
        "company": raw.get("company"),
        "description": description,
        "description_complete": raw.get("description_complete", True),
        "location": location,
        "country": raw.get("country") or location_country(location),
        "remote_type": raw.get("remote_type", "unknown"),
        "remote_eligibility": "unknown",
        "employment_type": raw.get("employment_type", []),
        "source_tags": raw.get("source_tags", []),
        "published_at": published,
        "application_url": raw["url"],
    }
    data["content_hash"] = content_hash(
        **{k: v for k, v in data.items() if k not in {"source_name", "external_id", "published_at"}}
    )
    return Job.model_validate(data)

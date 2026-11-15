"""Conservative exact duplicate detection. No semantic or LLM heuristics."""

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.schemas.job import Job


def _canonical(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip().casefold()
    if isinstance(value, list):
        return sorted({_canonical(item) for item in value})
    return value


def content_hash(**fields: Any) -> str:
    """Hash stable content, excluding source IDs and observation timestamps.

    Application URL is included conservatively: distinct requisitions with identical
    boilerplate must not be merged. Cross-source URL variants may remain separate.
    """
    payload = {
        key: value.strip() if key == "application_url" else _canonical(value)
        for key, value in fields.items()
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def deduplicate(jobs: Iterable["Job"]) -> list["Job"]:
    """Keep the latest payload per source identity; persistence checks content hashes.

    Different source identities are retained here so the repository can preserve
    their provenance even when they refer to the same exact content.
    """
    unique: dict[tuple[str, str], Job] = {}
    for job in jobs:
        unique[(job.source_name, job.external_id)] = job
    return list(unique.values())

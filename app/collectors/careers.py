"""Bounded public company-board clients; no user cookies or arbitrary URL fetching."""

import json
import re
import time
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.collectors.base import CollectionResult
from app.collectors.public_http import PublicFeedError, get_public_json
from app.config import Settings
from app.processing.locality import location_country


class CareerBoard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["lever", "greenhouse", "ayrade"]
    board: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    company: str = Field(min_length=1, max_length=200)
    enabled: bool = True


def load_boards(path: Path) -> list[CareerBoard]:
    return [
        board
        for row in json.loads(path.read_text(encoding="utf-8"))
        if (board := CareerBoard.model_validate(row)).enabled
    ]


class CareerCollector:
    def __init__(self, settings: Settings, client: httpx.Client, board: CareerBoard):
        self.settings, self.client, self.board = settings, client, board
        self.name = f"{board.kind}:{board.board.lower()}"

    def collect(self) -> CollectionResult:
        if self.board.kind == "ayrade":
            from app.collectors.ayrade import AyradeCollector

            return AyradeCollector(self.settings, self.client).collect()
        result = CollectionResult()
        for page in range(self.settings.career_max_pages):
            if page:
                time.sleep(self.settings.request_interval_seconds)
            url = (
                f"https://api.lever.co/v0/postings/{self.board.board}"
                if self.board.kind == "lever"
                else f"https://boards-api.greenhouse.io/v1/boards/{self.board.board}/jobs"
            )
            params = (
                {"mode": "json", "limit": 100, "skip": page * 100}
                if self.board.kind == "lever"
                else {"content": "true"}
            )
            try:
                payload = get_public_json(self.client, url, params, self.settings)
                rows = payload if self.board.kind == "lever" else payload["jobs"]
                if not isinstance(rows, list):
                    raise ValueError("Expected jobs array")
            except PublicFeedError as exc:
                result.error = f"Company feed unavailable ({exc}); no expiration inferred"
                break
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                result.error = "Company feed unavailable or malformed; no expiration inferred"
                break
            result.pages_fetched += 1
            for row in rows:
                if not isinstance(row, dict):
                    result.malformed_records += 1
                    continue
                try:
                    item = self._lever(row) if self.board.kind == "lever" else self._greenhouse(row)
                    # Multi-location boards may list offices worldwide. Keep Algerian positions.
                    if item is not None:
                        result.records.append(item)
                except (KeyError, TypeError, ValueError, AttributeError):
                    result.malformed_records += 1
            if self.board.kind != "lever" or len(rows) < 100:
                break
            result.truncated = page + 1 == self.settings.career_max_pages
        return result

    def _lever(self, row):
        category = row.get("categories", {})
        locations = category.get("allLocations") or [category.get("location", "")]
        local = [loc for loc in locations if isinstance(loc, str) and location_country(loc) == "DZ"]
        if not local:
            return None
        url = row["hostedUrl"]
        if not re.fullmatch(r"https://jobs\.lever\.co/[A-Za-z0-9_-]+/[A-Za-z0-9-]+", url):
            raise ValueError("Unexpected company job URL")
        sections = "\n".join(
            f"<h3>{part.get('text', '')}</h3>{part.get('content', '')}"
            for part in row.get("lists", [])
        )
        return {
            "source_name": self.name,
            "external_id": row["id"],
            "title": row["text"],
            "company": self.board.company,
            "location": " / ".join(local),
            "country": "DZ",
            "description": row.get("description", "") + sections + row.get("additional", ""),
            "remote_type": row.get("workplaceType", "unknown"),
            "url": url,
            "employment_type": [category["commitment"]] if category.get("commitment") else [],
            "source_tags": [v for k in ["department", "team"] if (v := category.get(k))],
            "published_at": row.get("createdAt"),
        }

    def _greenhouse(self, row):
        location = row.get("location", {}).get("name", "")
        if location_country(location) != "DZ":
            return None
        url = row["absolute_url"]
        if not url.startswith(
            ("https://boards.greenhouse.io/", "https://job-boards.greenhouse.io/")
        ):
            raise ValueError("Unexpected board URL")
        return {
            "source_name": self.name,
            "external_id": row["id"],
            "title": row["title"],
            "company": self.board.company,
            "location": location,
            "country": "DZ",
            "description": row.get("content", ""),
            "url": url,
        }

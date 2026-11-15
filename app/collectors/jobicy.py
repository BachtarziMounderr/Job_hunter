"""Public Jobicy connector with a one-hour local synchronization cache."""

import json
import logging
import time
from dataclasses import asdict
from pathlib import Path

import httpx

from app.collectors.base import CollectionResult
from app.config import Settings

logger = logging.getLogger(__name__)
API_URL = "https://jobicy.com/api/jobs"


class JobicyCollector:
    name = "jobicy"

    def __init__(self, settings: Settings, client: httpx.Client, sleep=time.sleep) -> None:
        self.settings = settings
        self.client = client
        self.sleep = sleep

    def _request(self, params: dict) -> dict:
        for attempt in range(self.settings.http_max_attempts):
            try:
                response = self.client.get(
                    API_URL,
                    params=params,
                    follow_redirects=False,
                    timeout=self.settings.http_timeout_seconds,
                    headers={"User-Agent": "AIJobHunter/0.2", "Accept": "application/json"},
                )
            except httpx.TransportError:
                if attempt + 1 == self.settings.http_max_attempts:
                    raise ValueError("Jobicy network retries exhausted") from None
            else:
                if response.status_code == 200:
                    try:
                        data = response.json()
                    except ValueError:
                        raise ValueError("Jobicy returned invalid JSON") from None
                    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
                        raise ValueError("Jobicy envelope must contain a jobs list")
                    if data.get("success") is False:
                        raise ValueError("Jobicy returned an unsuccessful response")
                    if not isinstance(data.get("nextCursor"), (str, type(None))):
                        raise ValueError("Jobicy returned an invalid cursor")
                    return data
                if response.status_code not in {408, 429, 500, 502, 503, 504}:
                    raise ValueError(f"Jobicy HTTP {response.status_code}; not retried")
                # On a server-requested cooldown, end this pass instead of polling early.
                if response.status_code == 429 or response.headers.get("Retry-After"):
                    raise ValueError("Jobicy requested a cooldown; synchronization stopped")
                if attempt + 1 == self.settings.http_max_attempts:
                    raise ValueError("Jobicy HTTP retries exhausted")
            self.sleep(min(self.settings.http_retry_base_seconds * 2**attempt, 60))
        raise ValueError("No Jobicy request attempts")

    def collect(self) -> CollectionResult:
        cache: Path = self.settings.source_cache_dir / "jobicy.json"
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            if 0 <= time.time() - cached["saved_at"] < 3600:
                logger.info("Using Jobicy cache to respect the hourly polling policy")
                return CollectionResult(**cached["result"])
        except (OSError, ValueError, KeyError, TypeError):
            pass
        result = CollectionResult()
        params: dict = {"count": 100}
        seen_cursors = set()
        for page in range(self.settings.jobicy_max_pages):
            if page:
                self.sleep(max(1, self.settings.request_interval_seconds))
            try:
                data = self._request(params)
            except ValueError as exc:
                result.error = str(exc)
                break
            result.pages_fetched += 1
            for row in data["jobs"]:
                if isinstance(row, dict):
                    result.records.append(row)
                else:
                    result.malformed_records += 1
            cursor = data.get("nextCursor")
            if not cursor:
                break
            if cursor in seen_cursors:
                result.error = "Jobicy repeated a pagination cursor"
                break
            seen_cursors.add(cursor)
            params["cursor"] = cursor
            result.truncated = page + 1 == self.settings.jobicy_max_pages
        # Cache partial/failed passes as well, so a cron/manual rerun won't hammer the API.
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(
            json.dumps({"saved_at": time.time(), "result": asdict(result)}), encoding="utf-8"
        )
        return result

"""Bounded client for Arbeitnow's verified public JSON API."""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from app.collectors.base import CollectionResult
from app.config import Settings

logger = logging.getLogger(__name__)
API_URL = "https://www.arbeitnow.com/api/job-board-api"
RETRY_STATUSES = {408, 429, 500, 502, 503, 504}


class CollectorError(Exception):
    """Safe, credential-free connector diagnostic."""


class ArbeitnowCollector:
    name = "arbeitnow"

    def __init__(
        self,
        settings: Settings,
        client: httpx.Client,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.client = client
        self.sleep = sleep

    def _retry_delay(self, response: httpx.Response | None, attempt: int) -> float:
        delay = min(self.settings.http_retry_base_seconds * 2**attempt, 60)
        if response is None:
            return delay
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                requested = float(retry_after)
            except ValueError:
                try:
                    requested = (
                        parsedate_to_datetime(retry_after) - datetime.now(UTC)
                    ).total_seconds()
                except (ValueError, TypeError, OverflowError):
                    requested = delay
            if requested > 60:
                raise CollectorError("Server requested a longer cooldown; try again later")
            delay = max(delay, requested)
        return delay

    def _fetch_page(self, page: int) -> dict:
        for attempt in range(self.settings.http_max_attempts):
            response = None
            try:
                # Never follow a URL supplied by job data or pagination links.
                response = self.client.get(
                    API_URL,
                    params={"page": page},
                    timeout=self.settings.http_timeout_seconds,
                    follow_redirects=False,
                    headers={"User-Agent": "AIJobHunter/0.1", "Accept": "application/json"},
                )
            except httpx.TransportError:
                if attempt + 1 == self.settings.http_max_attempts:
                    raise CollectorError("Network request failed after bounded retries") from None
            else:
                if response.status_code == 200:
                    try:
                        payload = response.json()
                    except ValueError:
                        raise CollectorError("API returned invalid JSON") from None
                    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                        raise CollectorError("API response must contain a data list")
                    links = payload.get("links", {})
                    if not isinstance(links, dict) or not isinstance(
                        links.get("next"),
                        (str, type(None)),
                    ):
                        raise CollectorError("API returned malformed pagination metadata")
                    return payload
                if response.status_code not in RETRY_STATUSES:
                    raise CollectorError(f"API returned HTTP {response.status_code}; not retried")
                if attempt + 1 == self.settings.http_max_attempts:
                    raise CollectorError(
                        f"API returned HTTP {response.status_code}; retries exhausted"
                    )
            delay = self._retry_delay(response, attempt)
            logger.warning("Arbeitnow request retry %d in %.1fs", attempt + 1, delay)
            self.sleep(delay)
        raise CollectorError("No request attempts available")  # defensive

    def collect(self) -> CollectionResult:
        """Fetch a small page budget; keep successful earlier pages on failure."""
        result = CollectionResult()
        for page in range(1, self.settings.arbeitnow_max_pages + 1):
            if page > 1:
                self.sleep(self.settings.request_interval_seconds)
            try:
                payload = self._fetch_page(page)
            except CollectorError as exc:
                result.error = str(exc)
                logger.error("Arbeitnow collection failed: %s", exc)
                break
            result.pages_fetched += 1
            for record in payload["data"]:
                if isinstance(record, dict):
                    result.records.append(record)
                else:
                    result.malformed_records += 1
            has_next = bool(payload.get("links", {}).get("next"))
            result.truncated = has_next and page == self.settings.arbeitnow_max_pages
            if not has_next or not payload["data"]:
                break
        return result

"""Bounded retries for public GET feeds, with credential-free diagnostics."""

import logging
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

logger = logging.getLogger(__name__)
RETRY_STATUSES = {408, 429, 500, 502, 503, 504}


class PublicFeedError(ValueError):
    """Safe diagnostic generated here, never from a response body or request URL."""


def get_public_json(client, url, params, settings):
    for attempt in range(settings.http_max_attempts):
        response = None
        try:
            response = client.get(
                url,
                params=params,
                timeout=settings.http_timeout_seconds,
                follow_redirects=False,
                headers={"User-Agent": "AIJobHunter/0.3", "Accept": "application/json"},
            )
        except httpx.TransportError:
            reason = "network request failed"
        else:
            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError:
                    raise PublicFeedError("invalid JSON") from None
            reason = f"HTTP {response.status_code}"
            if response.status_code not in RETRY_STATUSES:
                raise PublicFeedError(reason + "; not retried")
        if attempt + 1 == settings.http_max_attempts:
            raise PublicFeedError(reason + "; retries exhausted")
        delay = min(settings.http_retry_base_seconds * 2**attempt, 60)
        if response is not None and (value := response.headers.get("Retry-After")):
            try:
                requested = float(value)
            except ValueError:
                try:
                    requested = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
                except (ValueError, TypeError, OverflowError):
                    requested = delay
            if requested > 60:
                raise PublicFeedError("server requested a longer cooldown")
            delay = max(delay, requested)
        logger.warning("Public feed: %s; retry %d in %.1fs", reason, attempt + 1, delay)
        time.sleep(delay)
    raise PublicFeedError("no request attempts configured")

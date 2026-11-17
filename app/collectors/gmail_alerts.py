"""Read only a dedicated Gmail label using an offline OAuth grant; never send email."""

import base64

import httpx
from pydantic import BaseModel, SecretStr

from app.collectors.base import CollectionResult
from app.config import Settings
from app.processing.alerts import parse_alert_email


class GmailCredentials(BaseModel):
    client_id: SecretStr
    client_secret: SecretStr
    refresh_token: SecretStr


class GmailAlertCollector:
    name = "gmail-alerts"

    def __init__(self, settings: Settings, client: httpx.Client):
        self.settings, self.client = settings, client

    def collect(self) -> CollectionResult:
        result = CollectionResult()
        if not self.settings.gmail_oauth_json:
            result.error = "Gmail OAuth not configured; run scripts/setup_gmail.py once"
            return result
        try:
            creds = GmailCredentials.model_validate_json(
                self.settings.gmail_oauth_json.get_secret_value()
            )
            response = self.client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": creds.client_id.get_secret_value(),
                    "client_secret": creds.client_secret.get_secret_value(),
                    "refresh_token": creds.refresh_token.get_secret_value(),
                    "grant_type": "refresh_token",
                },
                timeout=self.settings.http_timeout_seconds,
                follow_redirects=False,
            )
            response.raise_for_status()
            token = response.json()["access_token"]
            headers = {"Authorization": "Bearer " + token}
            base = "https://gmail.googleapis.com/gmail/v1/users/me"
            response = self.client.get(
                base + "/labels",
                headers=headers,
                timeout=self.settings.http_timeout_seconds,
                follow_redirects=False,
            )
            response.raise_for_status()
            label = next(
                (
                    x["id"]
                    for x in response.json().get("labels", [])
                    if x["name"] == self.settings.gmail_label
                ),
                None,
            )
            if not label:
                result.error = (
                    "Dedicated Gmail label missing; create JobHunter/Alerts and its sender filter"
                )
                return result
            remaining = self.settings.gmail_max_messages
            params = {
                "labelIds": label,
                "q": f"newer_than:{self.settings.gmail_lookback_days}d -in:spam -in:trash",
                "maxResults": min(50, remaining),
            }
            while remaining:
                response = self.client.get(
                    base + "/messages",
                    params=params,
                    headers=headers,
                    timeout=self.settings.http_timeout_seconds,
                    follow_redirects=False,
                )
                response.raise_for_status()
                payload = response.json()
                result.pages_fetched += 1
                for item in payload.get("messages", [])[:remaining]:
                    # IDs come exclusively from Gmail, and are passed as one path segment.
                    message_id = item["id"]
                    if not isinstance(message_id, str) or not message_id.isalnum():
                        raise ValueError("Unexpected Gmail message id")
                    response = self.client.get(
                        base + "/messages/" + message_id,
                        params={"format": "raw"},
                        headers=headers,
                        timeout=self.settings.http_timeout_seconds,
                        follow_redirects=False,
                    )
                    response.raise_for_status()
                    content = response.json()
                    if content.get("sizeEstimate", 0) > 2_000_000:
                        result.malformed_records += 1
                    else:
                        try:
                            raw = content["raw"]
                            decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
                            result.records.extend(parse_alert_email(decoded))
                        except (ValueError, LookupError):
                            result.malformed_records += 1
                    remaining -= 1
                page = payload.get("nextPageToken")
                if not page:
                    break
                if not remaining:
                    result.truncated = True
                    break
                params.update({"pageToken": page, "maxResults": min(50, remaining)})
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            result.error = (
                "Gmail alert retrieval failed; check OAuth/label "
                "and source diagnostics (credentials hidden)"
            )
        return result

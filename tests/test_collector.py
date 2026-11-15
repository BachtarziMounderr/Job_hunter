import httpx
import pytest

from app.collectors.arbeitnow import API_URL, ArbeitnowCollector
from app.config import Settings


def collect(handler, **overrides):
    sleeps = []
    settings = Settings(_env_file=None, **overrides)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = ArbeitnowCollector(settings, client, sleeps.append).collect()
    return result, sleeps


def test_pagination_is_bounded_and_does_not_follow_external_links():
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(
            200, json={"data": [{"slug": "1"}, 5], "links": {"next": "http://evil.test/private"}}
        )

    result, sleeps = collect(handler, arbeitnow_max_pages=2)
    assert len(calls) == 2
    assert all(str(url).startswith(API_URL) for url in calls)
    assert calls[1].params["page"] == "2"
    assert result.pages_fetched == 2
    assert result.malformed_records == 2
    assert result.truncated
    assert sleeps == [1]


def test_rate_limit_retries_then_succeeds():
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        if count == 1:
            return httpx.Response(429, headers={"Retry-After": "4"})
        return httpx.Response(200, json={"data": []})

    result, sleeps = collect(handler)
    assert result.error is None
    assert sleeps == [4]


@pytest.mark.parametrize("status", [401, 403, 404, 302])
def test_access_errors_and_redirects_are_not_retried(status):
    result, sleeps = collect(lambda request: httpx.Response(status))
    assert result.error
    assert sleeps == []


def test_network_errors_have_bounded_retries():
    def handler(request):
        raise httpx.ConnectError("private diagnostic", request=request)

    result, sleeps = collect(handler)
    assert result.error == "Network request failed after bounded retries"
    assert sleeps == [1, 2]


def test_retry_after_long_cooldown_is_not_ignored():
    result, sleeps = collect(lambda r: httpx.Response(429, headers={"Retry-After": "120"}))
    assert "cooldown" in result.error
    assert sleeps == []


@pytest.mark.parametrize("payload", [[], {}, {"data": {}}, {"data": [], "links": []}])
def test_invalid_envelopes_report_failure(payload):
    result, _ = collect(lambda request: httpx.Response(200, json=payload))
    assert result.error


def test_invalid_json_is_reported():
    result, _ = collect(lambda request: httpx.Response(200, text="not JSON"))
    assert result.error == "API returned invalid JSON"


def test_partial_failure_preserves_previous_page():
    def handler(request):
        if request.url.params["page"] == "1":
            return httpx.Response(200, json={"data": [{"slug": "one"}], "links": {"next": "page2"}})
        return httpx.Response(503)

    result, _ = collect(handler, arbeitnow_max_pages=2)
    assert len(result.records) == 1
    assert result.pages_fetched == 1
    assert result.error

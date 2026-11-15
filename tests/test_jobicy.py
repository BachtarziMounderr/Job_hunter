from datetime import UTC, datetime

import httpx

from app.collectors.jobicy import JobicyCollector
from app.config import Settings
from app.processing.jobicy import normalize_jobicy


def row(**changes):
    return {
        "id": 1,
        "jobTitle": "Junior Python Developer",
        "companyName": "Example",
        "url": "https://jobicy.com/jobs/1-example",
        "jobDescription": "<p>Python SQL</p>",
        "jobGeo": "Worldwide",
        "jobLevel": "Junior",
        "jobType": ["Full-Time"],
        "jobIndustry": ["Engineering"],
        "pubDate": datetime.now(UTC).isoformat(),
    } | changes


def test_normalizer_preserves_geo_scope_and_canonical_url():
    job = normalize_jobicy(row())
    assert job.source_name == "jobicy"
    assert job.remote_eligibility == "Worldwide"
    assert job.remote_type == "remote"
    assert job.published_at.tzinfo
    assert str(job.application_url) == "https://jobicy.com/jobs/1-example"
    assert normalize_jobicy(row(jobGeo="Europe")).content_hash != job.content_hash


def test_jobicy_cursor_and_hourly_cache(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        cursor = None if len(calls) > 1 else "opaque-cursor"
        return httpx.Response(200, json={"jobs": [row(id=len(calls))], "nextCursor": cursor})

    settings = Settings(_env_file=None, source_cache_dir=tmp_path)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = JobicyCollector(settings, client, lambda delay: None)
        result = collector.collect()
        cached = collector.collect()
    assert len(calls) == 2
    assert calls[1].url.params["cursor"] == "opaque-cursor"
    assert len(result.records) == len(cached.records) == 2

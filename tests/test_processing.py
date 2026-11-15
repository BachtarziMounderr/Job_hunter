from app.processing.deduplicator import deduplicate
from app.processing.normalizer import clean_text, normalize_arbeitnow


def posting(**changes):
    return {
        "slug": "python-developer-1",
        "title": " Python Developer ",
        "company_name": "Example",
        "description": "<p>Python &amp; SQL</p><p>Junior</p>",
        "location": "Remote, Germany",
        "remote": True,
        "url": "https://example.com/jobs/1",
        "tags": ["IT", "IT", None],
        "job_types": ["full_time"],
        "created_at": 1760000000,
    } | changes


def test_normalization_preserves_facts_and_unknowns():
    job = normalize_arbeitnow(posting())
    assert job.title == "Python Developer"
    assert job.description == "Python & SQL Junior"
    assert job.remote_type == "remote"
    assert job.remote_eligibility == "unknown"
    assert job.country is None
    assert job.required_skills == []
    assert job.source_tags == ["IT"]
    assert job.published_at.tzinfo is not None


def test_optional_malformed_fields_do_not_drop_job():
    job = normalize_arbeitnow(
        posting(
            company_name=None,
            description={},
            location=12,
            remote="true",
            tags="IT",
            job_types=None,
            created_at=10**50,
        )
    )
    assert job.company is None
    assert job.description == ""
    assert job.location is None
    assert job.remote_type == "unknown"
    assert job.published_at is None


def test_html_script_and_style_are_removed():
    assert clean_text("<p>A</p><script>bad()</script><style>.x {}</style><p>B</p>") == "A B"


def test_deduplication_and_stable_hash():
    first = normalize_arbeitnow(posting())
    second = normalize_arbeitnow(posting(title="Python    Developer"))
    assert first.content_hash == second.content_hash
    assert len(deduplicate([first, second])) == 1
    different = normalize_arbeitnow(posting(url="https://example.com/jobs/2", slug="2"))
    assert first.content_hash != different.content_hash
    assert len(deduplicate([first, different])) == 2


def test_material_changes_change_hash():
    original = normalize_arbeitnow(posting())
    for change in [{"location": "Algiers"}, {"remote": False}, {"description": "New role"}]:
        assert normalize_arbeitnow(posting(**change)).content_hash != original.content_hash


def test_url_path_case_remains_significant_for_duplicate_detection():
    first = normalize_arbeitnow(posting(url="https://example.com/jobs/ABC"))
    second = normalize_arbeitnow(posting(url="https://example.com/jobs/abc"))
    assert first.content_hash != second.content_hash

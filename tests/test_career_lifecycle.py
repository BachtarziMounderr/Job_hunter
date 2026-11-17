from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from app.collectors.ayrade import AyradeCollector, ayrade_record, recruitment_links
from app.collectors.base import CollectionResult
from app.config import Settings
from app.database.models import JobRecord
from app.database.session import transaction
from app.pipeline import PipelineSource, run_pipeline
from app.processing.careers import normalize_career
from tests.test_algeria_search import posting


def test_company_disappearance_expires_only_after_complete_successful_snapshot(db):
    engine, base = db
    settings = base.model_copy(update={"search_scope": "algeria"})
    result = CollectionResult(records=[posting()], pages_fetched=1)
    collector = SimpleNamespace(name="lever:example", collect=lambda: result)
    source = PipelineSource(collector, normalize_career)
    run_pipeline(settings, engine, [source])
    for error, truncated in [("temporary error", False), (None, True)]:
        result = CollectionResult(pages_fetched=1, error=error, truncated=truncated)
        run_pipeline(settings, engine, [source])
        with transaction(engine) as session:
            assert session.scalar(select(JobRecord)).status == "active"
    result = CollectionResult(pages_fetched=1)
    run_pipeline(settings, engine, [source])
    with transaction(engine) as session:
        assert session.scalar(select(JobRecord)).status == "expired"


def test_ayrade_parser_keeps_headquarters_evidence_and_ignores_spontaneous_application():
    html = """<div class="et_pb_row"><div><p>Intégrateur Odoo</p></div>
    <div><a href="https://www.ayrade.com/integrateur-odoo/">Postuler</a></div></div>
    <div class="et_pb_row"><p>Candidature</p>
    <a href="https://www.ayrade.com/candidature-spontanee/">Postuler</a></div>"""
    assert recruitment_links(html) == [
        ("https://www.ayrade.com/integrateur-odoo/", "Intégrateur Odoo")
    ]
    detail = """<h2>INTÉGRATEUR ODOO</h2><h3>Profil recherché</h3><p>Python SQL.</p>
    <p>Poste basé au siège d’AYRADE.</p><p>Nom</p><p>Nos partenaires</p>
    <footer>Mohammadia Mall, Alger – Algérie</footer>"""
    record = ayrade_record(detail, "https://www.ayrade.com/integrateur-odoo/", "Intégrateur Odoo")
    assert record["country"] == "DZ"
    assert "Mohammadia" not in record["description"]
    # An office footer alone does not prove the role is in that office.
    unknown = ayrade_record(
        detail.replace("Poste basé au siège d’AYRADE.", "Work location to discuss"),
        record["url"],
        record["title"],
    )
    assert unknown["country"] is None


def test_ayrade_respects_robots_and_does_not_follow_external_redirects():
    calls = []

    def blocked(request):
        calls.append(str(request.url))
        return httpx.Response(200, text="User-agent: *\nDisallow: /recrutement/")

    with httpx.Client(transport=httpx.MockTransport(blocked)) as client:
        result = AyradeCollector(Settings(_env_file=None), client).collect()
    assert result.error and len(calls) == 1


def test_alert_plan_is_utf8_and_within_linkedin_alert_budget(tmp_path):
    from app.alert_plan import alert_plan, write_alert_plan

    settings = Settings(_env_file=None, profiles_dir=tmp_path / "missing")
    plan = alert_plan(settings)
    assert 0 < len(plan) <= 20
    assert all("location=Algeria" in item["linkedin"] for item in plan)
    output = tmp_path / "private" / "alert-plan.html"
    write_alert_plan(settings, output)
    assert "Algérie" in output.read_text(encoding="utf-8")


def test_cross_source_locality_aliases_do_not_duplicate_review_candidates(db):
    from app.database.repository import save_jobs
    from app.matching.embeddings import TfidfEmbedder
    from app.matching.service import match_jobs
    from app.notifications.service import select_reviews

    engine, base = db
    settings = base.model_copy(update={"search_scope": "algeria", "review_minimum_score": 0})
    first = normalize_career(posting(description_complete=False))
    second = normalize_career(
        posting(
            source_name="alert:linkedin",
            external_id="two",
            location="Algiers, Algeria",
            url="https://www.linkedin.com/jobs/view/123",
            description_complete=False,
        )
    )
    with transaction(engine) as session:
        save_jobs(session, [first, second])
    matches = match_jobs(settings, engine, TfidfEmbedder())
    assert len(matches) == 2
    assert len(select_reviews(matches, settings)) == 1


def test_company_feed_retries_transient_network_failure(monkeypatch):
    from app.collectors.careers import CareerBoard, CareerCollector

    calls = []
    monkeypatch.setattr("app.collectors.public_http.time.sleep", lambda _: None)

    def serve(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadTimeout("private provider details", request=request)
        return httpx.Response(200, json=[])

    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        result = CareerCollector(
            Settings(_env_file=None),
            client,
            CareerBoard(kind="lever", board="Example", company="Example"),
        ).collect()
    assert len(calls) == 2 and result.error is None and result.pages_fetched == 1


def test_company_feed_does_not_retry_access_denial_or_long_cooldown(monkeypatch):
    from app.collectors.careers import CareerBoard, CareerCollector

    monkeypatch.setattr("app.collectors.public_http.time.sleep", lambda _: pytest.fail("No retry"))
    for status, headers, diagnostic in [
        (403, {}, "HTTP 403"),
        (429, {"Retry-After": "120"}, "cooldown"),
    ]:
        calls = []

        def serve(request, calls=calls, status=status, headers=headers):
            calls.append(request)
            return httpx.Response(status, headers=headers)

        with httpx.Client(transport=httpx.MockTransport(serve)) as client:
            result = CareerCollector(
                Settings(_env_file=None),
                client,
                CareerBoard(kind="lever", board="Example", company="Example"),
            ).collect()
        assert len(calls) == 1 and diagnostic in result.error

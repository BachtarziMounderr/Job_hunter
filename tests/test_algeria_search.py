import base64
import json
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from app.cli import configured_sources, main
from app.collectors.base import CollectionResult
from app.collectors.careers import CareerBoard, CareerCollector
from app.collectors.gmail_alerts import GmailAlertCollector
from app.config import ScoreWeights, Settings
from app.database.daily import abandon_daily_run, claim_daily_run, set_daily_status
from app.database.models import JobRecord
from app.database.repository import save_jobs
from app.database.session import transaction
from app.matching.embeddings import TfidfEmbedder
from app.matching.scoring import score_job
from app.matching.service import match_jobs
from app.notifications.service import notify_matches, select_opportunities, select_reviews
from app.notifications.telegram import SendOutcome, TelegramClient
from app.pipeline import PipelineSource
from app.processing.alerts import canonical_alert_url, parse_alert_email
from app.processing.careers import normalize_career
from app.processing.locality import location_country
from app.schemas.profile import load_profile


def posting(**changes):
    return {
        "source_name": "lever:example",
        "external_id": "one",
        "title": "Junior Python Developer",
        "company": "Example",
        "location": "Alger, Algérie",
        "url": "https://jobs.lever.co/example/one",
        "description": (
            "<h3>Requirements</h3><p>Python SQL FastAPI. Master. 2 years of experience.</p>"
        ),
        **changes,
    }


def candidate():
    return load_profile(Path("profiles/default.json")).model_copy(
        update={
            "target_roles": ["Python Developer"],
            "target_seniority": ["junior", "internship"],
            "freelance_experience_years": 2,
        }
    )


@pytest.mark.parametrize(
    "location,country",
    [
        ("Algiers, Algeria", "DZ"),
        ("Oran", "DZ"),
        ("Algeria (East)", "DZ"),
        ("الجزائر", "DZ"),
        ("Tunis, Tunisia", "TN"),
        ("Paris, France", "FR"),
        ("Worldwide", None),
    ],
)
def test_location_evidence(location, country):
    assert location_country(location) == country


def test_country_only_policy_does_not_accept_worldwide_remote():
    job = normalize_career(posting(location="Worldwide", remote_type="remote"))
    result = score_job(job, candidate(), 1, ScoreWeights(), local_only=True)
    assert not result.eligible_for_notification
    assert "geography" in result.exclusion_codes


def test_local_clear_requirements_are_recommended_and_optional_skills_do_not_count():
    job = normalize_career(
        posting(
            description=(
                "<h3>Requirements</h3><p>Python SQL FastAPI. Master. 2 years of experience.</p>"
                "<h3>Nice to have</h3><p>Kubernetes AWS. 8 years of experience.</p>"
            )
        )
    )
    result = score_job(job, candidate(), 0.8, ScoreWeights(), local_only=True)
    assert result.eligible_for_notification
    assert "Kubernetes" not in result.missing_skills
    assert result.experience_score == 100


def test_partial_alert_is_review_only_even_with_high_similarity():
    job = normalize_career(posting(description_complete=False))
    result = score_job(job, candidate(), 1, ScoreWeights(), local_only=True)
    assert not result.eligible_for_notification
    assert any("partielle" in reason for reason in result.review_reasons)


def test_french_range_uses_lower_requirement_and_flags_conflicting_senior_title():
    job = normalize_career(
        posting(
            title="Senior Python Developer",
            description="Requirements:\nPython SQL. Master.\n1 à 2 ans d’expérience",
        )
    )
    result = score_job(job, candidate(), 1, ScoreWeights(), local_only=True)
    assert "experience" not in result.exclusion_codes
    assert any("contradiction" in reason for reason in result.review_reasons)


def test_old_active_company_offer_is_reviewed_and_legacy_history_is_ignored(db):
    engine, base = db
    settings = base.model_copy(update={"search_scope": "algeria"})
    recent = normalize_career(
        posting(published_at=(datetime.now(UTC) - timedelta(days=100)).isoformat())
    )
    legacy = normalize_career(
        posting(source_name="arbeitnow", external_id="old", url="https://example.com/legacy")
    )
    foreign = normalize_career(
        posting(external_id="fr", location="Paris, France", url="https://example.com/fr")
    )
    with transaction(engine) as session:
        save_jobs(session, [recent, legacy, foreign])
    matches = match_jobs(settings, engine, TfidfEmbedder())
    assert len(matches) == 1
    assert matches[0].job.source_name == "lever:example"
    assert any("ancienne" in reason for reason in matches[0].result.review_reasons)
    with transaction(engine) as session:
        assert len(session.scalars(select(JobRecord)).all()) == 3


def test_live_legacy_connectors_cannot_be_selected():
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: pytest.fail("No request allowed"))
    ) as client:
        for name in ["arbeitnow", "jobicy"]:
            with pytest.raises(ValueError, match="disabled"):
                configured_sources(Settings(_env_file=None), client, SimpleNamespace(source=name))


def test_company_connector_selects_algerian_locations_only():
    rows = [
        {
            "id": "one",
            "text": "Python Developer",
            "hostedUrl": "https://jobs.lever.co/example/one",
            "categories": {
                "location": "Tunis, Tunisia",
                "allLocations": ["Tunis, Tunisia", "Algiers, Algeria"],
            },
            "workplaceType": "hybrid",
            "description": "Python",
            "lists": [],
        },
        {
            "id": "two",
            "text": "Engineer",
            "hostedUrl": "https://jobs.lever.co/example/two",
            "categories": {"location": "Paris, France"},
            "lists": [],
        },
    ]
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=rows))
    ) as client:
        result = CareerCollector(
            Settings(_env_file=None),
            client,
            CareerBoard(kind="lever", board="example", company="Example"),
        ).collect()
    assert len(result.records) == 1
    job = normalize_career(result.records[0])
    assert job.country == "DZ" and job.location == "Algiers, Algeria"


def alert_bytes(html, sender="jobalerts-noreply@linkedin.com"):
    msg = EmailMessage()
    msg["From"] = sender
    msg["Subject"] = "Job alert"
    msg.set_content("An HTML job alert")
    msg.add_alternative(html, subtype="html")
    return msg.as_bytes()


ALERT_HTML = """<html><body><table>
<tr><td><a href="https://www.linkedin.com/comm/jobs/view/123?trackingId=private">
Junior Python Developer</a><div>Example</div><div>Alger, Algérie</div></td></tr>
<tr><td><a href="https://www.linkedin.com/jobs/view/other-job-456">Python Developer Paris</a>
<div>Other</div><div>Paris, France</div></td></tr>
</table><footer>Votre recherche : Algérie</footer></body></html>"""


def test_alert_cards_are_isolated_and_tracking_is_not_followed():
    records = parse_alert_email(alert_bytes(ALERT_HTML))
    assert len(records) == 2
    assert records[0]["country"] == "DZ"
    assert records[1]["country"] == "FR"
    assert records[0]["url"] == "https://www.linkedin.com/jobs/view/123"
    assert records[0]["description_complete"] is False
    assert "Other" not in records[0]["description"]
    assert "trackingId" not in records[0]["url"]


def test_sender_and_link_hosts_are_exactly_validated():
    assert not parse_alert_email(alert_bytes(ALERT_HTML, sender="alert@linkedin.com.evil.test"))
    for url in [
        "http://www.linkedin.com/jobs/view/123",
        "https://linkedin.com.evil/jobs/view/123",
        "https://127.0.0.1/jobs/view/123",
        "https://www.linkedin.com@evil.test/jobs/view/123",
    ]:
        assert canonical_alert_url(url, "linkedin") is None


def test_gmail_reads_only_configured_label_and_never_modifies_mail():
    encoded = base64.urlsafe_b64encode(alert_bytes(ALERT_HTML)).decode().rstrip("=")
    calls = []

    def serve(request):
        calls.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "private-access"})
        if request.url.path.endswith("/labels"):
            return httpx.Response(
                200, json={"labels": [{"id": "Label_7", "name": "JobHunter/Alerts"}]}
            )
        if request.url.path.endswith("/messages"):
            assert request.url.params["labelIds"] == "Label_7"
            return httpx.Response(
                200, json={"messages": [{"id": "abc123"}], "nextPageToken": "next"}
            )
        return httpx.Response(200, json={"raw": encoded, "sizeEstimate": len(encoded)})

    settings = Settings(
        _env_file=None,
        gmail_enabled=True,
        gmail_max_messages=1,
        gmail_oauth_json=json.dumps(
            {
                "client_id": "private-client",
                "client_secret": "private-secret",
                "refresh_token": "private-refresh",
            }
        ),
    )
    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        result = GmailAlertCollector(settings, client).collect()
    assert len(result.records) == 2 and result.truncated
    assert all(r.method == "GET" or r.url.host == "oauth2.googleapis.com" for r in calls)


def test_gmail_failure_does_not_leak_credentials():
    settings = Settings(_env_file=None, gmail_oauth_json="private-malformed-value")
    with httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail("No network"))) as client:
        result = GmailAlertCollector(settings, client).collect()
    assert result.error and "private-malformed" not in result.error


def test_daily_claim_resumes_failures_but_not_confirmed_or_ambiguous_reports(db):
    engine, settings = db
    key = claim_daily_run(settings, engine)
    abandon_daily_run(engine, key)
    assert claim_daily_run(settings, engine) == key
    set_daily_status(engine, key, "report_sending")
    abandon_daily_run(engine, key)
    assert claim_daily_run(settings, engine) is None
    set_daily_status(engine, key, "completed", "1")
    assert claim_daily_run(settings, engine) is None


def test_daily_cli_only_collects_once_after_confirmed_report(db, monkeypatch, capsys):
    engine, base = db
    settings = base.model_copy(
        update={
            "search_scope": "algeria",
            "run_mode": "daily",
            "embedding_backend": "tfidf",
            "telegram_bot_token": __import__("pydantic").SecretStr("private-test"),
            "telegram_chat_id": __import__("pydantic").SecretStr("1234"),
        }
    )
    calls = []
    messages = []

    class Stub:
        name = "lever:example"

        def collect(self):
            calls.append(1)
            return CollectionResult(records=[posting()], pages_fetched=1)

    monkeypatch.setattr("app.cli.Settings", lambda **kwargs: settings)
    monkeypatch.setattr(
        "app.cli.configured_sources", lambda *args: [PipelineSource(Stub(), normalize_career)]
    )
    monkeypatch.setattr(
        TelegramClient,
        "send",
        lambda self, text: messages.append(text) or SendOutcome("sent", message_id="1"),
    )
    assert main(["run", "--notify"]) == 0
    sent = len(messages)
    capsys.readouterr()
    assert main(["run", "--notify"]) == 0
    assert len(calls) == 1 and len(messages) == sent
    assert "skipped" in json.loads(capsys.readouterr().out)


def test_local_review_delivery_is_deduplicated(db):
    engine, base = db
    from pydantic import SecretStr

    settings = base.model_copy(
        update={
            "search_scope": "algeria",
            "review_minimum_score": 0,
            "telegram_bot_token": SecretStr("private-test"),
            "telegram_chat_id": SecretStr("1234"),
        }
    )
    with transaction(engine) as session:
        save_jobs(session, [normalize_career(posting(description_complete=False))])
    matches = match_jobs(settings, engine, TfidfEmbedder())
    assert not select_opportunities(matches, settings)
    assert select_reviews(matches, settings)
    messages = []
    sender = SimpleNamespace(
        send=lambda text: messages.append(text) or SendOutcome("sent", message_id="1")
    )
    first = notify_matches(settings, engine, matches, sender, dry_run=False, category="review")
    second = notify_matches(settings, engine, matches, sender, dry_run=False, category="review")
    assert first.sent == 1 and second.sent == 0 and second.skipped == 1
    assert "À VÉRIFIER" in messages[0]


def test_review_limit_does_not_starve_new_lower_ranked_jobs(db):
    from pydantic import SecretStr

    engine, base = db
    settings = base.model_copy(
        update={
            "search_scope": "algeria",
            "review_minimum_score": 0,
            "max_review_notifications": 1,
            "telegram_bot_token": SecretStr("private-test"),
            "telegram_chat_id": SecretStr("1234"),
        }
    )
    with transaction(engine) as session:
        save_jobs(
            session,
            [
                normalize_career(posting(description_complete=False)),
                normalize_career(
                    posting(
                        external_id="second",
                        title="Junior Backend Engineer Python",
                        url="https://jobs.lever.co/example/second",
                        description_complete=False,
                    )
                ),
            ],
        )
    matches = match_jobs(settings, engine, TfidfEmbedder())
    assert len(select_reviews(matches, settings)) == 2
    messages = []
    sender = SimpleNamespace(
        send=lambda text: messages.append(text) or SendOutcome("sent", message_id="1")
    )
    for _ in range(2):
        result = notify_matches(settings, engine, matches, sender, dry_run=False, category="review")
        assert result.sent == 1
    assert len(set(messages)) == 2

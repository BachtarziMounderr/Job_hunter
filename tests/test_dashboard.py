from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.api import create_app
from app.database.models import JobRecord, Opportunity
from app.database.session import transaction
from app.opportunities import (
    begin_search,
    complete_search,
    finish_announcements,
    pending_entries,
    reserve_announcements,
    saved_rankings,
    sync_opportunities,
)
from app.pipeline import PipelineReport
from tests.test_results import saved_matches


def setup_inbox(db):
    engine, _ = db
    settings, matches = saved_matches(db)
    assert sync_opportunities(settings, engine, matches)
    return settings, matches


def test_one_identity_survives_repeated_searches_profiles_and_source_aliases(db):
    engine, _ = db
    settings, matches = setup_inbox(db)
    extra_profile = replace(matches[0], profile_name="Another profile")
    another_source = replace(
        matches[0],
        job=matches[0].job.model_copy(
            update={
                "source_name": "alert:linkedin",
                "application_url": "https://www.linkedin.com/jobs/view/123",
                "location": "Algiers, Algeria",
            }
        ),
    )
    assert sync_opportunities(settings, engine, [*matches, extra_profile, another_source]) == []
    with transaction(engine) as session:
        assert session.scalar(select(func.count()).select_from(Opportunity)) == 1
    entries = pending_entries(settings, engine, matches)
    keys = reserve_announcements(settings, engine, entries)
    finish_announcements(engine, keys, "sent")
    assert pending_entries(settings, engine, matches) == []
    assert sync_opportunities(settings, engine, matches) == []


def test_same_application_url_with_updated_title_is_not_a_new_suggestion(db):
    engine, _ = db
    settings, matches = setup_inbox(db)
    entries = pending_entries(settings, engine, matches)
    finish_announcements(engine, reserve_announcements(settings, engine, entries), "sent")
    renamed = [
        replace(m, job=m.job.model_copy(update={"title": "Python Software Engineer"}))
        for m in matches
    ]
    assert sync_opportunities(settings, engine, renamed) == []
    assert not pending_entries(settings, engine, renamed)
    with transaction(engine) as session:
        assert session.scalar(select(func.count()).select_from(Opportunity)) == 1


@pytest.mark.parametrize(
    "outcome,retry", [("sent", False), ("uncertain", False), ("retryable", True)]
)
def test_announcement_confirmation_prevents_repeated_daily_suggestions(db, outcome, retry):
    engine, _ = db
    settings, matches = setup_inbox(db)
    entries = pending_entries(settings, engine, matches)
    keys = reserve_announcements(settings, engine, entries)
    assert not pending_entries(settings, engine, matches)
    finish_announcements(engine, keys, outcome)
    assert bool(pending_entries(settings, engine, matches)) is retry


def test_bootstrap_imports_saved_scores_without_notifying_old_offers(db):
    engine, _ = db
    settings, matches = saved_matches(db)
    restored = saved_rankings(settings, engine)
    assert len(restored) == len(matches)
    assert sync_opportunities(settings, engine, restored, bootstrap=True) == []
    assert not pending_entries(settings, engine, restored)


def test_apply_is_idempotent_persistent_and_not_reset_by_next_search(db):
    engine, _ = db
    settings, matches = setup_inbox(db)
    with TestClient(create_app(settings, engine=engine, prepare=False)) as client:
        first = client.get("/api/dashboard").json()
        row = first["items"][0]
        headers = {"X-Job-Hunter-CSRF": first["csrf_token"]}
        response = client.post(
            f"/api/opportunities/{row['id']}/status", json={"status": "applied"}, headers=headers
        )
        assert response.status_code == 200
        timestamp = response.json()["applied_at"]
        assert response.json()["application_url"] == str(matches[0].job.application_url)
        assert (
            client.post(
                f"/api/opportunities/{row['id']}/status",
                json={"status": "applied"},
                headers=headers,
            ).json()["applied_at"]
            == timestamp
        )
        assert sync_opportunities(settings, engine, matches) == []
        data = client.get("/api/dashboard?status=applied").json()
        assert data["stats"]["available"] == 0 and data["stats"]["applied"] == 1
        assert data["items"][0]["id"] == row["id"]
        assert not pending_entries(settings, engine, matches)
        assert (
            client.post(
                f"/api/opportunities/{row['id']}/status",
                json={"status": "available"},
                headers=headers,
            ).status_code
            == 200
        )
    with TestClient(create_app(settings, engine=engine, prepare=False)) as client:
        assert client.get("/api/dashboard").json()["stats"]["available"] == 1


def test_closed_jobs_hidden_from_available_but_applications_are_kept(db):
    engine, _ = db
    settings, matches = setup_inbox(db)
    with transaction(engine) as session:
        session.execute(update(JobRecord).values(status="expired"))
    with TestClient(create_app(settings, engine=engine, prepare=False)) as client:
        data = client.get("/api/dashboard").json()
        assert not data["items"] and data["stats"]["available"] == 0
    with transaction(engine) as session:
        session.execute(update(Opportunity).values(status="applied"))
    with TestClient(create_app(settings, engine=engine, prepare=False)) as client:
        assert len(client.get("/api/dashboard?status=applied").json()["items"]) == 1


def test_dashboard_rejects_csrf_foreign_origins_invalid_status_and_hosts(db):
    engine, _ = db
    settings, _ = setup_inbox(db)
    with TestClient(create_app(settings, engine=engine, prepare=False)) as client:
        data = client.get("/api/dashboard").json()
        route = f"/api/opportunities/{data['items'][0]['id']}/status"
        assert client.post(route, json={"status": "applied"}).status_code == 403
        headers = {"X-Job-Hunter-CSRF": data["csrf_token"], "Origin": "https://foreign.example"}
        assert client.post(route, json={"status": "applied"}, headers=headers).status_code == 403
        headers.pop("Origin")
        assert client.post(route, json={"status": "unknown"}, headers=headers).status_code == 422
        assert (
            client.post(
                "/api/opportunities/99999/status", json={"status": "applied"}, headers=headers
            ).status_code
            == 404
        )
        assert client.get("/api/dashboard", headers={"Host": "foreign.example"}).status_code == 400


def test_dashboard_filters_paginates_and_exposes_no_profile_cv_or_secrets(db):
    engine, _ = db
    settings, matches = setup_inbox(db)
    run = begin_search(engine, "daily")
    complete_search(
        engine, run, PipelineReport(sources_completed=2, records_received=72), len(matches), 1
    )
    with TestClient(create_app(settings, engine=engine, prepare=False)) as client:
        assert client.get("/api/dashboard?q=does-not-exist").json()["total"] == 0
        response = client.get("/api/dashboard?q=Python&limit=1")
        assert response.status_code == 200 and response.json()["total"] == 1
        assert client.get("/api/dashboard?page=2&limit=1").json()["items"] == []
        assert client.get("/api/dashboard?limit=101").status_code == 422
        text = response.text
        assert "resume_text" not in text and "database_url" not in text
        assert response.json()["history"][0]["status"] == "success"
        assert response.json()["schedule"]["time"] == "12:00"


def test_a_new_blocking_rule_removes_pending_opportunity_from_announcements(db):
    engine, _ = db
    settings, matches = setup_inbox(db)
    blocked = [
        replace(
            m,
            result=m.result.model_copy(
                update={"exclusion_codes": ["experience"], "eligible_for_notification": False}
            ),
        )
        for m in matches
    ]
    sync_opportunities(settings, engine, blocked)
    assert not pending_entries(settings, engine, blocked)
    with transaction(engine) as session:
        assert session.scalar(select(Opportunity)).is_current is False

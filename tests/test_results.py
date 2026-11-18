import json
from dataclasses import replace

import httpx
import pytest
from pydantic import SecretStr

from app.cli import main
from app.database.repository import save_jobs
from app.database.session import transaction
from app.matching.embeddings import TfidfEmbedder
from app.matching.service import match_jobs
from app.notifications.telegram import SendOutcome, TelegramClient
from app.processing.careers import normalize_career
from app.results import digest_buttons, digest_caption, result_entries, write_results
from tests.test_algeria_search import posting


def saved_matches(db):
    engine, base = db
    settings = base.model_copy(update={"search_scope": "algeria", "embedding_backend": "tfidf"})
    with transaction(engine) as session:
        save_jobs(session, [normalize_career(posting(description_complete=False))])
    return settings, match_jobs(settings, engine, TfidfEmbedder())


def test_report_prefers_compatible_profile_over_higher_blocked_score(db):
    settings, matches = saved_matches(db)
    compatible = replace(
        matches[0],
        profile_name="Full Stack",
        result=matches[0].result.model_copy(
            update={
                "total_score": 75,
                "exclusion_codes": [],
                "review_reasons": ["Expérience à vérifier"],
            }
        ),
    )
    blocked = replace(
        compatible,
        profile_name="AI Engineer",
        result=compatible.result.model_copy(
            update={"total_score": 99, "exclusion_codes": ["role"]}
        ),
    )
    (entry,) = result_entries([blocked, compatible], settings)
    assert entry.category == "review" and entry.best.profile_name == "Full Stack"
    assert len(entry.profiles) == 2


def test_html_keeps_links_and_escapes_untrusted_fields_without_credentials(db, tmp_path):
    settings, matches = saved_matches(db)
    match = replace(
        matches[0],
        job=matches[0].job.model_copy(
            update={
                "title": '<script>alert("injection")</script>',
                "description": "PRIVATE-CV-LIKE-TEXT",
            }
        ),
    )
    settings = settings.model_copy(update={"telegram_bot_token": SecretStr("PRIVATE-BOT-TOKEN")})
    path = tmp_path / "results.html"
    entries = write_results(settings, [match], path)
    html = path.read_text(encoding="utf-8")
    assert "&lt;script&gt;alert(&quot;injection&quot;)&lt;/script&gt;" in html
    assert '<script>alert("injection")</script>' not in html
    assert "PRIVATE-BOT-TOKEN" not in html and "PRIVATE-CV-LIKE-TEXT" not in html
    assert str(match.job.application_url) in html
    assert "<!--JOBS-->" not in html
    assert len(digest_caption(settings, entries)) <= 1024


@pytest.mark.parametrize("outcome,code", [("sent", 0), ("uncertain", 2), ("rejected", 2)])
def test_run_sends_one_document_with_all_results_and_no_individual_messages(
    db, tmp_path, monkeypatch, capsys, outcome, code
):
    settings, _ = saved_matches(db)
    settings = settings.model_copy(
        update={
            "telegram_bot_token": SecretStr("private-test"),
            "telegram_chat_id": SecretStr("123"),
            "profile_path": settings.profile_path.resolve(),
        }
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("app.cli.Settings", lambda **kwargs: settings)
    monkeypatch.setattr("app.cli.configured_sources", lambda *args: [])
    # No collection is required for a portable report of saved opportunities.
    messages = []

    def send_document(self, path, caption, buttons):
        messages.append((path.read_text(encoding="utf-8"), caption, buttons))
        return SendOutcome(outcome, message_id="7" if outcome == "sent" else None)

    monkeypatch.setattr(TelegramClient, "send_document", send_document)
    monkeypatch.setattr(TelegramClient, "send", lambda *args: pytest.fail("No individual send"))
    assert main(["report", "--send"]) == code
    assert len(messages) == 1 and "https://jobs.lever.co/example/one" in messages[0][0]
    assert "CV conseillé" in messages[0][0]
    assert json.loads(capsys.readouterr().out)["run_report"]["status"] == outcome


def test_document_upload_keeps_entire_file_and_inline_application_buttons(tmp_path):
    from app.config import Settings

    path = tmp_path / "results.html"
    path.write_text("<!doctype html>" + "x" * 12000 + "</html>", encoding="utf-8")
    calls = []

    def serve(request):
        calls.append(request)
        assert request.url.path.endswith("/sendDocument")
        assert b"x" * 12000 in request.content and b"</html>" in request.content
        assert b"https://example.com/job" in request.content
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    settings = Settings(_env_file=None, telegram_bot_token="private-test", telegram_chat_id="123")
    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        response = TelegramClient(settings, client).send_document(
            path, "Toutes les offres", [[{"text": "Postuler", "url": "https://example.com/job"}]]
        )
    assert response.status == "sent" and len(calls) == 1


def test_buttons_exclude_blocked_jobs_and_unsafe_urls(db):
    settings, matches = saved_matches(db)
    safe = replace(matches[0], result=matches[0].result.model_copy(update={"total_score": 80}))
    unsafe = replace(
        safe,
        job=safe.job.model_copy(
            update={"company": "Other", "application_url": "https://user:password@example.com/job"}
        ),
    )
    entries = result_entries([safe, unsafe], settings)
    assert len(digest_buttons(entries)) == 1

import json

import pytest

from app.cli import main
from app.notifications.telegram import SendOutcome, TelegramClient


@pytest.mark.parametrize("status,exit_code", [("sent", 0), ("uncertain", 2), ("rejected", 2)])
def test_complete_run_reports_zero_matches_and_checks_telegram_confirmation(
    tmp_path, monkeypatch, capsys, status, exit_code
):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'run.db'}")
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "")
    monkeypatch.setenv("PROFILES_JSON", "")
    monkeypatch.setenv("PROFILES_DIR", str(tmp_path / "no-private-profiles"))
    monkeypatch.setenv("EMBEDDING_BACKEND", "tfidf")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "private-test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456")
    monkeypatch.setenv("LLM_ENABLED", "false")
    payload = tmp_path / "empty-source.json"
    payload.write_text('{"data": []}', encoding="utf-8")
    messages = []

    def send(self, message):
        messages.append(message)
        return SendOutcome(status, message_id="1" if status == "sent" else None)

    monkeypatch.setattr(TelegramClient, "send", send)
    assert main(["--env-file", str(tmp_path / "absent.env"), "init-db"]) == 0
    assert main(
        ["--env-file", str(tmp_path / "absent.env"), "run", "--notify", "--input", str(payload)]
    ) == exit_code
    assert len(messages) == 1
    assert "Offres distinctes analysées : 0" in messages[0]
    assert "Aucune offre ne satisfait" in messages[0]
    assert "private-test-token" not in messages[0]
    output = json.loads(capsys.readouterr().out)
    assert output["run_report"]["status"] == status

import io
import json
from urllib.error import HTTPError

import pytest

from scripts.notify_workflow import notify


def environment(result):
    return {
        "TELEGRAM_BOT_TOKEN": "private-token",
        "TELEGRAM_CHAT_ID": "1234",
        "JOB_RESULTS_JSON": json.dumps(
            {"tests": {"result": result}, "container": {"result": "skipped"}}
        ),
        "WORKFLOW_NAME": "CI",
        "GITHUB_REPOSITORY": "owner/job-hunter",
        "GITHUB_RUN_ID": "42",
    }


@pytest.mark.parametrize("result,label", [("failure", "ÉCHEC"), ("success", "RÉUSSI")])
def test_workflow_result_is_sent_even_when_tests_fail(result, label):
    messages = []

    def send(request, **kwargs):
        messages.append(json.loads(request.data))
        return io.BytesIO(b'{"ok":true,"result":{"message_id":1}}')

    assert notify(environment(result), send) == 0
    assert label in messages[0]["text"]
    assert "https://github.com/owner/job-hunter/actions/runs/42" in messages[0]["text"]
    assert "private-token" not in messages[0]["text"]


def test_workflow_notifier_does_not_expose_bot_url_on_http_failure(capsys):
    def reject(request, **kwargs):
        raise HTTPError(request.full_url, 401, "private-token", {}, None)

    assert notify(environment("failure"), reject) == 1
    output = capsys.readouterr().out
    assert "HTTP 401" in output
    assert "private-token" not in output


def test_fork_without_secrets_does_not_attempt_to_send():
    def forbidden(*args, **kwargs):
        raise AssertionError("No request should be attempted")

    assert notify({}, forbidden) == 0

"""Send workflow outcomes without application dependencies or secret-bearing traces."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def notify(env, open_request=None) -> int:
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    chat = env.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        print("Telegram workflow notification skipped: secrets unavailable.")
        return 0
    try:
        jobs = json.loads(env.get("JOB_RESULTS_JSON", "{}"))
        results = {name: job.get("result", "unknown") for name, job in jobs.items()}
        state = (
            "ÉCHEC"
            if "failure" in results.values()
            else "ANNULÉ"
            if "cancelled" in results.values()
            else "IGNORÉ"
            if results and all(value == "skipped" for value in results.values())
            else "RÉUSSI"
        )
        if state in {"RÉUSSI", "IGNORÉ"} and env.get("NOTIFY_SUCCESS", "false").lower() != "true":
            print("Successful workflow notification muted; results are in the daily report.")
            return 0
        url = (
            f"{env.get('GITHUB_SERVER_URL', 'https://github.com')}/"
            f"{env.get('GITHUB_REPOSITORY', '')}/actions/runs/{env.get('GITHUB_RUN_ID', '')}"
        )
        lines = [
            f"Job Hunter — {env.get('WORKFLOW_NAME', 'GitHub Actions')} : {state}",
            f"Exécution #{env.get('GITHUB_RUN_NUMBER', '?')}",
            *[f"• {name}: {result}" for name, result in results.items()],
            "",
            "Détails et journaux : " + url,
        ]
        request = Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=json.dumps(
                {
                    "chat_id": chat,
                    "text": "\n".join(lines)[:3900],
                    "link_preview_options": {"is_disabled": True},
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        opener = open_request or build_opener(NoRedirect()).open
        with opener(request, timeout=25) as response:
            payload = json.load(response)
        if payload.get("ok") is True and isinstance(
            payload.get("result", {}).get("message_id"), int
        ):
            print("Telegram workflow notification confirmed.")
            return 0
        print("Telegram did not confirm workflow notification delivery; not retried.")
    except HTTPError as exc:
        print(f"Telegram workflow notification failed (HTTP {exc.code}); values hidden.")
    except (URLError, OSError, ValueError, TypeError, AttributeError):
        print("Telegram workflow notification unconfirmed; values hidden, not retried.")
    return 1


if __name__ == "__main__":
    raise SystemExit(notify(os.environ))

"""One-time desktop OAuth setup. Writes credentials locally, never prints tokens."""

import argparse
import base64
import hashlib
import json
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from dotenv import set_key

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


def authorize(client_path: Path, output: Path, open_browser: bool = True) -> None:
    if not output.resolve().is_relative_to(Path("private").resolve()):
        raise ValueError("OAuth output must stay in the gitignored private directory")
    document = json.loads(client_path.read_text(encoding="utf-8"))
    installed = document["installed"]
    client_id, client_secret = installed["client_id"], installed["client_secret"]
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    result = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            query = parse_qs(urlsplit(self.path).query)
            if urlsplit(self.path).path != "/callback" or query.get("state") != [state]:
                self.send_error(400, "Invalid OAuth callback")
                return
            if "code" in query:
                result["code"] = query["code"][0]
            else:
                result["error"] = True
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("Autorisation reçue. Tu peux fermer cet onglet.".encode())

    with HTTPServer(("127.0.0.1", 0), Callback) as server:
        redirect = f"http://127.0.0.1:{server.server_port}/callback"
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect,
                "response_type": "code",
                "scope": SCOPE,
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        print(
            "Read-only Gmail authorization. The scope covers the mailbox; "
            "Job Hunter reads only its configured label."
        )
        if open_browser:
            webbrowser.open(url)
        else:
            print("Open this authorization URL locally:", url)
        server.timeout = 1
        deadline = time.monotonic() + 300
        while not result and time.monotonic() < deadline:
            server.handle_request()
    if not result.get("code"):
        raise RuntimeError("Authorization not completed")
    with httpx.Client(timeout=30) as client:
        response = client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": result["code"],
                "code_verifier": verifier,
                "redirect_uri": redirect,
                "grant_type": "authorization_code",
            },
            follow_redirects=False,
        )
        response.raise_for_status()
        payload = response.json()
    credentials = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": payload["refresh_token"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(credentials), encoding="utf-8")
    output.chmod(0o600)
    set_key(".env", "GMAIL_OAUTH_JSON", json.dumps(credentials), quote_mode="always")
    set_key(".env", "GMAIL_ENABLED", "true", quote_mode="always")
    print("Private credentials saved to:", output)
    print("Store the whole file as GitHub secret GMAIL_OAUTH_JSON; set GMAIL_ENABLED=true.")
    print("Local .env updated automatically. Never post the credentials in chat.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("private/gmail-oauth.json"))
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        authorize(args.client, args.output, not args.no_browser)
    except Exception as exc:
        print("Gmail setup did not complete:", type(exc).__name__, "(credentials hidden)")
        raise SystemExit(1) from None

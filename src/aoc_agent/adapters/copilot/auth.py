import json
import time
from pathlib import Path

import httpx

COPILOT_CLIENT_ID = "Ov23li8tweQw6odWQebz"
GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"  # noqa: S105
TOKEN_PATH = Path.home() / ".aoc-agent" / "copilot_token.json"
HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}


def _request_device_code(client: httpx.Client) -> dict:
    resp = client.post(
        GITHUB_DEVICE_CODE_URL,
        json={"client_id": COPILOT_CLIENT_ID, "scope": "read:user"},
        headers=HEADERS,
    )
    resp.raise_for_status()
    return resp.json()


def _poll_for_token(client: httpx.Client, device_code: str, interval: int) -> str:
    while True:
        time.sleep(interval)
        resp = client.post(
            _ACCESS_TOKEN_URL,
            json={
                "client_id": COPILOT_CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            headers=HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()

        if "access_token" in data:
            return data["access_token"]

        error = data.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error in ("expired_token", "access_denied"):
            msg = f"GitHub OAuth failed: {error}"
            raise RuntimeError(msg)
        msg = f"Unexpected OAuth response: {data}"
        raise RuntimeError(msg)


def _save_token(token: str) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps({"oauth_token": token}))


def _load_token() -> str | None:
    if not TOKEN_PATH.exists():
        return None
    data = json.loads(TOKEN_PATH.read_text())
    return data.get("oauth_token")


def copilot_login() -> str:
    with httpx.Client() as client:
        device_data = _request_device_code(client)
        user_code = device_data["user_code"]
        verification_uri = device_data["verification_uri"]
        device_code = device_data["device_code"]
        interval = device_data.get("interval", 5)

        print(f"\nOpen {verification_uri} in your browser")
        print(f"Enter code: {user_code}\n")
        print("Waiting for authorization...")

        token = _poll_for_token(client, device_code, interval)

    _save_token(token)
    return token


def get_copilot_token() -> str:
    token = _load_token()
    if token is None:
        raise RuntimeError("No Copilot token found. Run `aoc-agent copilot-login` first.")
    return token

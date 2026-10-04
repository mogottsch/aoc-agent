"""Trusted exact-ID delete with raw acknowledgement; never shipped to the runner.

Vast CLI destroy__instance drops its raw result, and vastctl infers success from
inventory. Reuse vastctl's Vaultwarden loader, but not its lossy deletion path.
Endpoint/auth match the installed Vast API client's destroy_instance implementation.
"""

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import requests


def valid_id(instance):
    if type(instance) is not int or instance <= 0:
        raise ValueError("positive exact provider ID required")


def delete_ack(instance):
    valid_id(instance)
    key = os.environ.get("VAST_API_KEY")
    if not key:
        raise RuntimeError("provider credential unavailable")
    # No inherited proxies, netrc, endpoint overrides, redirects, or debug output.
    try:
        with requests.Session() as session:
            session.trust_env = False
            response = session.delete(
                f"https://console.vast.ai/api/v0/instances/{instance}/",
                headers={"Authorization": "Bearer " + key},
                json={},
                timeout=30,
                allow_redirects=False,
            )
            if not 200 <= response.status_code < 300:
                return {"success": False}
            raw = response.json()
            # Emit only the acknowledgement; raw messages may contain sensitive data.
            return {"success": isinstance(raw, dict) and raw.get("success") is True}
    except (requests.RequestException, ValueError):
        return {"success": False}


def destroy(instance):
    valid_id(instance)
    # Load only the existing trusted wrapper's definitions, never invoke its main.
    wrapper = Path("/usr/local/bin/vastctl").read_text()
    definitions, marker, _ = wrapper.partition("\nmain() {\n")
    if not marker or "\nload_api_key() {\n" not in definitions:
        raise RuntimeError("unsupported credential wrapper layout")
    script = definitions + "\nunset VAST_API_KEY VAST_URL\nload_api_key\nunset VAST_URL\n"
    script += "exec /usr/bin/python3 -I " + shlex.quote(str(Path(__file__).resolve()))
    script += " " + str(instance) + "\n"
    from vast_credentials import credential_env

    with credential_env() as env:
        p = subprocess.run(
            ["/usr/bin/bash", "-s"],
            input=script,
            capture_output=True,
            text=True,
            env=env,
            timeout=90,
        )
    if p.returncode:
        raise RuntimeError("provider delete failed (output suppressed)")
    try:
        result = json.loads(p.stdout)
    except ValueError:
        raise RuntimeError("invalid provider delete acknowledgement") from None
    if (
        not isinstance(result, dict)
        or set(result) != {"success"}
        or type(result["success"]) is not bool
    ):
        raise RuntimeError("invalid provider delete acknowledgement")
    return result


def main():
    try:
        if len(sys.argv) != 2 or not re.fullmatch(r"[1-9][0-9]*", sys.argv[1]):
            raise ValueError("invalid provider ID")
        result = delete_ack(int(sys.argv[1]))
    except (OSError, RuntimeError, ValueError):
        result = {"success": False}
    print(json.dumps(result))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

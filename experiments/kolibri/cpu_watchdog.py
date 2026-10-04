"""Fake-only Kolibri cleanup rehearsal; not a generic broker or Vast adapter.

Immutable ownership/deadline record lives off-runner. Delete acknowledgements are
not evidence of absence. Every pass rechecks exact incarnation before retrying.
"""

import argparse
import json
import math
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

FIELDS = {"provider", "instance", "owner", "lease", "created", "deadline"}


def validate(record):
    if set(record) != FIELDS or record["provider"] != "fake":
        raise ValueError("only strict fake records allowed")
    for field, prefix in (("instance", "fake-"), ("owner", "kolibri-"), ("lease", "lease-")):
        value = record[field]
        if (
            not isinstance(value, str)
            or not value.startswith(prefix)
            or not re.fullmatch(r"[a-zA-Z0-9-]{1,80}", value)
        ):
            raise ValueError("invalid fake ownership binding")
    for field in ("created", "deadline"):
        value = record[field]
        if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
            raise ValueError("invalid timestamp")
    if not 0 < record["deadline"] - record["created"] <= 600:
        raise ValueError("deadline must be positive and at most 600 seconds")


def cleanup(record, provider, *, now, execute=False):
    validate(record)
    if not execute:
        return "dry-run"
    if not math.isfinite(now):
        raise ValueError("invalid clock")
    if now < record["deadline"]:
        return "not-due"
    try:
        current = provider.get(record["instance"])
        if current is None:
            return "absent"
        if current != record:
            return "ownership-mismatch"
        provider.delete(record)
        return "absent" if provider.get(record["instance"]) is None else "retry"
    except (OSError, URLError, ValueError):
        return "retry"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("redirects forbidden")


class FakeHTTPProvider:
    def __init__(self, endpoint):
        # Literal loopback in unit tests, exact dedicated service in Kubernetes.
        if endpoint not in {"http://127.0.0.1:8081", "http://fake-provider:8081"}:
            raise ValueError("only dedicated fake-provider endpoint allowed")
        self.endpoint = endpoint
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, method, path, data=None):
        body = None if data is None else json.dumps(data).encode()
        req = Request(
            self.endpoint + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with self.opener.open(req, timeout=3) as response:
                if response.status != 200:
                    raise ValueError("non-success fake response")
                return json.loads(response.read(65537))
        except HTTPError as error:
            if error.code == 404 and method == "GET":
                return None
            raise

    def get(self, instance):
        return self.request("GET", "/instances/" + instance)

    def delete(self, record):
        self.request("DELETE", "/instances/" + record["instance"], record)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument("--execute-fake", action="store_true")
    parser.add_argument("--endpoint", default="http://fake-provider:8081")
    args = parser.parse_args()
    record = json.loads(args.record.read_text())
    validate(record)
    if not args.execute_fake:
        print(json.dumps({"status": "dry-run", "provider": "fake", "inference": False}))
        return
    provider = FakeHTTPProvider(args.endpoint)
    end = time.monotonic() + 120
    while time.monotonic() < end:
        status = cleanup(record, provider, now=time.time(), execute=True)
        print(
            json.dumps({"status": status, "instance": record["instance"], "time": time.time()}),
            flush=True,
        )
        if status == "absent":
            return
        if status == "ownership-mismatch":
            raise SystemExit(2)
        time.sleep(1)
    raise SystemExit("fake cleanup unresolved within bounded rehearsal")


if __name__ == "__main__":
    main()

"""Synthetic HTTP fixture and fake-provider-only API on distinct isolated ports."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cpu_watchdog import validate


def servers(record, *, host="0.0.0.0", ports=(8080, 8081)):
    validate(record)
    state = {
        "resources": {
            record["instance"]: dict(record),
            "fake-foreign": {**record, "instance": "fake-foreign", "owner": "kolibri-foreign"},
        },
        "attempts": 0,
        "events": [],
    }
    lock = threading.Lock()

    class Base(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, data):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    class Fixture(Base):
        def do_GET(self):
            if self.path == "/fixture":
                self.respond(
                    200,
                    {
                        "label": "SYNTHETIC_CPU_FIXTURE_NOT_KOLIBRI",
                        "input": "1\n2\n",
                        "part1": 3,
                        "part2": 2,
                    },
                )
            else:
                self.respond(404, {"error": "fixture only"})

    class Provider(Base):
        def do_GET(self):
            with lock:
                if self.path == "/audit":
                    self.respond(
                        200,
                        {
                            "attempts": state["attempts"],
                            "events": state["events"],
                            "remaining": state["resources"],
                        },
                    )
                    return
                instance = self.path.removeprefix("/instances/")
                item = state["resources"].get(instance)
                self.respond(200 if item is not None else 404, item)

        def do_DELETE(self):
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 4096:
                self.respond(400, {"error": "bounded body required"})
                return
            try:
                expected = json.loads(self.rfile.read(length))
                validate(expected)
            except (ValueError, TypeError):
                self.respond(400, {"error": "invalid fake binding"})
                return
            instance = self.path.removeprefix("/instances/")
            with lock:
                if (
                    expected != record
                    or instance != record["instance"]
                    or state["resources"].get(instance) != expected
                ):
                    self.respond(409, {"error": "atomic ownership mismatch"})
                    return
                state["attempts"] += 1
                count = state["attempts"]
                event = {
                    "attempt": count,
                    "time": time.time(),
                    "instance": instance,
                    "outcome": "503"
                    if count == 1
                    else "ack-still-present"
                    if count == 2
                    else "deleted",
                }
                state["events"].append(event)
                print(json.dumps(event), flush=True)
                if count == 1:
                    self.respond(503, {"fake": "injected transient failure"})
                elif count == 2:
                    self.respond(200, {"acknowledged": True, "deleted": False})
                else:
                    del state["resources"][instance]
                    self.respond(200, {"deleted": True})

    return ThreadingHTTPServer((host, ports[0]), Fixture), ThreadingHTTPServer(
        (host, ports[1]), Provider
    )


def main():
    record = json.loads(Path("/record/record.json").read_text())
    pair = servers(record)
    for server in pair:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    print(json.dumps({"ready": True, "fake_only": True}), flush=True)
    time.sleep(600)
    for server in pair:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()

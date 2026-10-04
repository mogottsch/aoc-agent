"""Real local TLS, no inference or provider network."""

import importlib
import json
import ssl
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_pinned_certificate_real_tls_and_bearer_transport(tmp_path):
    m = importlib.import_module("real_transport")
    directory = tmp_path / "tls"
    directory.mkdir(mode=0o700)
    secret = m.material(directory)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.headers["Authorization"] == "Bearer " + secret["api_key"]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"data": []}')

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(directory / "server.crt", directory / "server.key")
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = m.request(
            "127.0.0.1", server.server_port, secret["cert"], secret["api_key"], "GET", "/v1/models"
        )
        assert status == 200 and json.loads(body) == {"data": []}
        other = tmp_path / "other"
        other.mkdir(mode=0o700)
        wrong = m.material(other)
        with pytest.raises(ssl.SSLCertVerificationError):
            m.request(
                "127.0.0.1",
                server.server_port,
                wrong["cert"],
                secret["api_key"],
                "GET",
                "/v1/models",
            )
        with pytest.raises(ValueError):
            m.request(
                "127.0.0.1",
                server.server_port,
                secret["cert"],
                secret["api_key"],
                "GET",
                "https://elsewhere/",
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

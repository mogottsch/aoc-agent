"""Exercise the real pinned upstream -> loopback proxy -> HTTP client path."""

from __future__ import annotations

import base64
import http.client
import importlib.util
import json
import ssl
import threading
from contextlib import closing, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote, quote_plus

import httpx
import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import ModuleType


ROOT = Path(__file__).resolve().parents[1] / "experiments" / "kolibri"


def load_module(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + ".py"))
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TRANSPORT = load_module("real_transport")
DIAGNOSTICS = load_module("diagnostics")


@contextmanager
def running_server(server: ThreadingHTTPServer) -> Iterator[ThreadingHTTPServer]:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


@contextmanager
def proxy_for(
    tmp_path: Path, response_body: bytes, material: dict[str, str], *, status: int = 400
) -> Iterator[str]:
    class Upstream(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            assert self.headers["Authorization"] == "Bearer " + material["api_key"]
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(status)
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tmp_path / "tls" / "server.crt", tmp_path / "tls" / "server.key")
    upstream.socket = context.wrap_socket(upstream.socket, server_side=True)
    config = {**material, "host": "127.0.0.1", "port": upstream.server_port}
    with running_server(upstream):
        proxy = ThreadingHTTPServer(("127.0.0.1", 0), TRANSPORT.proxy_handler(config))
        with running_server(proxy):
            yield f"http://127.0.0.1:{proxy.server_port}/v1/chat/completions"


def fresh_material(tmp_path: Path) -> dict[str, str]:
    (tmp_path / "tls").mkdir(mode=0o700)
    return TRANSPORT.material(tmp_path / "tls")


def test_upstream_rejection_survives_proxy_and_persisted_failure(tmp_path: Path) -> None:
    material = fresh_material(tmp_path)
    payload = base64.b64encode(json.dumps(material).encode()).decode()
    reason = "fixture rejection: requested 9000 tokens; maximum context is 8192"
    body = json.dumps(
        {
            "error": {
                "message": reason,
                "type": "BadRequestError",
                "code": "fixture_context_limit",
                "reflected_key": material["api_key"],
                "reflected_pem": material["key"],
                "nested_json": json.dumps({"key": material["key"]}),
                "launch_payload": payload,
            }
        }
    ).encode()
    with proxy_for(tmp_path, body, material) as url, httpx.Client(trust_env=False) as client:
        response = client.post(
            url, headers={"Authorization": "Bearer " + material["api_key"]}, json={"messages": []}
        )
        assert response.status_code == 400
        error_body = response.json()["error"]
        assert isinstance(error_body, dict), "proxy destroyed structured upstream reason"
        assert error_body["message"] == reason
        assert error_body["code"] == "fixture_context_limit"
        assert error_body["type"] == "BadRequestError"
        for secret in (material["api_key"], material["key"], payload):
            assert secret not in response.text
            assert json.dumps(secret)[1:-1] not in response.text
        assert "PRIVATE KEY" not in response.text
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            DIAGNOSTICS.save_failure(tmp_path, error, year=2025, day=5)
        else:
            raise AssertionError("expected upstream HTTP rejection")
    persisted_text = (tmp_path / "failure.json").read_text()
    persisted = json.loads(persisted_text)
    assert persisted["exception"]["status_code"] == 400
    assert json.loads(persisted["exception"]["body"])["error"]["message"] == reason
    assert persisted["year"] == 2025
    assert persisted["day"] == 5
    for secret in (material["api_key"], material["key"], payload):
        assert secret not in persisted_text
        assert json.dumps(secret)[1:-1] not in persisted_text


@pytest.mark.parametrize("body", [b"reason: invalid input", b"reason: invalid input\xff", b""])
def test_malformed_rejection_is_valid_json_with_original_status(
    tmp_path: Path, body: bytes
) -> None:
    material = fresh_material(tmp_path)
    body += b" " + material["api_key"].encode() + b" " + material["key"].encode()
    with proxy_for(tmp_path, body, material) as url, httpx.Client(trust_env=False) as client:
        response = client.post(
            url, headers={"Authorization": "Bearer " + material["api_key"]}, json={"messages": []}
        )
    assert response.status_code == 400
    parsed = response.json()
    assert isinstance(parsed, dict)
    assert "reason: invalid input" in response.text or body.startswith(b" ")
    assert "[REDACTED]" in response.text
    assert material["api_key"] not in response.text
    assert "PRIVATE KEY" not in response.text


def test_large_rejection_is_bounded_after_redaction(tmp_path: Path) -> None:
    material = fresh_material(tmp_path)
    reason = "fixture: useful rejection reason"
    body = json.dumps(
        {"error": {"message": reason, "secret": material["api_key"], "padding": "é" * 100_000}}
    ).encode()
    with proxy_for(tmp_path, body, material) as url, httpx.Client(trust_env=False) as client:
        response = client.post(
            url, headers={"Authorization": "Bearer " + material["api_key"]}, json={"messages": []}
        )
    assert response.status_code == 400
    assert len(response.content) <= 64 * 1024
    assert reason in response.text
    assert response.json()["truncated"] is True
    assert material["api_key"] not in response.text


def test_rejection_redacts_pem_fragments_and_reencoded_launch_material(tmp_path: Path) -> None:
    material = fresh_material(tmp_path)
    payload = base64.b64encode(json.dumps(material, sort_keys=True, indent=2).encode()).decode()
    pem_line = material["key"].splitlines()[1]
    body = json.dumps(
        {"error": {"message": "fixture: rejected", "pem_line": pem_line, "payload": payload}}
    ).encode()
    with proxy_for(tmp_path, body, material) as url, httpx.Client(trust_env=False) as client:
        response = client.post(
            url, headers={"Authorization": "Bearer " + material["api_key"]}, json={"messages": []}
        )
    assert response.status_code == 400
    assert response.json()["error"]["message"] == "fixture: rejected"
    assert pem_line not in response.text
    assert payload not in response.text


def test_rejection_does_not_expose_reflected_prompt_headers_or_environment(tmp_path: Path) -> None:
    material = fresh_material(tmp_path)
    prompt = "PRIVATE-FIXTURE-PROMPT: do not persist this puzzle input"
    body = json.dumps(
        {
            "error": {"message": "fixture rejection: " + prompt, "code": "bad_input"},
            "messages": [{"content": prompt}],
            "headers": {"X-Private": "PRIVATE-HEADER-FIXTURE"},
            "environment": {"PRIVATE_VALUE": "PRIVATE-ENV-FIXTURE"},
        }
    ).encode()
    with proxy_for(tmp_path, body, material) as url, httpx.Client(trust_env=False) as client:
        response = client.post(
            url,
            headers={"Authorization": "Bearer " + material["api_key"]},
            json={"messages": [{"role": "user", "content": prompt}]},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_input"
    assert "fixture rejection:" in response.text
    for private in (prompt, "PRIVATE-HEADER-FIXTURE", "PRIVATE-ENV-FIXTURE"):
        assert private not in response.text


@pytest.mark.parametrize("layers", [1, 3])
def test_nested_json_private_fields_stay_redacted_in_saved_failure(
    tmp_path: Path, layers: int
) -> None:
    material = fresh_material(tmp_path)
    private = {"headers": {"X-Private": "NESTED-HEADER"}, "environment": {"VALUE": "NESTED-ENV"}}
    details = json.dumps(private)
    for _ in range(layers - 1):
        details = json.dumps({"details": details})
    body = json.dumps({"error": {"message": "fixture rejection", "details": details}}).encode()
    with proxy_for(tmp_path, body, material) as url, httpx.Client(trust_env=False) as client:
        response = client.post(
            url, headers={"Authorization": "Bearer " + material["api_key"]}, json={"messages": []}
        )
        with pytest.raises(httpx.HTTPStatusError) as raised:
            response.raise_for_status()
        DIAGNOSTICS.save_failure(tmp_path, raised.value)
    assert response.json()["error"]["message"] == "fixture rejection"
    saved = json.loads((tmp_path / "failure.json").read_text())["exception"]["body"]
    for text in (response.text, saved, (tmp_path / "failure-traceback.txt").read_text()):
        assert "NESTED-HEADER" not in text
        assert "NESTED-ENV" not in text
    cleaned = response.json()["error"]["details"]
    for _ in range(layers - 1):
        cleaned = json.loads(cleaned)["details"]
    assert json.loads(cleaned) == {"headers": "[REDACTED]", "environment": "[REDACTED]"}


@pytest.mark.parametrize("prompt", ["a", "ok"])
def test_short_prompt_preserves_reason_and_keys_in_saved_failure(
    tmp_path: Path, prompt: str
) -> None:
    material = fresh_material(tmp_path)
    reason = "fixture rejection: maximum context exceeded; requested tokens; a useful reason"
    body = json.dumps(
        {
            "error": {
                "message": reason,
                "type": "BadRequestError",
                "code": "maximum_context",
                "prompt": prompt,
                "content": prompt,
            }
        }
    ).encode()
    with proxy_for(tmp_path, body, material) as url, httpx.Client(trust_env=False) as client:
        response = client.post(
            url,
            headers={"Authorization": "Bearer " + material["api_key"]},
            json={"messages": [{"role": "user", "content": prompt}]},
        )
        with pytest.raises(httpx.HTTPStatusError) as raised:
            response.raise_for_status()
        DIAGNOSTICS.save_failure(tmp_path, raised.value)
    expected = {
        "message": reason,
        "type": "BadRequestError",
        "code": "maximum_context",
        "prompt": "[REDACTED]",
        "content": "[REDACTED]",
    }
    assert response.json()["error"] == expected
    saved = json.loads((tmp_path / "failure.json").read_text())["exception"]["body"]
    assert json.loads(saved)["error"] == expected


@pytest.mark.parametrize("padding", ["x" * 100_000, list(range(5000))], ids=["bytes", "nodes"])
def test_reason_after_oversized_metadata_survives_saved_failure(
    tmp_path: Path, padding: str | list[int]
) -> None:
    material = fresh_material(tmp_path)
    reason = "fixture rejection: maximum context exceeded (synthetic fixture only)"
    evidence = {
        "message": reason,
        "type": "BadRequestError",
        "code": "fixture_limit",
        "status": 400,
    }
    body = json.dumps(
        {
            "metadata": padding,
            "error": {"padding": padding, **evidence, "prompt": "PRIVATE-PAD-PROMPT"},
        }
    ).encode()
    with proxy_for(tmp_path, body, material) as url, httpx.Client(trust_env=False) as client:
        response = client.post(
            url,
            headers={"Authorization": "Bearer " + material["api_key"]},
            json={"messages": [{"content": "PRIVATE-PAD-PROMPT"}]},
        )
        with pytest.raises(httpx.HTTPStatusError) as raised:
            response.raise_for_status()
        DIAGNOSTICS.save_failure(tmp_path, raised.value)
    assert response.status_code == 400
    assert len(response.content) <= 64 * 1024
    parsed = response.json()
    for field, value in evidence.items():
        assert parsed["error"][field] == value
    assert parsed["truncated"] is True
    assert "PRIVATE-PAD-PROMPT" not in response.text
    saved = json.loads((tmp_path / "failure.json").read_text())["exception"]["body"]
    assert json.loads(saved) == parsed


@pytest.mark.parametrize("encoding", ["percent", "plus", "short"])
def test_url_encoded_prompt_query_is_redacted_in_saved_failure(
    tmp_path: Path, encoding: str
) -> None:
    material = fresh_material(tmp_path)
    prompt = "a" if encoding == "short" else "PRIVATE url prompt / é & data"
    escaped = quote_plus(prompt) if encoding == "plus" else quote(prompt, safe="")
    reason = "fixture rejection: maximum context exceeded; "
    message = reason + "https://fixture.invalid/reject?prompt=" + escaped + "&code=bad_input"
    body = json.dumps({"error": {"message": message, "prompt": prompt}}).encode()
    with proxy_for(tmp_path, body, material) as url, httpx.Client(trust_env=False) as client:
        response = client.post(
            url,
            headers={"Authorization": "Bearer " + material["api_key"]},
            json={"messages": [{"content": prompt}]},
        )
        with pytest.raises(httpx.HTTPStatusError) as raised:
            response.raise_for_status()
        DIAGNOSTICS.save_failure(tmp_path, raised.value)
    expected = {
        "message": reason + "https://fixture.invalid/reject?prompt=[REDACTED]&code=bad_input",
        "prompt": "[REDACTED]",
    }
    assert response.json()["error"] == expected
    saved = json.loads((tmp_path / "failure.json").read_text())["exception"]["body"]
    assert json.loads(saved)["error"] == expected


def test_unicode_essential_fields_and_supplemental_details_fit_byte_limit(tmp_path: Path) -> None:
    material = fresh_material(tmp_path)
    reason = "fixture rejection: " + "😀" * 10_000 + material["api_key"]
    body = json.dumps(
        {"error": dict.fromkeys(("message", "type", "code", "status", "status_code"), reason)}
    ).encode()
    with proxy_for(tmp_path, body, material) as url, httpx.Client(trust_env=False) as client:
        response = client.post(
            url, headers={"Authorization": "Bearer " + material["api_key"]}, json={"messages": []}
        )
    assert response.status_code == 400
    assert len(response.content) <= 64 * 1024
    assert response.json()["error"]["message"].startswith("fixture rejection:")
    assert response.json()["truncated"] is True
    assert material["api_key"] not in response.text


@pytest.mark.parametrize("shape", ["nodes", "depth"])
def test_request_private_scan_exhaustion_fails_closed(tmp_path: Path, shape: str) -> None:
    material = fresh_material(tmp_path)
    private = "PRIVATE-UNSCANNED-PROMPT"
    if shape == "nodes":
        request_data = json.dumps({"messages": [{"content": private}] * 5000}).encode()
    else:
        nested: object = private
        for _ in range(20):
            nested = [nested]
        request_data = json.dumps({"input": nested}).encode()
    body = json.dumps({"error": {"message": "fixture rejection: " + private}}).encode()
    with proxy_for(tmp_path, body, material) as url, httpx.Client(trust_env=False) as client:
        response = client.post(
            url, headers={"Authorization": "Bearer " + material["api_key"]}, content=request_data
        )
        with pytest.raises(httpx.HTTPStatusError) as raised:
            response.raise_for_status()
        DIAGNOSTICS.save_failure(tmp_path, raised.value)
    assert response.json()["truncated"] is True
    assert private not in response.text
    assert private not in (tmp_path / "failure.json").read_text()
    assert len(response.content) <= 64 * 1024


def test_nested_json_decode_work_exhaustion_drops_unscanned_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Scale the same input-derived character budget down for a compact fixture.
    monkeypatch.setattr(TRANSPORT, "LIMIT", 4096)
    material = fresh_material(tmp_path)
    details = json.dumps({"headers": {"secret": "PRIVATE-DEEP-HEADER"}, "padding": "x" * 1800})
    for _ in range(6):
        details = json.dumps(details)
    body = json.dumps({"error": {"message": "fixture rejection", "details": details}}).encode()
    assert len(body) <= TRANSPORT.LIMIT
    with proxy_for(tmp_path, body, material) as url, httpx.Client(trust_env=False) as client:
        response = client.post(
            url, headers={"Authorization": "Bearer " + material["api_key"]}, json={"messages": []}
        )
    assert response.status_code == 400
    assert response.json()["error"]["message"] == "fixture rejection"
    assert response.json()["truncated"] is True
    assert "PRIVATE-DEEP-HEADER" not in response.text


def test_credential_reflected_as_field_name_does_not_leak(tmp_path: Path) -> None:
    material = fresh_material(tmp_path)
    body = json.dumps(
        {"error": {"message": "fixture rejection", material["api_key"]: "reflected credential"}}
    ).encode()
    with proxy_for(tmp_path, body, material) as url, httpx.Client(trust_env=False) as client:
        response = client.post(
            url,
            headers={"Authorization": "Bearer " + material["api_key"]},
            json={"messages": [{"content": "a"}]},
        )
    assert response.json()["error"]["message"] == "fixture rejection"
    assert material["api_key"] not in response.text


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity"])
def test_non_json_numbers_never_escape_as_invalid_diagnostic_json(
    tmp_path: Path, number: str
) -> None:
    material = fresh_material(tmp_path)
    body = ('{"error":{"message":"fixture rejection","value":' + number + "}}").encode()
    with proxy_for(tmp_path, body, material) as url, httpx.Client(trust_env=False) as client:
        response = client.post(
            url, headers={"Authorization": "Bearer " + material["api_key"]}, json={"messages": []}
        )

    def reject_constant(value: str) -> None:
        pytest.fail("non-JSON numeric constant in diagnostic: " + value)

    parsed = json.loads(response.text, parse_constant=reject_constant)
    assert parsed["error"]["message"] == "fixture rejection"
    assert response.status_code == 400


@pytest.mark.parametrize("status", [200, 401, 429, 500, 302])
def test_proxy_preserves_success_and_error_status_but_refuses_redirects(
    tmp_path: Path, status: int
) -> None:
    material = fresh_material(tmp_path)
    body = b'{"error":{"message":"fixture status reason"}}'
    with (
        proxy_for(tmp_path, body, material, status=status) as url,
        httpx.Client(trust_env=False, follow_redirects=False) as client,
    ):
        response = client.post(
            url,
            headers={"Authorization": "Bearer " + material["api_key"]},
            json={"messages": []},
        )
    assert response.status_code == (502 if status == 302 else status)
    if status != 302:
        assert response.json()["error"]["message"] == "fixture status reason"
    if status == 200:
        assert response.content == body


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"Authorization": "Bearer wrong-fixture-token"}, 401),
        ({"Content-Length": str(16 * 1024 * 1024 + 1)}, 502),
        ({"Transfer-Encoding": "chunked"}, 502),
    ],
)
def test_proxy_keeps_auth_and_request_size_controls(
    tmp_path: Path, headers: dict[str, str], expected: int
) -> None:
    material = fresh_material(tmp_path)
    # stdlib permits an oversized declared length without allocating/sending it.
    with (
        proxy_for(tmp_path, b"{}", material) as url,
        closing(http.client.HTTPConnection("127.0.0.1", httpx.URL(url).port, timeout=5)) as client,
    ):
        client.request(
            "POST",
            "/v1/chat/completions",
            headers={"Authorization": "Bearer " + material["api_key"], **headers},
        )
        response = client.getresponse()
        response.read()
        assert response.status == expected

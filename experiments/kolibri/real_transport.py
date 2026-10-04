"""TLS-pinned disposable vLLM transport, served to run.py on literal loopback."""

import argparse
import base64
import http.client
import ipaddress
import json
import math
import re
import secrets
import socket
import ssl
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import chain
from pathlib import Path

LIMIT = 16 * 1024 * 1024
DIAGNOSTIC_LIMIT = 64 * 1024


def material(directory):
    if directory.is_symlink() or directory.stat().st_mode & 0o077:
        raise ValueError("private certificate directory required")
    cert, key = directory / "server.crt", directory / "server.key"
    if cert.exists() or key.exists():
        raise ValueError("fresh certificate required")
    subprocess.run(
        [
            "/usr/bin/openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=kolibri.invalid",
            "-addext",
            "subjectAltName=DNS:kolibri.invalid",
        ],
        capture_output=True,
        check=True,
        timeout=20,
    )
    key.chmod(0o600)
    cert.chmod(0o600)
    return {"api_key": secrets.token_hex(32), "cert": cert.read_text(), "key": key.read_text()}


def request(host, port, cert, api_key, method, path, body=None, *, timeout=1800):
    ipaddress.ip_address(host)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("invalid port")
    if (method, path) not in {("GET", "/v1/models"), ("POST", "/v1/chat/completions")}:
        raise ValueError("unsupported inference path")
    if body is not None and len(body) > LIMIT:
        raise ValueError("oversized inference body")
    # No system CA fallback, no proxy env, no redirects, TLS SNI is the pinned SAN.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_verify_locations(cadata=cert)
    sock = context.wrap_socket(
        socket.create_connection((host, port), timeout=timeout), server_hostname="kolibri.invalid"
    )
    connection = http.client.HTTPConnection("kolibri.invalid", timeout=timeout)
    connection.sock = sock
    try:
        connection.request(
            method,
            path,
            body=body,
            headers={
                "Authorization": "Bearer " + api_key,
                "Content-Type": "application/json",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        data = response.read(LIMIT + 1)
        if len(data) > LIMIT or 300 <= response.status < 400:
            raise ValueError("invalid upstream response")
        return response.status, data
    finally:
        connection.close()


def rejection_body(  # noqa: C901 - bounded parsing, redaction and serialization boundary
    data: bytes, config: dict[str, str], request_body: bytes | None = None
) -> bytes:
    """Keep structured upstream evidence, never reflected disposable credentials.

    Self-contained for the isolated (-I) proxy; no environment or writable imports.
    Complete JSON strings are parsed recursively (depth 12, 4096 node visits,
    2 * LIMIT decoded characters); exhaustion discards unscanned values.
    Request discovery has separate depth/node bounds, LIMIT private characters
    and at most 256 unique private strings; incomplete discovery fails closed.

    Prompt policy: private fields are suppressed structurally, exact scalar
    reflections are suppressed, and strings of at least 8 characters are also
    matched verbatim in values, never keys. Short prompts are not globally
    substituted into prose. URL/form encoding is supported only in labelled
    private key=value/query parameters with literal field names; arbitrary
    unlabelled encodings, transformed or partial prompt echoes are not covered.
    Oversized output keeps 512 characters per essential scalar string plus a
    sanitized supplemental excerpt; the serialized envelope is at most 64 KiB.
    """
    material = {name: config[name] for name in ("api_key", "cert", "key") if name in config}
    known = [config["api_key"], config.get("key", "")]
    known.append(base64.b64encode(json.dumps(material).encode()).decode())
    known.extend(line for line in config.get("key", "").splitlines() if line)
    prompts = set()
    private_fields = {
        "content",
        "input",
        "prompt",
        "prompts",
        "messages",
        "headers",
        "request_headers",
        "env",
        "environment",
    }

    scan_remaining = [4096, LIMIT]

    def collect_private(value: object, depth: int = 0, *, private: bool = False) -> None:
        scan_remaining[0] -= 1
        if depth > 12 or scan_remaining[0] < 0:
            raise ValueError("private-field scan limit")
        if isinstance(value, str) and private:
            scan_remaining[1] -= len(value)
            if scan_remaining[1] < 0 or len(prompts) >= 256:
                raise ValueError("private-string scan limit")
            prompts.add(value)
        elif isinstance(value, dict):
            for key, item in value.items():
                if key != "role":
                    collect_private(
                        item, depth + 1, private=private or key.lower() in private_fields
                    )
        elif isinstance(value, list):
            for item in value:
                collect_private(item, depth + 1, private=private)

    # Only request private values need cross-field reflection detection. Provider
    # private fields are removed structurally, including inside nested JSON.
    # If we cannot finish request discovery, no upstream prose is safe to retain.
    if request_body:
        try:
            collect_private(json.loads(request_body))
        except (ValueError, UnicodeDecodeError, RecursionError):
            return b'{"error":{"message":"[REDACTED]"},"truncated":true}'
    spellings = set()
    for secret in known:
        if secret:
            spellings.add(secret)
            encoded_secret = secret
            for _ in range(2):
                encoded_secret = json.dumps(encoded_secret)[1:-1]
                spellings.add(encoded_secret)
    ordered = sorted(spellings, key=len, reverse=True)
    # Common short prompts are not credentials: replace whole values, never
    # their occurrences inside diagnostic prose or structural field names.
    long_prompts = sorted((text for text in prompts if len(text) >= 8), key=len, reverse=True)

    def sanitize_payload(match: re.Match[str]) -> str:
        candidate = match.group()
        try:
            decoded = base64.b64decode(candidate, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return candidate
        return "[REDACTED]" if any(secret in decoded for secret in ordered) else candidate

    def sanitize_credentials(value: str) -> str:
        value = re.sub(r"[A-Za-z0-9+/]{32,}={0,2}", sanitize_payload, value)
        for secret in ordered:
            value = value.replace(secret, "[REDACTED]")
        return value

    # Nested JSON is provider-controlled too. Exhaustion fails closed, not to an
    # unsanitized string; count both tree visits and decoded JSON characters.
    remaining = [4096, 2 * LIMIT]
    clipped = [False]
    priority = ("error", "message", "type", "code", "status", "status_code")

    def sanitize(value: object, depth: int = 0) -> object:
        remaining[0] -= 1
        if depth > 12 or remaining[0] < 0:
            clipped[0] = True
            return "[REDACTED]"
        if isinstance(value, str):
            if value.lstrip().startswith(("{", "[", '"')):
                remaining[1] -= len(value)
                if remaining[1] < 0:
                    clipped[0] = True
                    return "[REDACTED]"
                try:
                    nested = json.loads(value)
                except (ValueError, RecursionError):
                    return "[REDACTED]"
                return json.dumps(sanitize(nested, depth + 1), ensure_ascii=True)
            # Recognize re-serialized launch material without blanket base64 suppression.
            value = re.sub(r"[A-Za-z0-9+/]{32,}={0,2}", sanitize_payload, value)
            if value in prompts:
                return "[REDACTED]"
            # Scoped key=value/query values include percent and form (+) URL
            # encoding without decoding/re-emitting the surrounding diagnostic.
            value = re.sub(
                r"(?i)(\b(?:prompt|prompts|content|input|messages|headers|environment|env)=)"
                r"[^&;\s\"'<>]+",
                r"\1[REDACTED]",
                value,
            )
            for secret in (*ordered, *long_prompts):
                value = value.replace(secret, "[REDACTED]")
            return value
        if isinstance(value, dict):
            cleaned = {}
            # Inspect diagnostic essentials before arbitrary supplemental metadata.
            keys = (key for key in priority if key in value)
            other = (key for key in value if key not in priority)
            for key in chain(keys, other):
                if remaining[0] <= 0:
                    clipped[0] = True
                    break
                cleaned[sanitize_credentials(key)] = (
                    "[REDACTED]"
                    if key.lower() in private_fields
                    else sanitize(value[key], depth + 1)
                )
            return cleaned
        if isinstance(value, list):
            cleaned = []
            for item in value:
                if remaining[0] <= 0:
                    clipped[0] = True
                    break
                cleaned.append(sanitize(item, depth + 1))
            return cleaned
        if isinstance(value, float) and not math.isfinite(value):
            return "[REDACTED]"
        return value

    try:
        result = sanitize(json.loads(data))
        encoded = json.dumps(result, ensure_ascii=True, allow_nan=False).encode()
    except (ValueError, UnicodeDecodeError, RecursionError):
        # Invalid UTF-8 is displayed losslessly as byte escapes, not dropped.
        result = {"error": {"message": sanitize(data.decode("utf-8", errors="backslashreplace"))}}
        encoded = json.dumps(result, ensure_ascii=True).encode()
    if clipped[0] and isinstance(result, dict):
        result["truncated"] = True
        encoded = json.dumps(result, ensure_ascii=True, allow_nan=False).encode()
    if len(encoded) <= DIAGNOSTIC_LIMIT:
        return encoded
    # Keep essential structured evidence, not a prefix dominated by metadata.
    # Only already-sanitized data may enter the bounded supplemental excerpt.
    source = result.get("error", result) if isinstance(result, dict) else result
    if isinstance(source, dict):
        evidence = {
            key: item[:512] if isinstance(item, str) else item
            for key, item in source.items()
            if key in priority[1:] and isinstance(item, (str, int, float, bool, type(None)))
        }
    else:
        evidence = {"message": str(source)[:512]}
    envelope = {"error": evidence, "details": "", "truncated": True}
    overhead = len(json.dumps(envelope, ensure_ascii=True).encode())
    # The supplemental excerpt is ASCII JSON text; outer quoting adds at most
    # one byte per character. Essential Unicode fields are bounded separately.
    envelope["details"] = encoded.decode("ascii")[: (DIAGNOSTIC_LIMIT - overhead) // 2]
    return json.dumps(envelope, ensure_ascii=True).encode()


def proxy_handler(config):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # Never persist prompt, Authorization, or provider errors.

        def handle_request(self):
            if not secrets.compare_digest(
                self.headers.get("Authorization", ""), "Bearer " + config["api_key"]
            ):
                self.send_error(401)
                return
            try:
                if self.headers.get("Transfer-Encoding"):
                    raise ValueError("chunked request forbidden")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 <= length <= LIMIT:
                    raise ValueError("body too large")
                body = self.rfile.read(length) if length else None
                status, data = request(
                    config["host"],
                    config["port"],
                    config["cert"],
                    config["api_key"],
                    self.command,
                    self.path,
                    body,
                )
                if status != 200:
                    data = rejection_body(data, config, body)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (OSError, ValueError, http.client.HTTPException):
                self.send_error(502, "secure serving transport failed")

        do_GET = handle_request
        do_POST = handle_request

    return Handler


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("config", type=Path)
    args = p.parse_args()
    config = json.loads(args.config.read_text())
    # Mounted config contains only disposable serving token, cert and public host.
    with ThreadingHTTPServer(("127.0.0.1", 8000), proxy_handler(config)) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()

"""Trusted pre-delete provider log capture. Never ship this into the runner pod.

The fixed trusted wrapper owns provider authentication and URLs. Preserve its entire
byte stdout/stderr, requesting the supported --tail 20000 provider cap rather than
the CLI's 1000-line default. Provider log completeness remains unknown.
"""

import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path


def _persist(directory, name, data):
    fd = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return {"file": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _provider_json_error(data):
    """Recognize error envelopes, including JSON lines mixed with diagnostics."""
    for candidate in (data, *data.splitlines()):
        try:
            payload = json.loads(candidate)
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("error") is True:
            return True
    return False


def capture_provider_logs(record, directory, known_secrets=(), *, provider=None, timeout=90):
    """Persist container and daemon logs; return metadata, never log text.

    ``record`` must already have an exact instance/label/start_date binding.
    ``directory`` must be private and trusted; each call creates a fresh 0700
    child containing 0600 files. ``known_secrets`` is a list/tuple/set of str or
    bytes values, not a dictionary or a single string. Include opaque encoded
    launch payloads as separate values if those can appear in provider logs.

    Recheck inventory before each fetch. Capture failures return status=failed
    and retain redacted diagnostics; invalid input or local persistence failures
    raise. The caller must run this BEFORE deletion and must never print files.
    Wrapper CLI blank-line normalization is upstream; this helper preserves all
    wrapper output bytes without decoding, truncating, or further normalization.
    """
    from real_lifecycle import Vast, secure_dir
    from vast_credentials import credential_env

    if not isinstance(record, dict) or not {"instance", "label", "start_date"} <= record.keys():
        raise ValueError("invalid provider binding")
    binding = {key: record[key] for key in ("instance", "label", "start_date")}
    if (
        type(binding["instance"]) is not int
        or binding["instance"] <= 0
        or not isinstance(binding["label"], str)
        or not re.fullmatch(r"hermes-kolibri-[0-9a-f]{32}", binding["label"])
        or type(binding["start_date"]) not in (int, float)
        or not math.isfinite(binding["start_date"])
    ):
        raise ValueError("invalid provider binding")

    if not isinstance(known_secrets, (tuple, list, set, frozenset)) or any(
        not isinstance(secret, (str, bytes)) for secret in known_secrets
    ):
        raise ValueError("known_secrets must be a collection of strings or bytes")
    spellings = set()
    for secret in known_secrets:
        if not secret:
            continue
        data = secret.encode() if isinstance(secret, str) else secret
        spellings.add(data)
        try:
            text = data.decode()
        except UnicodeDecodeError:
            continue
        spellings.add(json.dumps(text)[1:-1].encode())
        if "PRIVATE KEY-----" in text:
            spellings.update(line.encode() for line in text.splitlines() if line)
    pattern = (
        re.compile(b"|".join(re.escape(s) for s in sorted(spellings, key=len, reverse=True)))
        if spellings
        else None
    )

    def persist(name, data):
        if pattern:
            data = pattern.sub(b"[REDACTED]", data)
        return _persist(root, name, data)

    directory = Path(directory).absolute()
    if any(path.is_symlink() for path in (directory, *directory.parents)):
        raise ValueError("artifact directory symlink forbidden")
    secure_dir(directory)
    root = Path(tempfile.mkdtemp(prefix="provider-logs-", dir=directory))
    result = {
        "version": 1,
        "directory": str(root),
        "status": "captured",
        "provider_tail_cap": 20000,
        "completeness": "unknown",
        "streams": {},
    }
    provider = provider if provider is not None else Vast()
    for name in ("container", "daemon"):
        stream = {"status": "failed", "returncode": None}
        stdout, stderr, error = b"", b"", b""
        try:
            rows = provider.call("list")
            targets = [r for r in rows if r.get("id") == binding["instance"]]
            labels = [r for r in rows if r.get("label") == binding["label"]]
            if (
                len(targets) != 1
                or len(labels) != 1
                or type(targets[0].get("id")) is not int
                or type(targets[0].get("start_date")) not in (int, float)
                or targets[0].get("label") != binding["label"]
                or targets[0].get("start_date") != binding["start_date"]
            ):
                raise ValueError("provider ownership not verified")
            command = [
                "/usr/local/bin/vastctl",
                "logs",
                str(binding["instance"]),
                "--tail",
                str(result["provider_tail_cap"]),
            ]
            if name == "daemon":
                command.append("--daemon-logs")
            with credential_env() as env:
                completed = subprocess.run(
                    command, capture_output=True, env=env, stdin=subprocess.DEVNULL, timeout=timeout
                )
            stdout, stderr = completed.stdout, completed.stderr
            stream["returncode"] = completed.returncode
            if completed.returncode:
                error = f"provider logs exited with status {completed.returncode}\n".encode()
            elif _provider_json_error(stdout) or _provider_json_error(stderr):
                error = b"provider JSON error despite zero exit status\n"
            else:
                stream["status"] = "captured"
        except Exception as exc:
            stdout = getattr(exc, "stdout", None) or getattr(exc, "output", None) or b""
            stderr = getattr(exc, "stderr", None) or b""
            stream["returncode"] = getattr(exc, "returncode", None)
            error = (type(exc).__name__ + ": " + str(exc) + "\n").encode()
        for kind, data in (("stdout", stdout), ("stderr", stderr), ("error", error)):
            if isinstance(data, str):
                data = data.encode()
            stream[kind] = persist(
                name + (".error.txt" if kind == "error" else "." + kind + ".log"), data
            )
        if stream["status"] != "captured":
            result["status"] = "failed"
        result["streams"][name] = stream
    _persist(root, "metadata.json", (json.dumps(result, sort_keys=True, indent=2) + "\n").encode())
    return result

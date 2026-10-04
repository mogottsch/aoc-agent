"""Fake-only provider-log preservation tests; no vault or provider access."""

import hashlib
import importlib
import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def adapter():
    try:
        return importlib.import_module("provider_logs")
    except ModuleNotFoundError:
        pytest.fail("provider_logs capture helper is not implemented")


def record():
    return {"instance": 789, "label": "hermes-kolibri-" + "a" * 32, "start_date": 1010.0}


class Inventory:
    def __init__(self, rows=None):
        r = record()
        self.rows = (
            rows
            if rows is not None
            else [
                {"id": r["instance"], "label": r["label"], "start_date": r["start_date"]},
                {"id": 900, "label": "unrelated", "start_date": 1010.0},
            ]
        )
        self.calls = []

    def call(self, command, *args):
        self.calls.append((command, args))
        assert (command, args) == ("list", ())
        return self.rows


@pytest.fixture
def fake_only(monkeypatch):
    credentials = importlib.import_module("vast_credentials")
    life = importlib.import_module("real_lifecycle")

    @contextmanager
    def private_env():
        yield {
            "PATH": "/usr/bin",
            "HOME": "/nonexistent",
            "BITWARDENCLI_APPDATA_DIR": "/fake/private",
        }

    monkeypatch.setattr(credentials, "credential_env", private_env)
    monkeypatch.setattr(life.Vast, "call", lambda *a, **k: pytest.fail("live inventory forbidden"))
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: pytest.fail("unstubbed subprocess forbidden")
    )


def test_keeps_more_than_1000_lines_in_both_streams_privately(
    tmp_path, monkeypatch, fake_only, capsys
):
    m = adapter()
    full = b"\n".join(f"line {i}".encode() for i in range(2501)) + b"\n\n\xffEOF\n"
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        assert cmd[:5] == ["/usr/local/bin/vastctl", "logs", "789", "--tail", "20000"]
        assert kw == {
            "capture_output": True,
            "env": {
                "PATH": "/usr/bin",
                "HOME": "/nonexistent",
                "BITWARDENCLI_APPDATA_DIR": "/fake/private",
            },
            "stdin": subprocess.DEVNULL,
            "timeout": 90,
        }
        return subprocess.CompletedProcess(cmd, 0, full, b"diagnostic\n")

    monkeypatch.setattr(m.subprocess, "run", run)
    p = Inventory()
    result = m.capture_provider_logs(record(), tmp_path / "logs", (), provider=p)
    assert result["status"] == "captured"
    assert result["provider_tail_cap"] == 20000
    assert result["completeness"] == "unknown"
    assert calls == [
        ["/usr/local/bin/vastctl", "logs", "789", "--tail", "20000"],
        ["/usr/local/bin/vastctl", "logs", "789", "--tail", "20000", "--daemon-logs"],
    ]
    root = Path(result["directory"])
    assert root.stat().st_mode & 0o777 == 0o700
    for name in ("container", "daemon"):
        stream = result["streams"][name]
        assert stream["status"] == "captured"
        assert (root / stream["stdout"]["file"]).read_bytes() == full
        assert (root / stream["stderr"]["file"]).read_bytes() == b"diagnostic\n"
        assert stream["stdout"]["size"] == len(full)
        assert stream["stdout"]["sha256"] == hashlib.sha256(full).hexdigest()
    assert json.loads((root / "metadata.json").read_text()) == result
    assert all(f.stat().st_mode & 0o777 == 0o600 for f in root.iterdir())
    assert all(command == "list" for command, args in p.calls)
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("channel", ["stdout", "stderr"])
@pytest.mark.parametrize("failed_stream", ["container", "daemon"])
@pytest.mark.parametrize("formatting", ["compact", "pretty", "diagnostic-line"])
def test_zero_exit_provider_json_error_fails_and_preserves_outputs(
    tmp_path, monkeypatch, fake_only, capsys, channel, failed_stream, formatting
):
    m = adapter()
    token = "FAKE_provider_error_secret"  # noqa: S105 - synthetic redaction fixture
    payload = {
        "error": True,
        "status_code": 400,
        "message": "tail: Input should be a valid integer " + token,
    }
    raw = json.dumps(payload, indent=2 if formatting == "pretty" else None).encode() + b"\n"
    if formatting == "diagnostic-line":
        raw = b"provider diagnostic\n" + raw + b"additional diagnostic\n"
    outputs = {"stdout": b"partial logs\n\n\xff\n", "stderr": b"wrapper diagnostic\n"}
    outputs[channel] = raw
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        name = "daemon" if "--daemon-logs" in cmd else "container"
        if name == failed_stream:
            return subprocess.CompletedProcess(cmd, 0, outputs["stdout"], outputs["stderr"])
        return subprocess.CompletedProcess(cmd, 0, b"other stream logs\n", b"")

    monkeypatch.setattr(m.subprocess, "run", run)
    result = m.capture_provider_logs(record(), tmp_path / "logs", [token], provider=Inventory())
    assert result["status"] == "failed"
    assert result["provider_tail_cap"] == 20000
    assert result["completeness"] == "unknown"
    assert len(calls) == 2
    root = Path(result["directory"])
    failed = result["streams"][failed_stream]
    assert failed["status"] == "failed"
    assert failed["returncode"] == 0
    for kind, original in outputs.items():
        preserved = original.replace(token.encode(), b"[REDACTED]")
        assert (root / failed[kind]["file"]).read_bytes() == preserved
        assert failed[kind]["size"] == len(preserved)
        assert failed[kind]["sha256"] == hashlib.sha256(preserved).hexdigest()
    assert b"provider JSON error" in (root / failed["error"]["file"]).read_bytes()
    other = "container" if failed_stream == "daemon" else "daemon"
    assert result["streams"][other]["status"] == "captured"
    assert json.loads((root / "metadata.json").read_text()) == result
    assert all(f.stat().st_mode & 0o777 == 0o600 for f in root.iterdir())
    assert token not in json.dumps(result)
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "raw",
    [
        b'{"error": false, "status_code": 200}\n',
        b'{"error": "true"}\n',
        b'{"message": "error:true"}\n',
        b'[{"error": true}]\n',
        b'{"error": true\n',
        b'\xff\nordinary diagnostic\n',
    ],
)
def test_non_error_output_is_preserved_without_false_failure(tmp_path, monkeypatch, fake_only, raw):
    m = adapter()
    monkeypatch.setattr(
        m.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, raw, raw)
    )
    result = m.capture_provider_logs(record(), tmp_path / "logs", provider=Inventory())
    assert result["status"] == "captured"
    root = Path(result["directory"])
    for stream in result["streams"].values():
        assert stream["status"] == "captured"
        assert stream["returncode"] == 0
        for kind in ("stdout", "stderr"):
            assert (root / stream[kind]["file"]).read_bytes() == raw
        assert (root / stream["error"]["file"]).read_bytes() == b""


def test_exact_secrets_redacted_in_all_outputs_without_losing_diagnostics(
    tmp_path, monkeypatch, fake_only, capsys
):
    m = adapter()
    token = "FAKE_token_exact_123"  # noqa: S105 - synthetic redaction fixture
    key = (
        "-----BEGIN PRIVATE KEY-----\n"
        "FAKE_KEY_LINE_123\nFAKE_KEY_LINE_456\n"
        "-----END PRIVATE KEY-----\n"
    )
    escaped_key = json.dumps(key)[1:-1]
    raw = (
        "before\n"
        + token
        + "\n"
        + key
        + escaped_key
        + "\nFAKE_KEY_LINE_123\n"
        + "keep FAKE_token_exact_12 and arbitrary diagnostic\n"
    ).encode()
    monkeypatch.setattr(
        m.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, raw, raw)
    )
    result = m.capture_provider_logs(
        record(), tmp_path / "logs", [token, key], provider=Inventory()
    )
    root = Path(result["directory"])
    for stream in result["streams"].values():
        for kind in ("stdout", "stderr"):
            data = (root / stream[kind]["file"]).read_bytes()
            assert token.encode() not in data
            assert key.encode() not in data
            assert escaped_key.encode() not in data
            assert b"FAKE_KEY_LINE_123" not in data
            assert b"FAKE_KEY_LINE_456" not in data
            assert b"keep FAKE_token_exact_12 and arbitrary diagnostic" in data
            assert b"[REDACTED]" in data
            assert stream[kind]["size"] == len(data)
            assert stream[kind]["sha256"] == hashlib.sha256(data).hexdigest()
    assert token not in json.dumps(result) and key not in json.dumps(result)
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "change",
    ["absent", "label", "start_date", "duplicate-id", "duplicate-label", "bool-id", "bool-start"],
)
def test_unverified_ownership_never_fetches_logs(tmp_path, fake_only, change):
    m = adapter()
    p = Inventory()
    if change == "absent":
        p.rows = p.rows[1:]
    elif change == "duplicate-id":
        p.rows.append(dict(p.rows[0]))
    elif change == "duplicate-label":
        p.rows[1]["label"] = record()["label"]
    elif change == "bool-id":
        p.rows[0]["id"] = True
    elif change == "bool-start":
        p.rows[0]["start_date"] = True
    else:
        p.rows[0][change] = "wrong" if change == "label" else 1011
    result = m.capture_provider_logs(record(), tmp_path / "logs", provider=p)
    assert result["status"] == "failed"
    assert all(s["status"] == "failed" for s in result["streams"].values())
    assert all(
        "ownership" in (Path(result["directory"]) / s["error"]["file"]).read_text()
        for s in result["streams"].values()
    )


def test_ownership_rechecked_before_daemon_fetch(tmp_path, monkeypatch, fake_only):
    m = adapter()
    p = Inventory()
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        p.rows[0]["start_date"] = 2020
        return subprocess.CompletedProcess(cmd, 0, b"owned container", b"")

    monkeypatch.setattr(m.subprocess, "run", run)
    result = m.capture_provider_logs(record(), tmp_path / "logs", provider=p)
    assert result["status"] == "failed"
    assert result["streams"]["container"]["status"] == "captured"
    assert result["streams"]["daemon"]["status"] == "failed"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "failure", ["nonzero", "timeout", "called-process", "inventory", "credential", "os-error"]
)
def test_failure_diagnostics_are_complete_private_redacted_and_daemon_still_attempted(
    tmp_path, monkeypatch, fake_only, capsys, failure
):
    m = adapter()
    token = "FAKE_failure_secret"  # noqa: S105 - synthetic redaction fixture
    stdout = ("progress " + token + "\n") * 1500
    stderr = "FULL FAILURE DIAGNOSTIC " + token + "\n"
    p = Inventory()
    calls = []

    if failure == "inventory":

        def inventory(command, *args):
            p.calls.append((command, args))
            if len(p.calls) == 1:
                raise RuntimeError(stderr)
            return p.rows

        p.call = inventory
    if failure == "credential":
        credentials = importlib.import_module("vast_credentials")
        attempts = []

        @contextmanager
        def credential_env():
            attempts.append(True)
            if len(attempts) == 1:
                raise RuntimeError(stderr)
            yield {
                "PATH": "/usr/bin",
                "HOME": "/nonexistent",
                "BITWARDENCLI_APPDATA_DIR": "/fake/private",
            }

        monkeypatch.setattr(credentials, "credential_env", credential_env)

    def run(cmd, **kw):
        calls.append(cmd)
        if "--daemon-logs" in cmd:
            return subprocess.CompletedProcess(cmd, 0, b"daemon recovered\n", b"")
        if failure == "nonzero":
            return subprocess.CompletedProcess(cmd, 9, stdout.encode(), stderr.encode())
        if failure == "timeout":
            raise subprocess.TimeoutExpired(
                cmd, kw["timeout"], output=stdout.encode(), stderr=stderr.encode()
            )
        if failure == "called-process":
            raise subprocess.CalledProcessError(
                9, cmd, output=stdout.encode(), stderr=stderr.encode()
            )
        if failure == "os-error":
            raise OSError(stderr)
        pytest.fail("fetch forbidden after failed inventory/credentials")

    monkeypatch.setattr(m.subprocess, "run", run)
    result = m.capture_provider_logs(record(), tmp_path / "logs", [token], provider=p)
    assert result["status"] == "failed"
    root = Path(result["directory"])
    failed = result["streams"]["container"]
    assert failed["status"] == "failed"
    data = b"".join((root / failed[k]["file"]).read_bytes() for k in ("stdout", "stderr", "error"))
    assert token.encode() not in data
    if failure in ("nonzero", "timeout", "called-process"):
        assert (root / failed["stdout"]["file"]).read_bytes() == stdout.replace(
            token, "[REDACTED]"
        ).encode()
        assert (root / failed["stderr"]["file"]).read_bytes() == stderr.replace(
            token, "[REDACTED]"
        ).encode()
    else:
        assert b"FULL FAILURE DIAGNOSTIC [REDACTED]" in data
    assert result["streams"]["daemon"]["status"] == "captured"
    assert json.loads((root / "metadata.json").read_text()) == result
    assert all(f.stat().st_mode & 0o777 == 0o600 for f in root.iterdir())
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "field,value",
    [
        ("instance", True),
        ("instance", "789"),
        ("instance", "789 --url evil"),
        ("instance", 0),
        ("instance", None),
        ("label", "unrelated"),
        ("start_date", None),
        ("start_date", True),
        ("start_date", float("nan")),
    ],
)
def test_invalid_binding_rejected_before_inventory_or_credentials(
    tmp_path, fake_only, field, value
):
    m = adapter()
    r = record()
    r[field] = value
    p = Inventory()
    with pytest.raises(ValueError, match="binding"):
        m.capture_provider_logs(r, tmp_path / "logs", provider=p)
    assert p.calls == []
    assert not (tmp_path / "logs").exists()


@pytest.mark.parametrize("unsafe", ["symlink", "public", "ancestor-symlink"])
def test_unsafe_artifact_directory_rejected_before_provider_access(tmp_path, fake_only, unsafe):
    m = adapter()
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    if unsafe == "symlink":
        directory = tmp_path / "logs"
        directory.symlink_to(target, target_is_directory=True)
    elif unsafe == "ancestor-symlink":
        link = tmp_path / "link"
        link.symlink_to(target, target_is_directory=True)
        directory = link / "logs"
    else:
        directory = target
        directory.chmod(0o755)
    p = Inventory()
    with pytest.raises(ValueError, match="directory"):
        m.capture_provider_logs(record(), directory, provider=p)
    assert p.calls == []
    assert list(target.iterdir()) == []


@pytest.mark.parametrize("secrets", ["FAKE_not_a_sequence", [123], {"api_key": "FAKE_value"}])
def test_invalid_secret_collection_rejected_before_io(tmp_path, fake_only, secrets):
    m = adapter()
    p = Inventory()
    with pytest.raises(ValueError, match="known_secrets"):
        m.capture_provider_logs(record(), tmp_path / "logs", secrets, provider=p)
    assert p.calls == []
    assert not (tmp_path / "logs").exists()


def test_bytes_private_key_lines_and_escaped_form_are_redacted(tmp_path, monkeypatch, fake_only):
    m = adapter()
    key = b"-----BEGIN PRIVATE KEY-----\nFAKE_bytes_key_line\n-----END PRIVATE KEY-----\n"
    raw = b"FAKE_bytes_key_line\n" + json.dumps(key.decode())[1:-1].encode()
    monkeypatch.setattr(
        m.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, raw, b"")
    )
    result = m.capture_provider_logs(record(), tmp_path / "logs", [key], provider=Inventory())
    for stream in result["streams"].values():
        assert (
            b"FAKE_bytes_key_line"
            not in (Path(result["directory"]) / stream["stdout"]["file"]).read_bytes()
        )

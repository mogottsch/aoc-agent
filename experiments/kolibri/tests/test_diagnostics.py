"""FAKE-ONLY offline diagnostics regression; no external services or inference."""

import importlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run as preparation

BASE = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_fake_only_partial_failure_retains_sanitized_cause_and_full_traceback(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(preparation, "EXPERIMENT", tmp_path)
    monkeypatch.setenv("KOLIBRI_API_KEY", "FAKE_ONLY_DISPOSABLE_SECRET")
    closed = []

    async def close():
        closed.append(True)

    monkeypatch.setattr(
        preparation, "build_model", lambda _: SimpleNamespace(client=SimpleNamespace(close=close))
    )

    class FakeHTTPFailure(RuntimeError):
        status_code = 503
        body = {"error": "FAKE_ONLY provider unavailable", "token": "FAKE_ONLY_DISPOSABLE_SECRET"}

    async def fake_day(model, year, day, path):
        if day == 3:
            try:
                raise FakeHTTPFailure("FAKE_ONLY Bearer unknown-secret")
            except FakeHTTPFailure as cause:
                raise RuntimeError(
                    "FAKE_ONLY_DISPOSABLE_SECRET failed after partial rows"
                ) from cause
        with path.open("a") as file:
            file.write(json.dumps({"year": year, "day": day, "error": None}) + "\n")

    monkeypatch.setattr(preparation, "run_day", fake_day)
    config = preparation.load_experiment(BASE / "config.yaml")
    with pytest.raises(RuntimeError, match="failed after partial rows"):
        await preparation.run_experiment(config, "fake-only-partial", pins={"fake_only": True})
    directory = tmp_path / "runs/fake-only-partial"
    assert len((directory / "results.jsonl").read_text().splitlines()) == 2
    failure = json.loads((directory / "failure.json").read_text())
    assert failure["year"] == 2022 and failure["day"] == 3
    assert failure["exception"]["type"] == "RuntimeError"
    assert "failed after partial rows" in failure["exception"]["message"]
    assert failure["exception"]["cause"]["status_code"] == 503
    assert "provider unavailable" in failure["exception"]["cause"]["body"]
    traceback = (directory / "failure-traceback.txt").read_text()
    assert "direct cause" in traceback and "fake_day" in traceback
    assert "FakeHTTPFailure" in traceback and "RuntimeError" in traceback
    combined = json.dumps(failure) + traceback
    assert "FAKE_ONLY_DISPOSABLE_SECRET" not in combined and "unknown-secret" not in combined
    assert closed == [True]
    assert (directory / "failure.json").stat().st_mode & 0o777 == 0o600
    assert json.loads((directory / "manifest.json").read_text())["status"] == "failed"
    controller = importlib.import_module("real_controller")
    work = tmp_path / "work"
    work.mkdir()
    label = "hermes-kolibri-" + "a" * 32
    exported = tmp_path / "exported"
    exported.mkdir()

    class FakeOnlyKube:
        def call(self, *args, **kwargs):
            script = (
                args[-1]
                .replace("/work/repo/experiments/kolibri/runs/" + label, str(directory))
                .replace(
                    "pathlib.Path('/work/repo/experiments/kolibri/runs')/" + repr(label),
                    "pathlib.Path(" + repr(str(directory)) + ")",
                )
                .replace("/work/", str(work) + "/")
            )
            return subprocess.run(
                [sys.executable, "-c", script], capture_output=True, text=True, check=True
            ).stdout

    (work / "runner-status.json").write_text('{"status":"failed","exit_code":1}')
    # Exceed the old 16 MiB bound; all file segments must survive export.
    large_log = "FAKE_ONLY full log\n" + "x" * (17 * 1024 * 1024)
    (work / "runner-stderr.log").write_text(large_log)
    progress = controller.collect(
        FakeOnlyKube(), {"label": label, "namespace": "fake-only"}, "fake-only", exported
    )
    assert progress["saved_rows"] == 2 and progress["runner"] == "failed"
    assert (exported / "runner-stderr.log").read_text() == large_log
    assert (exported / "failure.json").read_bytes() == (directory / "failure.json").read_bytes()
    assert (exported / "failure-traceback.txt").read_bytes() == (
        directory / "failure-traceback.txt"
    ).read_bytes()


def test_fake_only_child_logs_survive_nonzero_exit_without_console_leak(tmp_path, capsys):
    runner = importlib.import_module("real_runner")
    script = (
        "import sys; print('FAKE_ONLY first row'); "
        "print('Bearer FAKE_ONLY_UNKNOWN_AUTH', file=sys.stderr); "
        "print('FAKE_ONLY_TOKEN', file=sys.stderr); "
        "print('x'*300000, file=sys.stderr); sys.exit(7)"
    )
    code = runner.run_logged(
        [sys.executable, "-c", script],
        tmp_path,
        {"PATH": "/usr/bin", "KOLIBRI_API_KEY": "FAKE_ONLY_TOKEN"},
        tmp_path,
    )
    assert code == 7
    assert "first row" in (tmp_path / "runner-stdout.log").read_text()
    stderr = (tmp_path / "runner-stderr.log").read_text()
    assert "FAKE_ONLY_UNKNOWN_AUTH" not in stderr and "FAKE_ONLY_TOKEN" not in stderr
    assert "x" * 300000 in stderr
    assert capsys.readouterr().out == "" and capsys.readouterr().err == ""
    assert (tmp_path / "runner-stderr.log").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("broken", [False, True])
def test_fake_only_cleanup_retains_namespace_on_export_failure(tmp_path, monkeypatch, broken):
    controller = importlib.import_module("real_controller")
    events = []
    record = {"label": "hermes-kolibri-" + "a" * 32, "namespace": "fake-only"}
    (tmp_path / "namespace-attempted").write_text("fake-only")

    def export(*args, **kwargs):
        events.append("export")
        if broken:
            raise OSError("FAKE_ONLY export disk failure")

    monkeypatch.setattr(controller, "export_namespace", export)
    monkeypatch.setattr(controller, "cleanup_namespace", lambda *a: events.append("delete") or True)
    assert controller.finish_namespace(object(), record, "fake-only", tmp_path) is (not broken)
    assert events == (["export"] if broken else ["export", "delete"])
    if broken:
        assert "export disk failure" in (tmp_path / "export-failure-traceback.txt").read_text()
        assert json.loads((tmp_path / "namespace-cleanup.json").read_text())["retained"]


def test_fake_only_namespace_export_preserves_init_proxy_previous_and_oom(tmp_path, monkeypatch):
    controller = importlib.import_module("real_controller")
    calls = []
    record = {"label": "hermes-kolibri-" + "a" * 32, "namespace": "fake-only"}
    pod = {
        "metadata": {"name": "fake-only", "uid": "fake-only"},
        "status": {
            "initContainerStatuses": [
                {
                    "name": "install-public-deps",
                    "state": {"terminated": {"exitCode": 0, "reason": "Completed"}},
                }
            ],
            "containerStatuses": [
                {"name": "runner", "state": {"running": {}}, "restartCount": 0},
                {
                    "name": "tls-proxy",
                    "state": {"running": {}},
                    "restartCount": 1,
                    "lastState": {"terminated": {"reason": "OOMKilled", "exitCode": 137}},
                },
            ],
        },
    }

    class FakeOnlyKube:
        def call(self, *args, **kwargs):
            calls.append(args)
            if "logs" in args:
                return (
                    "FAKE_ONLY complete log Bearer FAKE_ONLY_AUTH FAKE_ONLY_TOKEN\n" + "x" * 300000
                )
            return json.dumps({"items": [pod] if "pods" in args else []})

    monkeypatch.setattr(controller, "collect", lambda *a, **kw: {"runner": "failed"})
    controller.export_namespace(
        FakeOnlyKube(), record, None, tmp_path, secrets=("FAKE_ONLY_TOKEN",)
    )
    assert len([a for a in calls if "logs" in a]) == 4
    assert any("--previous" in a for a in calls)
    assert "OOMKilled" in (tmp_path / "kubernetes-pods.json").read_text()
    for file in tmp_path.glob("kubernetes-*.log"):
        text = file.read_text()
        assert "FAKE_ONLY_AUTH" not in text and "FAKE_ONLY_TOKEN" not in text
        assert "x" * 300000 in text


def test_explicit_transport_token_is_redacted_from_private_failure(tmp_path):
    diagnostics = importlib.import_module("diagnostics")
    error = RuntimeError("FAKE_ONLY_EXPLICIT_TRANSPORT provider cause")
    diagnostics.save_failure(tmp_path, error, secrets=("FAKE_ONLY_EXPLICIT_TRANSPORT",))
    assert "provider cause" in (tmp_path / "failure.json").read_text()
    assert "FAKE_ONLY_EXPLICIT_TRANSPORT" not in (tmp_path / "failure.json").read_text()


def test_fake_only_kube_failure_preserves_private_command_cause(tmp_path, monkeypatch, capsys):
    controller = importlib.import_module("real_controller")
    diagnostics = importlib.import_module("diagnostics")
    monkeypatch.setattr(
        controller.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=1, stdout="", stderr="FAKE_ONLY server rejected log export Bearer fake-auth"
        ),
    )
    with pytest.raises(RuntimeError) as failure:
        controller.Kube().call("logs", "fake-only")
    diagnostics.save_failure(tmp_path, failure.value)
    evidence = (tmp_path / "failure.json").read_text()
    assert "server rejected log export" in evidence and "fake-auth" not in evidence
    assert capsys.readouterr().out == ""


def test_streaming_redaction_preserves_non_newline_progress_and_split_tokens():
    diagnostics = importlib.import_module("diagnostics")
    stream = diagnostics.RedactingStream(("FAKE_ONLY_SPLIT_TOKEN",))
    output = stream.feed("x" * 100000)
    assert len(output) > 99000  # survives a runner kill before a newline arrives
    output += stream.feed(" FAKE_ONLY_SPLIT_")
    output += stream.feed("TOKEN Bear")
    output += stream.feed("er FAKE_ONLY_BEARER")
    output += stream.feed("_TOKEN\nlast line", final=True)
    assert "FAKE_ONLY_SPLIT_TOKEN" not in output
    assert "FAKE_ONLY_BEARER_TOKEN" not in output
    assert output.count("x") == 100000 and output.endswith("last line")


def test_streaming_redaction_handles_no_known_credentials(monkeypatch):
    diagnostics = importlib.import_module("diagnostics")
    for name in list(diagnostics.os.environ):
        monkeypatch.delenv(name)
    stream = diagnostics.RedactingStream()
    assert stream.feed("FAKE_ONLY ordinary output", final=True) == "FAKE_ONLY ordinary output"


def test_streaming_redaction_handles_long_bearer_whitespace():
    diagnostics = importlib.import_module("diagnostics")
    stream = diagnostics.RedactingStream()
    text = stream.feed("Bearer " + " " * 1000)
    text += stream.feed("FAKE_ONLY_UNKNOWN_CREDENTIAL done", final=True)
    assert "FAKE_ONLY_UNKNOWN_CREDENTIAL" not in text and text.endswith("done")


def test_export_failure_recording_fault_cannot_block_independent_gpu_cleanup(tmp_path, monkeypatch):
    controller = importlib.import_module("real_controller")
    record = {"label": "hermes-kolibri-" + "a" * 32, "namespace": "fake-only"}
    (tmp_path / "namespace-attempted").write_text("fake-only")

    def fail_export(*args, **kwargs):
        raise OSError("FAKE_ONLY export failed")

    def fail_diagnostic(*args, **kwargs):
        raise ValueError("FAKE_ONLY unsafe diagnostic path")

    monkeypatch.setattr(controller, "export_namespace", fail_export)
    monkeypatch.setattr(controller, "save_failure", fail_diagnostic)
    assert controller.finish_namespace(object(), record, "fake-only", tmp_path) is False


def test_known_multiline_secret_is_redacted_inside_serialized_provider_body(tmp_path):
    diagnostics = importlib.import_module("diagnostics")
    secret = "FAKE_ONLY multiline\nprivate credential"  # noqa: S105 - synthetic redaction fixture

    class FakeOnlyProviderError(RuntimeError):
        body: dict

    error = FakeOnlyProviderError("FAKE_ONLY provider body")
    error.body = {"credential": secret, "diagnostic": "keep complete provider error"}
    diagnostics.save_failure(tmp_path, error, secrets=(secret,))
    text = (tmp_path / "failure.json").read_text()
    assert "private credential" not in text and "keep complete provider error" in text


@pytest.mark.asyncio
async def test_fake_only_close_error_retains_original_day_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(preparation, "EXPERIMENT", tmp_path)

    async def close():
        raise OSError("FAKE_ONLY close failed")

    monkeypatch.setattr(
        preparation, "build_model", lambda _: SimpleNamespace(client=SimpleNamespace(close=close))
    )

    async def fake_day(*args):
        raise RuntimeError("FAKE_ONLY original day failure")

    monkeypatch.setattr(preparation, "run_day", fake_day)
    config = preparation.load_experiment(BASE / "config.yaml")
    with pytest.raises(RuntimeError, match="original day failure"):
        await preparation.run_experiment(config, "fake-only-close", pins={"fake_only": True})
    directory = tmp_path / "runs/fake-only-close"
    assert "close failed" in (directory / "client-close-failure.json").read_text()
    assert "original day failure" in (directory / "failure.json").read_text()


def test_streaming_redaction_handles_encoded_credential_across_chunks():
    diagnostics = importlib.import_module("diagnostics")
    secret = "FAKE_ONLY\n" * 10 + "credential"  # noqa: S105 - synthetic redaction fixture
    encoded = json.dumps(secret)[1:-1]
    stream = diagnostics.RedactingStream((secret,))
    output = stream.feed(encoded[:-1])
    output += stream.feed(encoded[-1:] + " complete", final=True)
    assert "credential" not in output and output.endswith("complete")


def test_exception_group_traceback_does_not_silently_elide_failures(tmp_path):
    diagnostics = importlib.import_module("diagnostics")
    errors = [RuntimeError(f"FAKE_ONLY grouped failure {i}") for i in range(30)]
    error = ExceptionGroup("FAKE_ONLY grouped diagnostics", errors)
    diagnostics.save_failure(tmp_path, error)
    text = (tmp_path / "failure-traceback.txt").read_text()
    for i in range(30):
        assert f"FAKE_ONLY grouped failure {i}\n" in text

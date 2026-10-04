"""Offline regression: recovery attaches exact existing lease and never rents."""

import importlib
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.mark.parametrize("export_ok", [True, False])
@pytest.mark.parametrize(
    "benchmark_failed",
    [
        False,
        True,
        "complete-errors",
        "complete-pins",
        "complete-config",
        "complete-partial-manifest",
        "complete-duplicate",
        "complete-provenance",
        "collect-error",
        "collect-timeout",
        "collect-timeout-expiry",
        "collect-timeout-credit",
        "collect-timeout-rate",
        "collect-subprocess-error",
        "collect-replay-race",
        "collect-replay-changing",
        "collect-replay-transition",
        "collect-replay-pending",
        "collect-replay-persistent",
        "collect-replay-terminal",
        "collect-replay-unsafe",
        "collect-replay-credit",
        "collect-replay-rate",
        "collect-replay-expiry",
    ],
)
@pytest.mark.parametrize("retained", [False, True])
def test_resume_existing_instance_preserves_deadline_and_never_launches(
    monkeypatch,
    tmp_path,
    export_ok,
    benchmark_failed,
    retained,
    *,
    replacement=False,
    expected_bounded_cleanup=False,
):
    m = importlib.import_module("real_resume")
    life = importlib.import_module("real_lifecycle")
    from test_real_lifecycle import lease, row

    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    r = lease()
    r.update(
        created=time.time() - 10,
        deadline=time.time() + 1000,
        instance=789,
        start_date=time.time() - 5,
        status="debug-retained" if retained else "launching",
    )
    path = root / (r["label"] + ".json")
    life.store(path, r)
    directory = root / r["label"]
    directory.mkdir(mode=0o700)
    if retained:
        (directory / "namespace-attempted").write_text(r["namespace"])
        (directory / "debug-hold.json").write_text(json.dumps({"pod": "pod"}))
    (directory / "server.crt").write_text("CERT")
    (directory / "server.key").write_text("KEY")
    config = {"api_key": "a" * 64, "cert": "CERT", "key": "KEY"}
    target = directory / "resume-transport.json"
    target.write_text(json.dumps(config))
    target.chmod(0o600)
    monkeypatch.setattr(m, "STATE", root)
    monkeypatch.setattr(m, "locked", lambda: life.locked(root))
    controller = importlib.import_module("real_controller")
    monkeypatch.setattr(controller, "locked", lambda: life.locked(root))
    monkeypatch.setattr(controller, "export_namespace", lambda *a, **k: None)
    calls = []
    collection_count = 0
    replay_race = isinstance(benchmark_failed, str) and benchmark_failed.startswith(
        "collect-replay"
    )
    recovered_race = benchmark_failed in {
        "collect-replay-race",
        "collect-replay-changing",
        "collect-replay-transition",
        "collect-replay-pending",
    }
    monkeypatch.setattr(m.time, "sleep", lambda _: None)

    class Provider:
        rows = [row(r, start_date=r["start_date"])]
        credit = 9.65

        def call(self, command, *args):
            calls.append(command)
            if command == "list":
                return self.rows
            if command == "balance":
                return {
                    "id": 639482,
                    "username": "moritz-hermes-bot",
                    "is_team": True,
                    "credit": self.credit,
                }
            if command == "status":
                return {
                    "actual_status": "running",
                    "public_ipaddr": "8.8.8.8",
                    "ports": {
                        "8000/tcp": [
                            {"HostIp": "0.0.0.0", "HostPort": "23456"},
                            {"HostIp": "::", "HostPort": "23456"},
                        ]
                    },
                }
            if command == "destroy":
                self.rows = []
                return {"success": True}
            raise AssertionError("unexpected paid or other call: " + command)

    provider = Provider()
    monkeypatch.setattr(m, "Vast", lambda: provider)
    monkeypatch.setattr(m, "finish_provider_logs", lambda *a: True)  # Fake-only provider logs.

    class Kube:
        def get(self, namespace, kind, name):
            if kind == "namespace":
                return {"metadata": {"labels": {"kolibri-real": r["label"]}}}
            raise AssertionError(kind)

        def call(self, *args, **kwargs):
            if "pods" in args:
                return json.dumps(
                    {
                        "items": [
                            {
                                "metadata": {"name": "pod"},
                                "status": {
                                    "containerStatuses": [
                                        {"name": "runner", "state": {"running": {}}}
                                    ]
                                },
                            }
                        ]
                    }
                )
            assert "exec" in args
            script = args[-1]
            if "request_replay" in script:
                calls.append("replay-same-pod")
                return "2"
            if "root=pathlib.Path('/work/attempts/')" in script:
                return "[]"
            if "files={}" in script:
                calls.append("old-inventory")
                return json.dumps({"failure.json": {"size": 1, "sha256": "unused"}})
            if "s=f.open('rb')" in script:
                calls.append("archived-file-disappeared")
                raise controller.KubeError(
                    "Kubernetes read-or-exec failed; private diagnostic body retained",
                    "FileNotFoundError: [Errno 2] No such file or directory: "
                    "'/work/repo/experiments/kolibri/runs/" + r["label"] + "/failure.json'",
                )
            calls.append("runner-probe")
            if benchmark_failed == "collect-replay-terminal":
                return json.dumps({"status": "complete", "attempt": 2 if retained else 1})
            if retained and benchmark_failed == "collect-replay-transition":
                return "{}"
            if retained and benchmark_failed == "collect-replay-pending":
                return json.dumps({"status": "failed", "attempt": 1})
            return json.dumps({"status": "running", "attempt": 2 if retained else 1})

    monkeypatch.setattr(m, "Kube", Kube)
    monkeypatch.setattr(
        m, "request", lambda *a, **k: (200, b'{"data":[{"id":"Aleph-Alpha/Kolibri-1"}]}')
    )

    def deploy(k, record, c, d, **kwargs):
        assert not retained, "must not replace retained namespace or pod"
        assert "key" not in c
        assert record["deadline"] == r["deadline"]
        return "pod"

    monkeypatch.setattr(m, "deploy", deploy)

    def finish(*args, **kwargs):
        calls.append("export-before-cleanup")
        return export_ok

    monkeypatch.setattr(m, "finish_namespace", finish)

    def collect(*args, **kwargs):
        nonlocal collection_count
        from test_real_controller import write_completed_checkpoint

        write_completed_checkpoint(directory, benchmark_failed)
        collection_count += 1
        if replay_race:
            assert "destroy" not in calls, "export race must not trigger forced GPU deletion"
            assert life.read(path)["status"] == "running"
            if benchmark_failed == "collect-replay-credit":
                provider.credit = 0
            elif benchmark_failed == "collect-replay-rate":
                provider.rows[0]["dph_total"] = 4.5
            elif benchmark_failed == "collect-replay-expiry":
                monkeypatch.setattr(m.time, "time", lambda: r["deadline"])
            if collection_count == 1 or benchmark_failed == "collect-replay-persistent":
                if benchmark_failed == "collect-replay-changing":
                    raise ValueError("artifact changed during export; retry before cleanup")
                if benchmark_failed == "collect-replay-unsafe":
                    raise ValueError("invalid artifact inventory")
                return controller.collect(*args, **kwargs)
            if collection_count == 2 and retained:
                return {"runner": "failed", "saved_rows": 4, "attempt": 1}
            if collection_count == (3 if retained else 2):
                return {"runner": "running", "saved_rows": 4, "attempt": 2 if retained else 1}
            return {"runner": "complete", "saved_rows": 50, "attempt": 2 if retained else 1}
        if benchmark_failed == "collect-error":
            raise RuntimeError("temporary evidence export failure after isolation gate")
        if isinstance(benchmark_failed, str) and benchmark_failed.startswith("collect-timeout"):
            if benchmark_failed == "collect-timeout-expiry":
                monkeypatch.setattr(m.time, "time", lambda: r["deadline"])
            elif benchmark_failed == "collect-timeout-credit":
                provider.credit = 0
            elif benchmark_failed == "collect-timeout-rate":
                provider.rows[0]["dph_total"] = 4.5
            raise subprocess.TimeoutExpired(["kubectl", "exec", "pod"], 90)
        if benchmark_failed == "collect-subprocess-error":
            raise subprocess.CalledProcessError(1, ["kubectl", "exec", "pod"])
        return {
            "runner": "complete"
            if not benchmark_failed or str(benchmark_failed).startswith("complete-")
            else "failed",
            "saved_rows": 50
            if not benchmark_failed or str(benchmark_failed).startswith("complete-")
            else 4,
            "error_rows": 0,
            "attempt": 2 if retained else 1,
        }

    monkeypatch.setattr(m, "collect", collect)
    assert m.run_existing(
        path, rerun_failed=retained and not replacement, replace_dead_runner=replacement
    ) == (0 if export_ok and (not benchmark_failed or recovered_race) else 2)
    if recovered_race:
        if benchmark_failed != "collect-replay-changing":
            assert calls.count("old-inventory") == calls.count("archived-file-disappeared") == 1
        assert collection_count == (4 if retained else 3)
        assert not (directory / "controller-status.json").exists()
    elif replay_race:
        assert collection_count == (4 if benchmark_failed == "collect-replay-persistent" else 1)
    assert calls.count("replay-same-pod") == int(retained and not replacement)
    durable = life.read(path)
    assert (durable["instance"], durable["start_date"], durable["deadline"]) == (
        r["instance"],
        r["start_date"],
        r["deadline"],
    )
    bounded_cleanup = expected_bounded_cleanup or benchmark_failed in {
        "collect-timeout-expiry",
        "collect-timeout-credit",
        "collect-timeout-rate",
        "collect-replay-credit",
        "collect-replay-rate",
        "collect-replay-expiry",
    }
    if benchmark_failed and not recovered_race:
        if isinstance(benchmark_failed, str) and benchmark_failed.startswith("collect-timeout"):
            failure = json.loads((directory / "controller-status.json").read_text())
            assert failure["error_type"] == "TimeoutExpired"
        if bounded_cleanup:
            assert durable["status"] == "destroyed"
            assert "launch" not in calls and calls.count("destroy") == 1
            assert calls.count("export-before-cleanup") == 1
            summary = json.loads((directory / "cleanup-summary.json").read_text())
            assert summary["verified"] == export_ok
            return
        assert life.read(path)["status"] == "debug-retained"
        assert life.read(path)["deadline"] == r["deadline"]
        assert "destroy" not in calls and "export-before-cleanup" not in calls
        assert provider.rows == [row(r, start_date=r["start_date"])]
        hold = json.loads((directory / "debug-hold.json").read_text())
        assert hold["namespace"] == r["namespace"] and hold["pod"] == "pod"
        assert hold["deadline"] == r["deadline"]
        return
    assert "launch" not in calls and calls.count("destroy") == 1
    assert life.read(path)["status"] == "destroyed"
    assert life.read(path)["deadline"] == r["deadline"]
    assert calls.index("export-before-cleanup") < calls.index("destroy")


def test_recovery_delivers_frozen_checkpoint_not_mutable_original(monkeypatch, tmp_path):
    from test_checkpoint import row, seed

    controller = importlib.import_module("real_controller")
    resume = importlib.import_module("real_resume")
    source = seed(tmp_path / "original", [row(day=d) for d in range(1, 14)])
    expected = tuple(
        (name, (source / name).read_bytes()) for name in ("results.jsonl", "manifest.json")
    )
    observed = []

    class ObservePatch(pytest.MonkeyPatch):
        def setattr(self, target, name, value, *args, **kwargs):
            if target is resume and name == "Vast":
                factory = value

                def stage():
                    lease = next((tmp_path / "state").glob("hermes-kolibri-*.json"))
                    controller.prepare_checkpoint(source, lease.with_suffix(""))
                    (source / "results.jsonl").write_text("mutated original")
                    return factory()

                value = stage
            elif target is resume and name == "deploy":
                deploy = value

                def observe(kube, record, config, directory, **options):
                    observed.append(options.get("checkpoint"))
                    return deploy(kube, record, config, directory, **options)

                value = observe
            return super().setattr(target, name, value, *args, **kwargs)

    with ObservePatch.context() as patcher:
        test_resume_existing_instance_preserves_deadline_and_never_launches(
            patcher, tmp_path, True, False, False
        )
    assert observed == [expected]


@pytest.mark.parametrize(
    "tamper",
    ["results", "manifest", "metadata", "metadata-list", "metadata-provenance-list", "symlink"],
)
def test_recovery_rejects_tampered_frozen_checkpoint(tmp_path, tamper):
    from test_checkpoint import row, seed

    controller = importlib.import_module("real_controller")
    source = seed(tmp_path / "original", [row(day=d) for d in range(1, 14)])
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    controller.prepare_checkpoint(source, directory)
    if tamper == "results":
        (directory / "checkpoint-source/results.jsonl").write_text(json.dumps(row()) + "\n")
    elif tamper == "manifest":
        target = directory / "checkpoint-source/manifest.json"
        target.write_text(target.read_text() + "\n")
    elif tamper == "metadata":
        target = directory / "checkpoint-source.json"
        metadata = json.loads(target.read_text())
        metadata["provenance"]["saved_rows"] = 1
        target.write_text(json.dumps(metadata))
    elif tamper == "metadata-list":
        (directory / "checkpoint-source.json").write_text("[]")
    elif tamper == "metadata-provenance-list":
        target = directory / "checkpoint-source.json"
        metadata = json.loads(target.read_text())
        metadata["provenance"] = []
        target.write_text(json.dumps(metadata))
    else:
        target = directory / "checkpoint-source/results.jsonl"
        target.unlink()
        target.symlink_to(source / "results.jsonl")
    with pytest.raises(ValueError):
        controller.recover_checkpoint(directory)


def test_operator_stop_ends_retained_lease_without_transport_or_balance(monkeypatch, tmp_path):
    m = importlib.import_module("real_resume")
    life = importlib.import_module("real_lifecycle")
    from test_real_lifecycle import BalanceUnavailable, lease, row

    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    r = lease()
    r.update(instance=789, start_date=1010.0, status="debug-retained")
    path = root / (r["label"] + ".json")
    life.store(path, r)
    directory = root / r["label"]
    directory.mkdir(mode=0o700)
    p = BalanceUnavailable([row(r)])
    monkeypatch.setattr(m, "STATE", root)
    monkeypatch.setattr(m, "locked", lambda: life.locked(root))
    monkeypatch.setattr(m, "Vast", lambda: p)
    monkeypatch.setattr(m, "Kube", lambda: object())
    calls = []
    monkeypatch.setattr(m, "finish_namespace", lambda *a, **k: calls.append("cleanup") or True)
    assert m.stop_existing(path) == 0
    assert life.read(path)["status"] == "destroyed"
    assert life.read(path)["deadline"] == r["deadline"]
    assert p.deleted == [789] and p.balance_calls == 0 and calls == ["cleanup"]


def test_retained_resume_without_explicit_replay_does_not_touch_provider_or_cleanup(
    monkeypatch, tmp_path
):
    m = importlib.import_module("real_resume")
    life = importlib.import_module("real_lifecycle")
    from test_real_lifecycle import lease

    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    record = lease()
    record.update(instance=789, start_date=1010.0, status="debug-retained")
    path = root / (record["label"] + ".json")
    life.store(path, record)
    monkeypatch.setattr(m, "STATE", root)
    monkeypatch.setattr(m, "locked", lambda: life.locked(root))

    def no_provider():
        pytest.fail("implicit replay must be rejected before any external calls")

    monkeypatch.setattr(m, "Vast", no_provider)
    with pytest.raises(ValueError, match="explicit"):
        m.run_existing(path)
    assert life.read(path) == record

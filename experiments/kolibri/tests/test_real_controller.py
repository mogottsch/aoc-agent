"""Offline real-controller recipe and public bundle tests."""

import importlib
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def write_completed_checkpoint(directory, fault=None):
    """Real schema/pins fixture; collector reports remain independently untrusted."""
    from test_checkpoint import pins, row, settings

    rows = [row(year=year, day=day) for year in (2022, 2023) for day in range(1, 26)]
    manifest = {"status": "complete", "config": settings().model_dump(mode="json"), "pins": pins()}
    if fault == "complete-errors":
        for result in rows:
            result["error"] = "deliberate offline error"
    elif fault == "complete-pins":
        manifest["pins"]["plugin_commit"] = "0" * 40
    elif fault == "complete-config":
        manifest["config"]["benchmark"]["models"][0]["disable_tool_choice"] = True
    elif fault == "complete-partial-manifest":
        manifest["status"] = "running"
    elif fault == "complete-duplicate":
        rows[-1] = dict(rows[0])
    elif fault == "complete-provenance":
        manifest["seed"] = {"saved_rows": 13}
    (directory / "manifest.json").write_text(json.dumps(manifest))
    (directory / "results.jsonl").write_text("".join(json.dumps(result) + "\n" for result in rows))


@pytest.mark.parametrize(
    "fault",
    [
        "complete-errors",
        "complete-pins",
        "complete-config",
        "complete-partial-manifest",
        "complete-duplicate",
        "complete-provenance",
        "missing-manifest",
        None,
    ],
)
def test_collect_fake_complete_error_rows_preserves_progress_but_rejects_success(tmp_path, fault):
    import subprocess

    m = importlib.import_module("real_controller")
    work = tmp_path / "work"
    work.mkdir()
    record = {"namespace": "offline", "label": "hermes-kolibri-" + "f" * 32, "status": "running"}
    benchmark = work / "repo/experiments/kolibri/runs" / record["label"]
    benchmark.mkdir(parents=True)
    write_completed_checkpoint(benchmark, fault)
    (work / "runner-status.json").write_text('{"status":"complete","attempt":1}')
    output = tmp_path / "export"
    output.mkdir(mode=0o700)
    if fault == "missing-manifest":
        write_completed_checkpoint(output)
        (benchmark / "manifest.json").unlink()

    class Kube:
        def call(self, *args, **kwargs):
            return subprocess.run(
                [sys.executable, "-I", "-c", args[-1].replace("/work/", str(work) + "/")],
                check=True,
                capture_output=True,
                text=True,
            ).stdout

    progress = m.collect(Kube(), record, "pod", output)
    assert progress["saved_rows"] == 50
    assert progress["error_rows"] == (50 if fault == "complete-errors" else 0)
    assert progress.get("completion_validated") is (fault is None)
    assert json.loads((output / "progress.json").read_text()) == progress
    assert (output / "results.jsonl").read_bytes() == (benchmark / "results.jsonl").read_bytes()


def test_real_recipe_has_no_credentialed_runtime_and_narrow_tls_egress():
    m = importlib.import_module("real_controller")
    config = {"host": "8.8.8.8", "port": 23456, "cert": "PUBLIC_CERT", "api_key": "DISPOSABLE"}
    objects = m.resources(
        "kolibri-real-" + "a" * 12, "hermes-kolibri-" + "a" * 32, config, ["151.101.0.223"]
    )
    job = next(o for o in objects if o["kind"] == "Job")
    pod = job["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["securityContext"]["runAsNonRoot"]
    assert all("hostPath" not in v for v in pod["volumes"])
    assert job["spec"]["activeDeadlineSeconds"] == 5400
    runner, proxy = pod["containers"]
    installer = pod["initContainers"][0]
    assert runner["resources"] == {
        "requests": {"cpu": "25m", "memory": "512Mi", "ephemeral-storage": "64Mi"},
        "limits": {"cpu": "1", "memory": "8Gi", "ephemeral-storage": "2Gi"},
    }
    assert proxy["resources"] == {
        "requests": {"cpu": "25m", "memory": "32Mi", "ephemeral-storage": "64Mi"},
        "limits": {"cpu": "100m", "memory": "128Mi", "ephemeral-storage": "128Mi"},
    }
    assert installer["resources"] == {
        "requests": {"cpu": "25m", "memory": "256Mi", "ephemeral-storage": "64Mi"},
        "limits": {"cpu": "1", "memory": "1Gi", "ephemeral-storage": "2Gi"},
    }
    quota = next(o for o in objects if o["kind"] == "ResourceQuota")
    assert quota["spec"]["hard"] == {
        "limits.cpu": "3",
        "limits.memory": "9Gi",
        "limits.ephemeral-storage": "6Gi",
        "pods": "1",
        "count/jobs.batch": "1",
        "services": "0",
        "persistentvolumeclaims": "0",
        "count/secrets": "1",
    }
    for c in pod["containers"] + pod["initContainers"]:
        assert c["securityContext"]["readOnlyRootFilesystem"]
        assert c["securityContext"]["capabilities"]["drop"] == ["ALL"]
        assert not any(
            e["name"] in {"VAST_API_KEY", "HF_TOKEN", "API_KEY", "KUBECONFIG"}
            for e in c.get("env", [])
        )
    text = json.dumps(objects)
    assert "/opt/data" not in text and "/opt/kube" not in text
    tls = next(o for o in objects if o["metadata"]["name"] == "serving-tls")
    assert tls["spec"]["egress"][0]["to"] == [{"ipBlock": {"cidr": "8.8.8.8/32"}}]
    assert tls["spec"]["egress"][0]["ports"] == [{"port": 23456, "protocol": "TCP"}]


def test_public_bundle_is_allowlisted_not_checkout():
    m = importlib.import_module("real_controller")
    blob = m.bundle_archive()
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        names = tar.getnames()
        assert "experiments/kolibri/run.py" in names
        assert "experiments/kolibri/verify_pins.py" in names
        assert "experiments/kolibri/checkpoint.py" in names
        assert "experiments/kolibri/memory_telemetry.py" in names
        assert "src/aoc_agent/__init__.py" in names
        from aoc_agent.adapters.aoc.parser import extract_answer_from_html

        for year in (2022, 2023):
            for day in range(1, 26):
                for part in (1, 2) if day != 25 else (1,):
                    name = f"cache/{year}/day_{day}.part{part}_solved.html"
                    member = tar.extractfile(name)
                    assert member is not None
                    clean = member.read().decode()
                    original = (m.ROOT / name).read_text()
                    assert extract_answer_from_html(clean, part) == extract_answer_from_html(
                        original, part
                    )
        assert len([n for n in names if n.endswith(".input.txt")]) == 50
        assert "experiments/kolibri/vast_delete.py" not in names
        assert not any(
            ".env" in n or "results/" in n or ".git/" in n or "real_lifecycle" in n for n in names
        )
        html = tar.extractfile("cache/2022/day_1.unsolved.html").read().decode()
        assert "<article" in html and "<nav" not in html
    assert len(blob) < 700000


def test_runner_rejects_inference_without_isolation_release(tmp_path):
    import pytest

    runner = importlib.import_module("real_runner")
    with pytest.raises(ValueError):
        runner.command({"action": "shell", "run_id": "bad"})
    assert (
        runner.command({"action": "preflight", "run_id": "hermes-kolibri-" + "a" * 32})[-1]
        == "preflight"
    )
    cmd = runner.command({"action": "run", "run_id": "hermes-kolibri-" + "a" * 32})
    assert "--execute" in cmd and "--run-id" in cmd


def test_cni_propagation_retries_positive_without_weakening_gate(tmp_path):
    m = importlib.import_module("real_controller")
    target = [["target", "8.8.8.8", 443]]
    calls = iter(
        [
            [{"name": "target", "host": "8.8.8.8", "port": 443, "connected": False}],
            [{"name": "target", "host": "8.8.8.8", "port": 443, "connected": True}],
        ]
    )
    result = m.controls_ready(target, lambda: next(calls), pause=lambda: None)
    assert result[0]["connected"] is True


def test_cni_revocation_waits_for_exact_denial_not_api_ack():
    m = importlib.import_module("real_controller")
    target = [["target", "8.8.8.8", 443]]
    positive = [{"name": "target", "host": "8.8.8.8", "port": 443, "connected": True}]
    denied = [
        {
            "name": "target",
            "host": "8.8.8.8",
            "port": 443,
            "connected": False,
            "denial_candidate": True,
        }
    ]
    calls = iter([positive, denied])
    assert m.denial_ready(target, lambda: next(calls), positive, pause=lambda: None) == denied


@pytest.mark.parametrize("export_ok", [True, False])
@__import__("pytest").mark.parametrize("cleanup_ok", [True, False])
@pytest.mark.parametrize(
    "launch_fault", ["none", "response-loss", "attachment-write-fail", "hidden-response-loss"]
)
@pytest.mark.parametrize(
    "benchmark_failed",
    [
        False,
        True,
        "collect-error",
        "complete-errors",
        "complete-pins",
        "complete-config",
        "complete-partial-manifest",
        "complete-duplicate",
        "complete-provenance",
    ],
)
def test_mocked_approved_controller_exercises_launch_tls_export_and_cleanup(
    monkeypatch, tmp_path, capsys, cleanup_ok, launch_fault, export_ok, benchmark_failed
):
    m = importlib.import_module("real_controller")
    life = importlib.import_module("real_lifecycle")
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    monkeypatch.setattr(m, "STATE", state)
    monkeypatch.setattr(m, "secure_dir", lambda: life.secure_dir(state))
    monkeypatch.setattr(m, "locked", lambda: life.locked(state))

    class Provider:
        rows = []
        calls = []
        omit_next_inventory = False

        def call(self, command, *args):
            self.calls.append(command)
            if command == "balance":
                return {
                    "id": 639482,
                    "username": "moritz-hermes-bot",
                    "is_team": True,
                    "credit": 9.65,
                }
            if command == "list":
                if self.omit_next_inventory:
                    self.omit_next_inventory = False
                    return []
                return self.rows
            if command == "search":
                return [
                    {
                        "id": 123,
                        "disk_space": 690,
                        "cuda_max_good": 13.2,
                        "dph_total": 4.13,
                        "gpu_name": "H200 NVL",
                        "gpu_ram": 143771,
                        "driver_version": "595.84",
                        "reliability": 0.996,
                    }
                ]
            if command == "launch":
                r = life.read(next(state.glob("hermes-kolibri-*.json")))
                self.rows = [
                    {"id": 789, "label": r["label"], "start_date": r["created"], "dph_total": 4.19}
                ]
                if launch_fault in {"response-loss", "hidden-response-loss"}:
                    self.omit_next_inventory = launch_fault == "hidden-response-loss"
                    raise RuntimeError("create response lost after resource allocation")
                return {"success": True, "new_contract": 789}
            if command == "status":
                return {
                    "actual_status": "running",
                    "ports": {"8000/tcp": [{"HostPort": "23456"}]},
                    "public_ipaddr": "8.8.8.8",
                }
            if command == "destroy":
                self.rows = []
                return {"success": True}
            raise AssertionError(command)

    p = Provider()
    attachment_failed = False

    def store(path, record):
        nonlocal attachment_failed
        if (
            launch_fault == "attachment-write-fail"
            and record["instance"] is not None
            and not attachment_failed
        ):
            attachment_failed = True
            raise OSError("injected attachment write failure")
        life.store(path, record)

    monkeypatch.setattr(m, "store", store)
    monkeypatch.setattr(m, "Vast", lambda: p)
    monkeypatch.setattr(m, "finish_provider_logs", lambda *a: True)  # Fake-only provider logs.
    monkeypatch.setattr(m, "Kube", lambda: object())

    def tls(*args, **kwargs):
        # Readiness/download waits must never hold the watchdog state lock.
        with life.locked(state):
            pass
        return 200, b'{"data":[{"id":"Aleph-Alpha/Kolibri-1"}]}'

    monkeypatch.setattr(m, "request", tls)

    def deploy(k, r, c, d, **kw):
        assert "key" not in c
        (d / "namespace-attempted").write_text(r["namespace"])
        return "pod"

    monkeypatch.setattr(m, "deploy", deploy)

    def collect(*args):
        if benchmark_failed == "collect-error":
            raise RuntimeError("temporary evidence export failure after isolation gate")
        write_completed_checkpoint(args[3], benchmark_failed)
        return {
            "runner": "failed" if benchmark_failed is True else "complete",
            "saved_rows": 4 if benchmark_failed is True else 50,
        }

    monkeypatch.setattr(m, "collect", collect)

    def export(*args, **kwargs):
        if not export_ok:
            raise OSError("FAKE_ONLY diagnostic export failed")

    monkeypatch.setattr(m, "export_namespace", export)
    namespace_deletions = []
    monkeypatch.setattr(
        m, "cleanup_namespace", lambda *a: namespace_deletions.append(a) or cleanup_ok
    )
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            {"job_id": "verified-cron", "schedule_seconds": 60, "verified_at": m.time.time()}
        )
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "real_controller.py",
            "--execute-approved",
            "--offer",
            "123",
            "--watchdog-receipt",
            str(receipt),
        ],
    )
    assert m.main() == (
        0 if cleanup_ok and export_ok and launch_fault == "none" and not benchmark_failed else 2
    )
    if benchmark_failed and launch_fault == "none":
        path = next(state.glob("hermes-kolibri-*.json"))
        retained = life.read(path)
        assert retained["status"] == "debug-retained"
        assert namespace_deletions == []
        assert p.calls.count("destroy") == 0 and len(p.rows) == 1
        artifact = state / retained["label"]
        hold = json.loads((artifact / "debug-hold.json").read_text())
        assert hold["deadline"] == retained["deadline"]
        transport = artifact / "resume-transport.json"
        assert transport.stat().st_mode & 0o077 == 0
        assert set(json.loads(transport.read_text())) == {"api_key", "cert", "key"}
        # Retention is a singleton blocker, including if inventory temporarily disappears.
        assert m.main() == 2
        assert p.calls.count("launch") == 1
        life.pass_once(
            root=state, execute=True, provider=p, kube=object(), now=retained["deadline"]
        )
        assert life.read(path)["status"] == "destroyed" and p.calls.count("destroy") == 1
        return
    if launch_fault == "hidden-response-loss":
        assert p.calls.count("launch") == 1 and len(p.rows) == 1
        assert life.read(next(state.glob("hermes-kolibri-*.json")))["status"] == "cleanup"
        # Empty inventory during finish must not permit another controller rental.
        assert m.main() == 2
        assert p.calls.count("launch") == 1 and len(p.rows) == 1
        life.pass_once(root=state, execute=True, provider=p, now=m.time.time())
    assert p.calls.count("launch") == 1 and p.calls.count("destroy") == 1
    assert len(p.rows) == 0
    assert attachment_failed is (launch_fault == "attachment-write-fail")
    assert life.read(next(state.glob("hermes-kolibri-*.json")))["status"] == "destroyed"
    if launch_fault != "none":
        artifact = next(p for p in state.iterdir() if p.is_dir())
        assert (artifact / "controller-failure-traceback.txt").is_file()
        failure = json.loads((artifact / "controller-failure.json").read_text())
        assert failure["exception"]["message"]
    output = capsys.readouterr().out
    assert ('"event": "first-result"' in output) is (launch_fault == "none")
    assert "api_key" not in output and "PRIVATE KEY" not in output


def test_cleanup_namespace_timeout_reconciles_owned_uid_not_foreign():
    import pytest

    m = importlib.import_module("real_controller")

    class Kube:
        calls = []

        def get(self, *args):
            return {
                "metadata": {
                    "uid": "owned",
                    "resourceVersion": "7",
                    "labels": {"kolibri-real": "foreign"},
                }
            }

        def call(self, *args, **kwargs):
            self.calls.append(args)

    k = Kube()
    with pytest.raises(ValueError, match="ownership"):
        m.cleanup_namespace(k, "kolibri-real-" + "a" * 12, "hermes-kolibri-" + "a" * 32)
    assert not k.calls


@pytest.mark.parametrize(
    "bindings,expected",
    [
        ([{"HostIp": "0.0.0.0", "HostPort": "23456"}], 23456),
        (
            [{"HostIp": "0.0.0.0", "HostPort": "23456"}, {"HostIp": "::", "HostPort": "23456"}],
            23456,
        ),
    ],
)
def test_serving_port_accepts_one_unique_port_with_multiple_ip_bindings(bindings, expected):
    m = importlib.import_module("real_controller")
    assert m.serving_port({"8000/tcp": bindings}) == expected


@pytest.mark.parametrize(
    "bindings",
    [
        [],
        [{"HostPort": "0"}],
        [{"HostPort": "65536"}],
        [{"HostPort": "23456"}, {"HostPort": "23457"}],
        [{"HostPort": "bad"}],
        [{"HostPort": "23456", "HostIp": "127.0.0.1"}],
        [{"HostPort": "23456", "HostIp": "::"}],
        None,
    ],
)
def test_serving_port_rejects_invalid_or_ambiguous_bindings(bindings):
    m = importlib.import_module("real_controller")
    with pytest.raises(ValueError):
        m.serving_port({"8000/tcp": bindings})


def test_non_nvidia_or_small_offer_is_rejected_before_launch():
    import pytest

    m = importlib.import_module("real_controller")
    valid = {
        "id": 123,
        "disk_space": 690,
        "cuda_max_good": 13.2,
        "dph_total": 4.13,
        "gpu_name": "H200 NVL",
        "gpu_ram": 143771,
        "driver_version": "595.84",
        "reliability": 0.996,
    }
    assert m.select_offer([valid], 123, 4.25) == valid
    for change in (
        {"gpu_name": "MI300X"},
        {"gpu_ram": 80000},
        {"disk_space": 45},
        {"driver_version": "550.1"},
        {"reliability": 0.5},
        {"dph_total": 5},
    ):
        with pytest.raises(ValueError):
            m.select_offer([{**valid, **change}], 123, 4.25)


@__import__("pytest").mark.parametrize("foreign", [False, True])
def test_actual_controller_reconciles_namespace_create_lost_response(
    monkeypatch, tmp_path, foreign
):
    import subprocess

    m = importlib.import_module("real_controller")
    life = importlib.import_module("real_lifecycle")
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    monkeypatch.setattr(m, "STATE", state)
    monkeypatch.setattr(m, "secure_dir", lambda: life.secure_dir(state))
    monkeypatch.setattr(m, "Vast", lambda: object())  # Any provider call would fail this CPU path.
    monkeypatch.setattr(
        m,
        "material",
        lambda d: {"api_key": "DISPOSABLE", "cert": "PUBLIC_CERT", "key": "DISPOSABLE_KEY"},
    )
    monkeypatch.setattr(
        m.socket, "getaddrinfo", lambda *a: [(None, None, None, None, ("151.101.0.223", 443))]
    )

    class Kube:
        namespace = None
        deleted = False

        def get(self, ns, kind, name):
            return self.namespace

        def call(self, *args, data=None, **kwargs):
            if "get" in args and ("pods" in args or "events" in args):
                return '{"items":[]}'
            if args[0] == "create":
                assert data["kind"] == "Namespace"
                self.namespace = {
                    **data,
                    "metadata": {**data["metadata"], "uid": "owned", "resourceVersion": "7"},
                }
                if foreign:
                    self.namespace["metadata"]["labels"]["kolibri-real"] = "foreign"
                raise subprocess.TimeoutExpired("mock-kube-create", 60)
            if args[0] == "delete":
                assert data["preconditions"] == {"uid": "owned", "resourceVersion": "7"}
                self.deleted = True
                self.namespace = None
                return ""
            if args[0] == "wait":
                return ""
            raise AssertionError(args)

    kube = Kube()
    monkeypatch.setattr(m, "Kube", lambda: kube)
    monkeypatch.setattr(sys, "argv", ["real_controller.py", "--execute-cpu-preflight"])
    assert m.main() == 2
    directory = next(p for p in state.iterdir() if p.is_dir())
    cleanup = json.loads((directory / "namespace-cleanup.json").read_text())
    assert cleanup["absent"] is (not foreign)
    assert kube.deleted is (not foreign)


@pytest.mark.parametrize(
    "previous",
    ["expired-ambiguous", "legacy-unbound", "legacy-bound", "rejected-delete", "unknown-delete"],
)
def test_second_rental_rejected_for_unresolved_lease_despite_empty_inventory(
    monkeypatch, tmp_path, previous
):
    m = importlib.import_module("real_controller")
    life = importlib.import_module("real_lifecycle")
    from test_real_lifecycle import ChangingInventory, Provider, lease, row

    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    r = lease()
    if previous.endswith("-delete"):

        class UnacknowledgedDelete(ChangingInventory):
            def call(self, command, *args):
                if command == "destroy":
                    return {"success": False} if previous == "rejected-delete" else {}
                return super().call(command, *args)

        p = UnacknowledgedDelete([row(r)], [3])
        assert life.watchdog(r, p, now=7000, execute=True) == "retry"
        assert r["status"] == "cleanup" and len(p.rows) == 1
    elif previous.startswith("legacy"):
        r["status"] = "absent"
        if previous == "legacy-bound":
            r.update(instance=789, start_date=1010.0)
    else:
        life.watchdog(r, Provider(), now=7000, execute=True)
    life.store(state / (r["label"] + ".json"), r)
    monkeypatch.setattr(m, "STATE", state)
    monkeypatch.setattr(m, "secure_dir", lambda: life.secure_dir(state))
    monkeypatch.setattr(m, "locked", lambda: life.locked(state))
    monkeypatch.setattr(
        m, "material", lambda d: {"api_key": "DISPOSABLE", "cert": "CERT", "key": "KEY"}
    )
    calls = []

    class NoRental:
        def call(self, command, *args):
            calls.append(command)
            raise RuntimeError("must reject unresolved lease before querying provider")

    monkeypatch.setattr(m, "Vast", NoRental)
    monkeypatch.setattr(m, "Kube", lambda: object())
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps({"job_id": "fake-cron", "schedule_seconds": 60, "verified_at": m.time.time()})
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "real_controller.py",
            "--execute-approved",
            "--offer",
            "123",
            "--watchdog-receipt",
            str(receipt),
        ],
    )
    assert m.main() == 2
    assert calls == []


def test_collect_preserves_current_and_archived_attempts_with_replay_progress(tmp_path):
    import subprocess

    m = importlib.import_module("real_controller")
    work = tmp_path / "work"
    work.mkdir()
    archived = work / "attempts/0001/benchmark"
    archived.mkdir(parents=True)
    (archived / "failure.json").write_text('{"reason":"first attempt"}')
    (archived.parent / "runner-stdout.log").write_text("first log")
    (archived.parent / "memory-metrics.jsonl").write_text('{"memory_current":100}\n')
    (archived.parent / "memory-metrics.metadata.json").write_text('{"status":"sampled"}')
    (work / "runner-status.json").write_text('{"status":"failed","attempt":2}')
    (work / "runner-stdout.log").write_text("second log")
    (work / "runner-stderr.log").write_text("")
    (work / "memory-metrics.jsonl").write_text('{"memory_current":200}\n')
    (work / "memory-metrics.metadata.json").write_text('{"status":"unavailable"}')
    output = tmp_path / "export"
    output.mkdir(mode=0o700)

    class Kube:
        def call(self, *args, **kwargs):
            script = args[-1].replace("/work/", str(work) + "/")
            return subprocess.run(
                [sys.executable, "-c", script], check=True, capture_output=True, text=True
            ).stdout

    record = {"label": "hermes-kolibri-" + "a" * 32, "namespace": "fake", "status": "running"}
    progress = m.collect(Kube(), record, "pod", output)
    assert progress["attempt"] == 2
    assert (
        output / "attempts/0001/benchmark/failure.json"
    ).read_text() == '{"reason":"first attempt"}'
    assert (output / "attempts/0001/runner-stdout.log").read_text() == "first log"
    assert (output / "attempts/0002/runner-stdout.log").read_text() == "second log"
    assert (output / "memory-metrics.jsonl").read_text() == '{"memory_current":200}\n'
    assert (output / "attempts/0001/memory-metrics.jsonl").read_text() == '{"memory_current":100}\n'
    assert (output / "attempts/0002/memory-metrics.jsonl").read_text() == '{"memory_current":200}\n'
    assert (output / "memory-metrics.metadata.json").read_text() == '{"status":"unavailable"}'
    assert (
        output / "attempts/0001/memory-metrics.metadata.json"
    ).read_text() == '{"status":"sampled"}'
    assert (
        output / "attempts/0002/memory-metrics.metadata.json"
    ).read_text() == '{"status":"unavailable"}'


def test_runner_job_deadline_uses_remaining_original_lease_not_fresh_ttl():
    m = importlib.import_module("real_controller")
    config = {"host": "8.8.8.8", "port": 23456, "cert": "CERT", "api_key": "DISPOSABLE"}
    objects = m.resources(
        "kolibri-real-" + "a" * 12,
        "hermes-kolibri-" + "a" * 32,
        config,
        ["151.101.0.223"],
        remaining_seconds=99,
    )
    job = next(o for o in objects if o["kind"] == "Job")
    assert job["spec"]["activeDeadlineSeconds"] == 99
    with pytest.raises(ValueError, match="remaining"):
        m.resources(
            "kolibri-real-" + "a" * 12,
            "hermes-kolibri-" + "a" * 32,
            config,
            ["151.101.0.223"],
            remaining_seconds=0,
        )


def test_terminated_runner_export_does_not_exec_dead_container(monkeypatch, tmp_path):
    m = importlib.import_module("real_controller")
    record = {"namespace": "fake", "label": "hermes-kolibri-" + "a" * 32}

    class Kube:
        def call(self, *args, **kwargs):
            assert "exec" not in args
            if "pods" in args:
                return json.dumps(
                    {
                        "items": [
                            {
                                "metadata": {"name": "pod"},
                                "status": {
                                    "containerStatuses": [
                                        {
                                            "name": "runner",
                                            "state": {"terminated": {"exitCode": 137}},
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                )
            return "{}" if "events" in args else "last log"

    def no_collect(*args, **kwargs):
        pytest.fail("terminated container is not exec-able")

    monkeypatch.setattr(m, "collect", no_collect)
    m.export_namespace(Kube(), record, "pod", tmp_path)
    assert (tmp_path / "kubernetes-pod-runner.log").read_text() == "last log"


@pytest.mark.parametrize("boundary", ["credit", "rate", "expiry", "unowned"])
def test_failed_benchmark_cannot_enter_debug_hold_past_billing_or_ownership_gates(
    monkeypatch, tmp_path, boundary
):
    m = importlib.import_module("real_controller")
    life = importlib.import_module("real_lifecycle")
    from test_real_lifecycle import Provider, lease, row

    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    record = lease()
    record.update(instance=789, start_date=1010.0, status="running")
    path = root / (record["label"] + ".json")
    life.store(path, record)
    directory = root / record["label"]
    directory.mkdir(mode=0o700)
    provider = Provider(
        [
            row(
                record,
                label="foreign" if boundary == "unowned" else record["label"],
                dph_total=4.5 if boundary == "rate" else 4.19,
            )
        ],
        credit=0 if boundary == "credit" else 9.65,
    )
    monkeypatch.setattr(m, "locked", lambda: life.locked(root))
    monkeypatch.setattr(m.time, "time", lambda: 6400 if boundary == "expiry" else 1100)
    assert (
        m.retain_failure(
            path, record, object(), "pod", directory, {"api_key": "DISPOSABLE"}, provider
        )
        is False
    )
    assert not (directory / "debug-hold.json").exists()
    assert provider.deleted == ([] if boundary == "unowned" else [789])


@pytest.mark.parametrize("credit,expected", [(14.7, 0), (14.699, 2)])
@pytest.mark.parametrize("resume", [False, True])
def test_three_hour_cli_quote_covers_fixed_deadline_before_launch(
    monkeypatch, tmp_path, credit, expected, resume
):
    from test_checkpoint import row, seed

    m = importlib.import_module("real_controller")
    life = importlib.import_module("real_lifecycle")
    source = seed(tmp_path / "seed", [row(day=d) for d in range(1, 14)]) if resume else None
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    monkeypatch.setattr(m, "STATE", state)
    monkeypatch.setattr(m, "secure_dir", lambda root=state: life.secure_dir(root))
    monkeypatch.setattr(m, "locked", lambda: life.locked(state))
    monkeypatch.setattr(m, "material", lambda d: {"api_key": "TOKEN", "cert": "CERT", "key": "KEY"})
    monkeypatch.setattr(m, "Kube", lambda: object())
    monkeypatch.setattr(m, "finish_namespace", lambda *a, **k: True)
    monkeypatch.setattr(m, "finish_provider_logs", lambda *a, **k: True)
    monkeypatch.setattr(m, "export_namespace", lambda *a, **k: None)
    clock = [1000.0]
    monkeypatch.setattr(m.time, "time", lambda: clock[0])
    calls = []

    class Provider:
        rows = []

        def call(self, command, *args):
            calls.append(command)
            if command == "balance":
                return {
                    "id": 639482,
                    "username": "moritz-hermes-bot",
                    "is_team": True,
                    "credit": credit,
                }
            if command == "list":
                return self.rows
            if command == "search":
                return [
                    {
                        "id": 123,
                        "disk_space": 690,
                        "cuda_max_good": 13.2,
                        "dph_total": 4.6,
                        "gpu_name": "H200",
                        "gpu_ram": 143771,
                        "driver_version": "595.84",
                        "reliability": 0.996,
                    }
                ]
            if command == "launch":
                r = life.read(next(state.glob("hermes-kolibri-*.json")))
                assert r["deadline"] == 11800
                self.rows = [
                    {"id": 789, "label": r["label"], "start_date": 1000.0, "dph_total": 4.6}
                ]
                clock[0] += 120
                return {"success": True, "new_contract": 789}
            if command == "status":
                return {
                    "actual_status": "running",
                    "ports": {"8000/tcp": [{"HostPort": "23456"}]},
                    "public_ipaddr": "8.8.8.8",
                }
            if command == "destroy":
                self.rows = []
                return {"success": True}
            raise AssertionError(command)

    monkeypatch.setattr(m, "Vast", Provider)
    monkeypatch.setattr(
        m, "request", lambda *a, **k: (200, b'{"data":[{"id":"Aleph-Alpha/Kolibri-1"}]}')
    )

    def deploy(k, r, c, d, **kwargs):
        assert r["deadline"] == 11800
        if source:
            assert kwargs["checkpoint"] == (
                ("results.jsonl", (source / "results.jsonl").read_bytes()),
                ("manifest.json", (source / "manifest.json").read_bytes()),
            )
            assert (d / "checkpoint-source/results.jsonl").read_bytes() == kwargs["checkpoint"][0][
                1
            ]
        else:
            assert kwargs["checkpoint"] == ()
        recipe = m.resources(
            r["namespace"],
            r["label"],
            c,
            ["151.101.0.223"],
            remaining_seconds=int(r["deadline"] - clock[0]),
        )
        assert recipe[-1]["spec"]["activeDeadlineSeconds"] == 10680
        return "pod"

    monkeypatch.setattr(m, "deploy", deploy)
    collected = []

    def collect(*args):
        collected.append(clock[0])
        if len(collected) == 1:
            clock[0] += 5500
            return {"runner": "running", "saved_rows": 13}
        write_completed_checkpoint(args[3])
        return {"runner": "complete", "saved_rows": 50}

    monkeypatch.setattr(m, "collect", collect)
    monkeypatch.setattr(m.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(m.time, "sleep", lambda seconds: None)
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"job_id": "fake", "schedule_seconds": 60, "verified_at": 1000}))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "real_controller.py",
            "--execute-approved",
            "--offer",
            "123",
            "--watchdog-receipt",
            str(receipt),
            "--ttl-seconds",
            "10800",
            "--hourly-ceiling",
            "4.7",
            "--reserve",
            "0",
        ],
    )
    if source:
        sys.argv += ["--resume-from", str(source)]
    assert m.main() == expected
    directory = next(p for p in state.iterdir() if p.is_dir())
    quote = json.loads((directory / "quote.json").read_text())
    assert quote["ttl_seconds"] == 10800 and quote["estimated_maximum"] == 14.7
    assert calls.count("launch") == (1 if expected == 0 else 0)
    if source:
        assert (
            json.loads((directory / "checkpoint-source.json").read_text())["provenance"][
                "saved_rows"
            ]
            == 13
        )


def test_cli_and_renderer_share_three_hour_bound(monkeypatch):
    m = importlib.import_module("real_controller")
    life = importlib.import_module("real_lifecycle")
    assert m.MAX_TTL_SECONDS == life.MAX_TTL_SECONDS == 10800
    assert 0 < m.DEFAULT_TTL_SECONDS <= m.MAX_TTL_SECONDS
    monkeypatch.setattr(m, "bundle_archive", lambda: b"fake")
    monkeypatch.setattr(sys, "argv", ["real_controller.py", "--ttl-seconds", "10801"])
    with pytest.raises(SystemExit) as error:
        m.main()
    assert error.value.code == 2
    with pytest.raises(ValueError, match="remaining"):
        m.resources(
            "kolibri-real-" + "a" * 12,
            "hermes-kolibri-" + "a" * 32,
            {"host": "8.8.8.8", "port": 443},
            ["151.101.0.223"],
            remaining_seconds=10801,
        )


def test_checkpoint_preparation_uses_shared_validator_once_and_freezes_bytes(monkeypatch, tmp_path):
    import types

    import run

    m = importlib.import_module("real_controller")
    source = tmp_path / "source"
    source.mkdir()
    # Deliberately not valid checkpoint JSON: this test delegates validation rather than duplicates it.
    validated = {
        "results_bytes": b"validated rows\n",
        "manifest_bytes": b"validated manifest\n",
        "provenance": {"saved_rows": 13},
    }
    calls = []

    def validate(directory, config, pins):
        assert directory == source
        assert config == run.load_experiment(m.BASE / "config.yaml")
        assert pins == json.loads((m.BASE / "pins.json").read_text())
        calls.append(directory)
        return validated

    monkeypatch.setitem(
        sys.modules, "checkpoint", types.SimpleNamespace(validated_checkpoint=validate)
    )
    output = tmp_path / "lease"
    output.mkdir(mode=0o700)
    payload = m.prepare_checkpoint(source, output)
    assert payload == (
        ("results.jsonl", b"validated rows\n"),
        ("manifest.json", b"validated manifest\n"),
    )
    validated["results_bytes"] = b"changed source after validation"
    assert payload[0][1] == b"validated rows\n"
    assert calls == [source]
    assert {p.name for p in (output / "checkpoint-source").iterdir()} == {
        "results.jsonl",
        "manifest.json",
    }
    assert (output / "checkpoint-source/results.jsonl").read_bytes() == payload[0][1]
    assert (output / "checkpoint-source/results.jsonl").stat().st_mode & 0o077 == 0
    metadata = json.loads((output / "checkpoint-source.json").read_text())
    assert metadata == {"source": str(source), "provenance": {"saved_rows": 13}}


@pytest.mark.parametrize("tamper", [False, True])
def test_checkpoint_exec_delivery_is_segmented_allowlisted_and_hash_verified(tmp_path, tamper):
    import subprocess

    m = importlib.import_module("real_controller")
    work = tmp_path / "work"
    work.mkdir()
    payload = (("results.jsonl", b"x" * 200000), ("manifest.json", b'{"validated":true}\n'))
    calls = []

    def execute(script):
        assert len(script) < 65536
        calls.append(script)
        if tamper and "hexdigest" in script:
            (work / "checkpoint/results.jsonl").write_bytes(b"tampered")
        translated = script.replace("/work/checkpoint", str(work / "checkpoint"))
        return subprocess.run(
            [sys.executable, "-c", translated], capture_output=True, text=True, check=True
        ).stdout

    if tamper:
        with pytest.raises((ValueError, subprocess.CalledProcessError)):
            m.deliver_checkpoint(execute, payload)
    else:
        m.deliver_checkpoint(execute, payload)
        assert {p.name for p in (work / "checkpoint").iterdir()} == {
            "results.jsonl",
            "manifest.json",
        }
        for name, data in payload:
            assert (work / "checkpoint" / name).read_bytes() == data
            assert (work / "checkpoint" / name).stat().st_mode & 0o077 == 0
        assert len(calls) > 4


def test_resume_cli_invalid_checkpoint_fails_before_provider_or_kube(monkeypatch, tmp_path):
    m = importlib.import_module("real_controller")
    life = importlib.import_module("real_lifecycle")
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    monkeypatch.setattr(m, "STATE", state)
    monkeypatch.setattr(m, "secure_dir", lambda: life.secure_dir(state))
    monkeypatch.setattr(m, "material", lambda d: {"api_key": "TOKEN", "cert": "CERT", "key": "KEY"})
    monkeypatch.setattr(m, "Vast", lambda: object())
    monkeypatch.setattr(m, "Kube", lambda: object())
    calls = []

    def reject(source, directory):
        calls.append(source)
        raise ValueError("invalid seed from shared validator")

    monkeypatch.setattr(m, "prepare_checkpoint", reject)
    source = tmp_path / "seed"
    monkeypatch.setattr(
        sys, "argv", ["real_controller.py", "--execute-approved", "--resume-from", str(source)]
    )
    assert m.main() == 2
    assert calls == [source]
    assert not list(state.glob("hermes-kolibri-*.json"))


@pytest.mark.parametrize("tamper", [False, True, "expired"])
def test_deploy_delivers_checkpoint_before_release_and_bundles_shared_helpers(
    monkeypatch, tmp_path, tamper
):
    import subprocess

    m = importlib.import_module("real_controller")
    work = tmp_path / "work"
    work.mkdir()
    directory = tmp_path / "lease"
    directory.mkdir(mode=0o700)
    clock = [1000.0]
    monkeypatch.setattr(m.time, "time", lambda: clock[0])
    monkeypatch.setattr(
        m.socket, "getaddrinfo", lambda *a: [(None, None, None, None, ("151.101.0.223", 443))]
    )
    monkeypatch.setattr(m, "controls_ready", lambda *a, **k: [])
    monkeypatch.setattr(m, "denial_ready", lambda *a, **k: [])
    payload = (
        ("results.jsonl", b"validated results\n"),
        ("manifest.json", b"validated manifest\n"),
    )
    config = {"host": "8.8.8.8", "port": 23456, "cert": "CERT", "api_key": "TOKEN"}
    record = {
        "namespace": "kolibri-real-" + "a" * 12,
        "label": "hermes-kolibri-" + "a" * 32,
        "deadline": m.time.time() + 10800,
    }
    created = []

    class Kube:
        def get(self, ns, kind, name):
            if kind == "service":
                return {"spec": {"clusterIP": "10.43.0.1", "ports": [{"port": 443}]}}
            if kind == "endpoints":
                return {"subsets": []}
            return None

        def call(self, *args, data=None, **kwargs):
            if "create" in args:
                created.append(data)
                return ""
            if "get" in args:
                return json.dumps(
                    {
                        "items": [
                            {
                                "metadata": {"name": "pod"},
                                "status": {"conditions": [{"type": "Ready", "status": "True"}]},
                            }
                        ]
                    }
                )
            if "delete" in args:
                return ""
            assert "exec" in args and args[args.index("-c") + 1] == "runner"
            script = args[-1]
            if tamper is True and "hexdigest" in script:
                (work / "checkpoint/results.jsonl").write_bytes(b"tampered")
            if tamper == "expired" and "hexdigest" in script:
                clock[0] = record["deadline"]
            if "released.json" in script:
                assert '"resume_from"' not in script
                for name, data in payload:
                    assert (work / "checkpoint" / name).read_bytes() == data
            return subprocess.run(
                [sys.executable, "-c", script.replace("/work/", str(work) + "/")],
                capture_output=True,
                text=True,
                check=True,
            ).stdout

    if tamper:
        with pytest.raises(
            (ValueError, RuntimeError), match="expired" if tamper == "expired" else "hash"
        ):
            m.deploy(Kube(), record, config, directory, checkpoint=payload)
        assert not (work / "released.json").exists()
    else:
        assert m.deploy(Kube(), record, config, directory, checkpoint=payload) == "pod"
        assert json.loads((work / "released.json").read_text()) == {
            "action": "run",
            "run_id": record["label"],
        }
    bundle = next(o for o in created[1]["items"] if o["kind"] == "ConfigMap")
    assert "checkpoint.py" in bundle["data"] and "memory_telemetry.py" in bundle["data"]
    manifest = json.loads((directory / "bundle-manifest.json").read_text())
    assert "checkpoint.py" in manifest["scripts_sha256"]
    assert "memory_telemetry.py" in manifest["scripts_sha256"]


def test_oom_runner_exports_shared_artifacts_through_live_tls_proxy(tmp_path):
    import subprocess

    m = importlib.import_module("real_controller")
    work = tmp_path / "work"
    work.mkdir()
    record = {"namespace": "fake", "label": "hermes-kolibri-" + "a" * 32, "status": "running"}
    run = work / "repo/experiments/kolibri/runs" / record["label"]
    run.mkdir(parents=True)
    (run / "manifest.json").write_text('{"status":"running"}')
    (run / "results.jsonl").write_text('{"year":2022,"day":1,"error":null}\n')
    (work / "runner-status.json").write_text('{"status":"running","attempt":1}')
    (work / "runner-stdout.log").write_text("retained stdout")
    (work / "runner-stderr.log").write_text("retained stderr")
    (work / "memory-metrics.jsonl").write_text('{"memory_peak":1000000000}\n')
    output = tmp_path / "export"
    output.mkdir(mode=0o700)
    exec_calls = []

    class Kube:
        def call(self, *args, **kwargs):
            if "pods" in args:
                return json.dumps(
                    {
                        "items": [
                            {
                                "metadata": {"name": "pod"},
                                "status": {
                                    "containerStatuses": [
                                        {
                                            "name": "runner",
                                            "state": {
                                                "terminated": {
                                                    "exitCode": 137,
                                                    "reason": "OOMKilled",
                                                }
                                            },
                                        },
                                        {"name": "tls-proxy", "state": {"running": {}}},
                                    ]
                                },
                            }
                        ]
                    }
                )
            if "exec" in args:
                assert args[args.index("-c") + 1] == "tls-proxy"
                assert args[args.index("--") + 1 : args.index("--") + 4] == ("python", "-I", "-c")
                exec_calls.append(args)
                return subprocess.run(
                    [sys.executable, "-c", args[-1].replace("/work/", str(work) + "/")],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout
            return "{}" if "events" in args else "container log"

    m.export_namespace(Kube(), record, "pod", output)
    assert exec_calls
    assert (output / "results.jsonl").read_bytes() == (run / "results.jsonl").read_bytes()
    assert (output / "memory-metrics.jsonl").read_bytes() == (
        work / "memory-metrics.jsonl"
    ).read_bytes()
    assert json.loads((output / "namespace-export.json").read_text())["complete"] is True

"""Fake-only lifecycle contracts; no credentials, provider SDK, or network."""

import importlib.util
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))


def test_cleanup_default_never_deletes_even_when_overdue():
    spec = importlib.util.find_spec("cpu_watchdog")
    assert spec is not None, "missing fake-only safe-default cleanup"
    import cpu_watchdog as w

    class Provider:
        deletes = []

        def get(self, instance):
            return dict(record)

        def delete(self, record):
            self.deletes.append(record)

    record = dict(
        provider="fake",
        instance="fake-1",
        owner="kolibri-test",
        lease="lease-1",
        created=10,
        deadline=20,
    )
    provider = Provider()
    assert w.cleanup(record, provider, now=21) == "dry-run"
    assert provider.deletes == []


def test_deadline_exact_binding_readback_and_retry():
    import cpu_watchdog as w

    record = dict(
        provider="fake",
        instance="fake-1",
        owner="kolibri-test",
        lease="lease-1",
        created=10,
        deadline=20,
    )

    class Provider:
        calls = 0
        state = dict(record)

        def get(self, instance):
            return self.state

        def delete(self, expected):
            assert expected == record
            self.calls += 1
            if self.calls == 1:
                raise OSError("fake transient failure")
            if self.calls == 3:
                self.state = None

    p = Provider()
    assert w.cleanup(record, p, now=19, execute=True) == "not-due"
    assert p.calls == 0
    assert w.cleanup(record, p, now=20, execute=True) == "retry"
    assert w.cleanup(record, p, now=21, execute=True) == "retry"
    assert w.cleanup(record, p, now=22, execute=True) == "absent"
    assert p.calls == 3
    assert w.cleanup(record, p, now=23, execute=True) == "absent"


def test_mismatch_never_deletes():
    import cpu_watchdog as w

    record = dict(
        provider="fake",
        instance="fake-1",
        owner="kolibri-test",
        lease="lease-1",
        created=10,
        deadline=20,
    )
    for field in record:

        class Provider:
            def get(self, instance):
                return {**record, field: "foreign"}

            def delete(self, expected):
                raise AssertionError("must not delete mismatched resource")

        assert w.cleanup(record, Provider(), now=30, execute=True) == "ownership-mismatch"


def test_invalid_records_fail_closed():
    import pytest

    import cpu_watchdog as w

    record = dict(
        provider="fake",
        instance="fake-1",
        owner="kolibri-test",
        lease="lease-1",
        created=10,
        deadline=20,
    )
    invalid = [
        {**record, "provider": "vast"},
        {**record, "instance": "1234"},
        {**record, "deadline": float("nan")},
        {**record, "deadline": 99999},
        {**record, "deadline": 9},
        {**record, "extra": True},
    ]
    for bad in invalid:
        with pytest.raises(ValueError):
            w.cleanup(bad, None, now=21, execute=True)


def test_real_agent_executes_fixture_in_jupyter(tmp_path, monkeypatch):
    import asyncio
    import json

    assert importlib.util.find_spec("cpu_fixture") is not None, (
        "missing real CPU agent fixture runtime"
    )
    from cpu_fixture import run_fixture

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AOC_SESSION_TOKEN", "SYNTHETIC_NOT_A_COOKIE")
    monkeypatch.setenv("EXECUTION_SANDBOX", "local")
    import pydantic_ai.models

    before = pydantic_ai.models.ALLOW_MODEL_REQUESTS
    result = asyncio.run(run_fixture({"input": "1\n2\n", "part1": 3, "part2": 2}, []))
    assert pydantic_ai.models.ALLOW_MODEL_REQUESTS == before, (
        "fixture must restore process-global safety switch"
    )
    assert result["model"] == "SYNTHETIC_CPU_FIXTURE_NOT_KOLIBRI"
    assert result["jupyter"]["part1"] == 3
    assert result["jupyter"]["part2"] == 2
    assert result["jupyter"]["token_present"] is False
    assert result["part1_correct"] and result["part2_correct"]
    assert json.loads((tmp_path / "out/results.jsonl").read_text())["model"] == result["model"]


def test_fake_http_failure_ack_not_absence_and_atomic_ownership():
    import json
    import threading
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    import pytest

    assert importlib.util.find_spec("cpu_fake_provider") is not None, (
        "missing isolated fake HTTP fixture"
    )
    from cpu_fake_provider import servers

    record = dict(
        provider="fake",
        instance="fake-1",
        owner="kolibri-test",
        lease="lease-1",
        created=10,
        deadline=20,
    )
    fixture, api = servers(record, host="127.0.0.1", ports=(0, 0))
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (fixture, api)]
    for t in threads:
        t.start()
    base = "http://127.0.0.1:" + str(api.server_port)

    def delete(data):
        return urlopen(
            Request(base + "/instances/fake-1", data=json.dumps(data).encode(), method="DELETE"),
            timeout=2,
        )

    try:
        with pytest.raises(HTTPError) as mismatch:
            delete({**record, "owner": "kolibri-foreign"})
        assert mismatch.value.code == 409
        with pytest.raises(HTTPError) as failure:
            delete(record)
        assert failure.value.code == 503
        assert delete(record).status == 200
        assert json.load(urlopen(base + "/instances/fake-1")) == record
        assert delete(record).status == 200
        with pytest.raises(HTTPError) as absent:
            urlopen(base + "/instances/fake-1")
        assert absent.value.code == 404
        audit = json.load(urlopen(base + "/audit"))
        assert audit["attempts"] == 3
        assert "fake-foreign" in audit["remaining"]
    finally:
        for s in (fixture, api):
            s.shutdown()
            s.server_close()


def test_kubernetes_recipe_is_hardened_bounded_and_network_scoped():
    assert importlib.util.find_spec("cpu_k8s") is not None, (
        "missing reproducible CPU-only isolation recipe"
    )
    from cpu_k8s import resources

    record = dict(
        provider="fake",
        instance="fake-1",
        owner="kolibri-test",
        lease="lease-1",
        created=10,
        deadline=20,
    )
    objects = resources("kolibri-cpu-test", record, ["151.101.0.223"])
    for obj in objects:
        if obj["kind"] != "Job":
            continue
        assert obj["spec"]["activeDeadlineSeconds"] <= 600
        assert obj["spec"]["backoffLimit"] == 0
        pod = obj["spec"]["template"]["spec"]
        assert pod["automountServiceAccountToken"] is False
        if obj["metadata"]["name"] == "cpu-runner":
            init_env = {item["name"]: item["value"] for item in pod["initContainers"][0]["env"]}
            assert init_env["TMPDIR"] == "/work", (
                "pip temporary extraction must not evict 128Mi runtime tmp"
            )
        assert not pod.get("hostNetwork") and not pod.get("hostPID")
        assert pod["securityContext"]["runAsUser"] == 10001
        assert pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
        assert all("hostPath" not in v and "secret" not in v for v in pod["volumes"])
        for c in pod["containers"] + pod.get("initContainers", []):
            sc = c["securityContext"]
            assert sc["readOnlyRootFilesystem"] and not sc["allowPrivilegeEscalation"]
            assert sc["capabilities"]["drop"] == ["ALL"]
            assert "@sha256:" in c["image"]
            assert "memory" in c["resources"]["limits"]
            assert not any("gpu" in key for key in c["resources"]["limits"])
    policies = {o["metadata"]["name"]: o for o in objects if o["kind"] == "NetworkPolicy"}
    assert policies["default-deny"]["spec"]["egress"] == []
    assert policies["default-deny"]["spec"]["ingress"] == []
    assert policies["runner-fixture"]["spec"]["egress"][0]["ports"] == [
        {"port": 8080, "protocol": "TCP"}
    ]
    assert policies["watchdog-provider"]["spec"]["egress"][0]["ports"] == [
        {"port": 8081, "protocol": "TCP"}
    ]
    assert policies["install-public"]["spec"]["egress"][0]["to"] == [
        {"ipBlock": {"cidr": "151.101.0.223/32"}}
    ]


def test_rehearsal_default_is_no_spend_no_cluster_writes(tmp_path):
    import json
    import os
    import subprocess

    path = BASE / "cpu_rehearsal.py"
    assert path.is_file(), "missing explicit opt-in CPU orchestration"
    proc = subprocess.run(
        [sys.executable, str(path)],
        cwd=tmp_path,
        env={**os.environ, "PATH": ""},
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["execution"] is False and result["inference"] is False
    assert result["provider"] == "fake"
    assert list(tmp_path.iterdir()) == []


def test_actual_fixture_runner_fault_injection_preserves_logs():
    import subprocess

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "from cpu_fixture import finish_report; finish_report({'synthetic': True}, '{\"model\":\"SYNTHETIC_CPU_FIXTURE_NOT_KOLIBRI\"}', crash=True)",
        ],
        cwd=BASE,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 42, proc.stderr
    assert '"synthetic": true' in proc.stdout
    assert "RESULT_JSONL" in proc.stdout
    assert "actual_agent_runner_crash" in proc.stdout


def test_optimized_python_cannot_bypass_rehearsal_assertions(tmp_path):
    import os
    import subprocess

    proc = subprocess.run(
        [sys.executable, "-O", str(BASE / "cpu_rehearsal.py"), "--execute-cpu"],
        cwd=tmp_path,
        env={**os.environ, "PATH": ""},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "optimized Python" in proc.stderr
    assert list(tmp_path.iterdir()) == []


def test_empty_public_allowlist_is_rejected():
    import pytest

    from cpu_k8s import resources

    record = dict(
        provider="fake",
        instance="fake-1",
        owner="kolibri-test",
        lease="lease-1",
        created=10,
        deadline=20,
    )
    with pytest.raises(ValueError, match="nonempty"):
        resources("kolibri-cpu-test", record, [])


def test_fixture_closed_port_without_positive_control_is_not_isolation(tmp_path, monkeypatch):
    import asyncio
    import socket

    import pytest

    from cpu_fixture import run_fixture

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AOC_SESSION_TOKEN", "SYNTHETIC_NOT_A_COOKIE")
    monkeypatch.setenv("EXECUTION_SANDBOX", "local")
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]  # bound but not listening
        with pytest.raises(RuntimeError, match="positive control"):
            asyncio.run(
                run_fixture(
                    {"input": "1\n2\n", "part1": 3, "part2": 2}, [["closed", "127.0.0.1", port]]
                )
            )


def test_jupyter_dns_failure_with_control_record_still_fails(tmp_path, monkeypatch):
    import asyncio

    import pytest

    from cpu_fixture import run_fixture

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AOC_SESSION_TOKEN", "SYNTHETIC_NOT_A_COOKIE")
    monkeypatch.setenv("EXECUTION_SANDBOX", "local")
    targets = [["dns", "invalid.test.invalid", 443]]
    # Injected control record exercises kernel failure classification, not real reachability evidence.
    positive = [{"name": "dns", "host": "invalid.test.invalid", "port": 443, "connected": True}]
    with pytest.raises(AssertionError, match="denial"):
        asyncio.run(run_fixture({"input": "1\n2\n", "part1": 3, "part2": 2}, targets, positive))

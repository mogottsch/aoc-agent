"""Offline replacement contract: no providers, cluster or credentials."""

import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_checkpoint import pins, row, seed, settings


def test_filtered_checkpoint_preserves_39_nonerror_raw_42_and_wrong_answers(tmp_path):
    checkpoint = importlib.import_module("checkpoint")
    rows = [
        row(year=y, day=d, error="OOM" if (y, d) in {(2022, 2), (2023, 3), (2023, 7)} else None)
        for y in (2022, 2023)
        for d in range(1, 26)
        if y == 2022 or d <= 17
    ]
    source = seed(tmp_path / "source", rows, saved_rows=42, error_rows=3, status="running")
    raw = (source / "results.jsonl").read_bytes()
    manifest = (source / "manifest.json").read_bytes()
    result = checkpoint.filtered_checkpoint(source, settings(), pins())
    assert len(result["completed"]) == 39
    assert result["raw_results_bytes"] == raw
    assert result["raw_manifest_bytes"] == manifest
    assert (source / "results.jsonl").read_bytes() == raw
    provenance = json.loads(result["manifest_bytes"])["seed"]
    assert provenance["schema_version"] == 2
    assert provenance["raw_results_sha256"] == hashlib.sha256(raw).hexdigest()
    assert provenance["source_rows"] == 42
    assert provenance["filtered_errors"] == [[2022, 2], [2023, 3], [2023, 7]]
    assert all(
        not r["part1_correct"] for r in map(json.loads, result["results_bytes"].splitlines())
    )
    derived = tmp_path / "derived"
    derived.mkdir()
    (derived / "results.jsonl").write_bytes(result["results_bytes"])
    (derived / "manifest.json").write_bytes(result["manifest_bytes"])
    assert (
        checkpoint.validated_checkpoint(derived, settings(), pins())["completed"]
        == result["completed"]
    )


def replacement_fixture(tmp_path):
    from test_real_lifecycle import lease

    controller = importlib.import_module("real_controller")
    r = lease()
    r.update(status="debug-retained", instance=789, start_date=1010)
    hold = dict(r, pod="benchmark-old", pod_uid="pod-uid", namespace_uid="ns-uid")
    (tmp_path / "debug-hold.json").write_text(json.dumps(hold))
    namespace = {
        "metadata": {
            "name": r["namespace"],
            "uid": "ns-uid",
            "labels": {"kolibri-real": r["label"]},
        }
    }
    pod = {
        "metadata": {
            "name": "benchmark-old",
            "uid": "pod-uid",
            "namespace": r["namespace"],
            "ownerReferences": [
                {"kind": "Job", "name": "benchmark", "uid": "job-uid", "controller": True}
            ],
        },
        "spec": {
            "containers": [
                {"name": "runner"},
                {
                    "name": "tls-proxy",
                    "image": controller.IMAGE,
                    "command": [
                        "python",
                        "-I",
                        "/bundle/real_transport.py",
                        "/serving/transport.json",
                    ],
                    "volumeMounts": [
                        {"name": "work", "mountPath": "/work"},
                        {"name": "bundle", "mountPath": "/bundle", "readOnly": True},
                        {"name": "serving", "mountPath": "/serving", "readOnly": True},
                    ],
                },
            ],
            "volumes": [
                {"name": "work", "emptyDir": {}},
                {"name": "bundle", "configMap": {"name": "bundle"}},
                {"name": "serving", "secret": {"secretName": "serving"}},
            ],
        },
        "status": {
            "containerStatuses": [
                {
                    "name": "runner",
                    "state": {"terminated": {"reason": "OOMKilled", "exitCode": 137}},
                },
                {"name": "tls-proxy", "state": {"running": {}}, "ready": True},
            ]
        },
    }
    job = {
        "metadata": {
            "name": "benchmark",
            "uid": "job-uid",
            "namespace": r["namespace"],
            "resourceVersion": "1",
        }
    }

    class Kube:
        def get(self, ns, kind, name):
            if kind == "configmap":
                return {
                    "immutable": True,
                    "data": {
                        "real_transport.py": (controller.BASE / "real_transport.py").read_text()
                    },
                }
            return {"namespace": namespace, "pod": pod, "job": job}[kind]

    return controller, r, Kube(), pod, namespace


@pytest.mark.parametrize(
    "fault", ["pod-uid", "namespace", "running", "proxy", "owner", "bundle", "proxy-path"]
)
def test_owned_dead_runner_rejects_foreign_or_live(tmp_path, fault):
    c, r, kube, pod, ns = replacement_fixture(tmp_path)
    if fault == "pod-uid":
        pod["metadata"]["uid"] = "foreign"
    if fault == "namespace":
        ns["metadata"]["labels"]["kolibri-real"] = "foreign"
    if fault == "running":
        pod["status"]["containerStatuses"][0]["state"] = {"running": {}}
    if fault == "proxy":
        pod["spec"]["containers"][1]["command"] = ["python", "untrusted.py"]
    if fault == "owner":
        pod["metadata"]["ownerReferences"][0]["uid"] = "foreign"
    if fault == "proxy-path":
        pod["spec"]["containers"][1]["env"] = [{"name": "PYTHONPATH", "value": "/work"}]
    if fault == "bundle":
        old = kube.get
        kube.get = (
            lambda n, k, name: {"immutable": False, "data": {"real_transport.py": "foreign"}}
            if k == "configmap"
            else old(n, k, name)
        )
    with pytest.raises(ValueError):
        c.owned_dead_runner(kube, r, tmp_path)


def test_owned_dead_runner_rejects_immutable_foreign_proxy_source(tmp_path):
    c, r, kube, pod, ns = replacement_fixture(tmp_path)
    old_get = kube.get
    kube.get = (
        lambda n, k, name: {"immutable": True, "data": {"real_transport.py": "foreign"}}
        if k == "configmap"
        else old_get(n, k, name)
    )
    with pytest.raises(ValueError, match="untrusted immutable proxy source"):
        c.owned_dead_runner(kube, r, tmp_path)


def test_dead_runner_export_failure_never_deletes_or_stages(monkeypatch, tmp_path):
    c, r, kube, pod, ns = replacement_fixture(tmp_path)
    calls = []

    def fail(*a, **kw):
        calls.append("export")
        raise RuntimeError("export failed")

    monkeypatch.setattr(c, "export_namespace", fail)
    with pytest.raises(RuntimeError, match="export failed"):
        c.prepare_dead_runner(kube, r, tmp_path, {}, check_active=lambda: calls.append("gate"))
    assert calls == ["gate", "export"]
    assert not (tmp_path / "checkpoint-source").exists()


@pytest.mark.parametrize("tamper", [False, True])
def test_dead_runner_freezes_raw_and_verified_seed_before_replacement(
    monkeypatch, tmp_path, tamper
):
    c, r, kube, pod, ns = replacement_fixture(tmp_path)

    def export(k, rec, old, directory, **kw):
        assert kw["bounded"] is True
        assert old == "benchmark-old"
        seed(
            directory / "unused", [row(day=d, error="OOM" if d == 2 else None) for d in range(1, 5)]
        )
        for name in ("results.jsonl", "manifest.json"):
            (directory / name).write_bytes((directory / "unused" / name).read_bytes())
        (directory / "namespace-export.json").write_text('{"complete":true}')
        inventory = {
            name: {
                "size": (directory / name).stat().st_size,
                "sha256": hashlib.sha256((directory / name).read_bytes()).hexdigest(),
            }
            for name in ("results.jsonl", "manifest.json")
        }
        if tamper:
            inventory["results.jsonl"]["sha256"] = "0" * 64
        (directory / "artifact-export.json").write_text(json.dumps(inventory))

    monkeypatch.setattr(c, "export_namespace", export)
    if tamper:
        with pytest.raises(ValueError, match="export hash"):
            c.prepare_dead_runner(kube, r, tmp_path, {}, check_active=lambda: None)
        return
    binding, payload = c.prepare_dead_runner(kube, r, tmp_path, {}, check_active=lambda: None)
    assert binding["pod_uid"] == "pod-uid"
    assert c.recover_checkpoint(tmp_path) == payload
    raw = tmp_path / "dead-runner-pod-uid" / "results.jsonl"
    assert len(raw.read_bytes().splitlines()) == 4
    assert raw.stat().st_mode & 0o777 == 0o400
    assert len(dict(payload)["results.jsonl"].splitlines()) == 3


@pytest.mark.parametrize("gate_fault", [False, True])
def test_owned_deploy_deletes_only_after_verified_seed_and_preserves_binding(
    monkeypatch, tmp_path, gate_fault
):
    c, r, kube, pod, ns = replacement_fixture(tmp_path)
    r["deadline"] = 2000
    hold = json.loads((tmp_path / "debug-hold.json").read_text())
    hold["deadline"] = 2000
    (tmp_path / "debug-hold.json").write_text(json.dumps(hold))
    source = seed(tmp_path / "source", [row(day=1)])
    payload = c.prepare_checkpoint(source, tmp_path)
    binding = c.owned_dead_runner(kube, r, tmp_path)
    (tmp_path / "replacement-ready.json").write_text(
        json.dumps({"binding": binding, "instance": 789, "deadline": 2000})
    )
    calls = []
    old_get = kube.get
    config = {"host": "8.8.8.8", "port": 12345, "cert": "CERT", "api_key": "a" * 64}
    import base64

    def get(n, k, name):
        if k == "secret":
            return {
                "immutable": True,
                "data": {"transport.json": base64.b64encode(json.dumps(config).encode()).decode()},
            }
        if k == "configmap" and name.startswith("bundle-"):
            return None
        if calls and k in {"pod", "job"}:
            return None
        return old_get(n, k, name)

    kube.get = get

    class Started(RuntimeError):
        pass

    def call(*args, **kw):
        data = kw.get("data", {})
        calls.append((args, data))
        if data.get("kind") == "Job":
            assert data["spec"]["activeDeadlineSeconds"] == 1000
            runner = data["spec"]["template"]["spec"]["containers"][0]
            assert runner["resources"]["limits"]["memory"] == "8Gi"
            assert data["spec"]["template"]["spec"]["volumes"][0]["configMap"]["name"].startswith(
                "bundle-"
            )
            raise Started("CPU job started")
        return ""

    kube.call = call
    monkeypatch.setattr(c.time, "time", lambda: 1000)
    monkeypatch.setattr(
        c.socket, "getaddrinfo", lambda *a: [(None, None, None, None, ("1.1.1.1", 443))]
    )
    monkeypatch.setattr(c, "bundle_archive", lambda: b"public")

    def gate():
        if gate_fault:
            raise RuntimeError("billing gate rejected")

    with pytest.raises(
        RuntimeError, match="billing gate rejected" if gate_fault else "CPU job started"
    ):
        c.deploy(
            kube, r, config, tmp_path, checkpoint=payload, owned_replace=binding, check_active=gate
        )
    if gate_fault:
        assert calls == []
    else:
        deletion = calls[0][1]
        assert deletion["preconditions"] == {"uid": "job-uid", "resourceVersion": "1"}
        assert not any(data.get("kind") in {"Namespace", "Secret"} for _, data in calls)
    assert r["deadline"] == 2000 and r["instance"] == 789


def test_explicit_replace_resume_never_rents_and_exports_before_deploy(monkeypatch, tmp_path):
    resume = importlib.import_module("real_resume")
    observed = []

    class Observe(pytest.MonkeyPatch):
        def setattr(self, target, name, value, *a, **kw):
            if target is resume and name == "deploy":

                def replacement(k, r, c, d, **opts):
                    assert observed == ["export-verified"]
                    assert opts["owned_replace"] == {"pod": "pod", "pod_uid": "offline"}
                    assert opts["checkpoint"] == (("results.jsonl", b""), ("manifest.json", b"{}"))
                    # Delegate fixture's existing no-create deployment assertion in nonretained mode.
                    return "pod"

                value = replacement
            return super().setattr(target, name, value, *a, **kw)

    from test_real_resume import test_resume_existing_instance_preserves_deadline_and_never_launches

    with Observe.context() as patcher:
        patcher.setattr(
            resume, "owned_dead_runner", lambda *a: {"pod": "pod", "pod_uid": "offline"}
        )

        def prepare(*a, **kw):
            kw["check_active"]()
            observed.append("export-verified")
            return {"pod": "pod", "pod_uid": "offline"}, (
                ("results.jsonl", b""),
                ("manifest.json", b"{}"),
            )

        patcher.setattr(resume, "prepare_dead_runner", prepare)
        test_resume_existing_instance_preserves_deadline_and_never_launches(
            patcher, tmp_path, True, False, True, replacement=True
        )
    assert observed == ["export-verified"]


def test_runner_uses_bounded_rlimit_backend_only_campaign():
    c = importlib.import_module("real_controller")
    resources = c.resources(
        "kolibri-real-" + "a" * 12,
        "hermes-kolibri-" + "b" * 32,
        {"host": "8.8.8.8", "port": 12345},
        ["1.1.1.1"],
    )
    runner = resources[-1]["spec"]["template"]["spec"]["containers"][0]
    env = {entry["name"]: entry["value"] for entry in runner["env"]}
    assert env["EXECUTION_SANDBOX"] == "rlimit"
    assert env["EXECUTION_MEMORY_MB"] == "4096"


@pytest.mark.parametrize("fault", ["credit", "rate", "ttl"])
def test_replacement_billing_fault_prevents_cpu_deletion(monkeypatch, tmp_path, fault):
    resume = importlib.import_module("real_resume")
    from test_real_resume import test_resume_existing_instance_preserves_deadline_and_never_launches

    observed = []

    class Observe(pytest.MonkeyPatch):
        def setattr(self, target, name, value, *a, **kw):
            if target is resume and name == "Vast":
                factory = value

                def provider():
                    obj = factory()
                    observed.append(obj)
                    return obj

                value = provider
            elif target is resume and name == "deploy":

                def value(*a, **kw):
                    pytest.fail("billing fault must prevent deployment/deletion")

            return super().setattr(target, name, value, *a, **kw)

    with Observe.context() as patcher:
        patcher.setattr(
            resume, "owned_dead_runner", lambda *a: {"pod": "pod", "pod_uid": "offline"}
        )

        def prepare(k, r, d, c, *, check_active):
            if fault == "credit":
                observed[0].credit = 0
            elif fault == "rate":
                observed[0].rows[0]["dph_total"] = 4.5
            else:
                patcher.setattr(resume.time, "time", lambda: r["deadline"])
            check_active()
            pytest.fail("billing fault did not reject")

        patcher.setattr(resume, "prepare_dead_runner", prepare)
        test_resume_existing_instance_preserves_deadline_and_never_launches(
            patcher, tmp_path, True, True, True, replacement=True, expected_bounded_cleanup=True
        )

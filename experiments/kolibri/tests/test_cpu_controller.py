"""Offline controller regressions: kubectl is mocked, never contacted."""

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

controller = importlib.import_module("cpu_rehearsal")


class Cluster:
    def __init__(self, *, foreign=False, cleanup_failure=False):
        self.namespace = None
        self.calls = []
        self.foreign = foreign
        self.cleanup_failure = cleanup_failure

    def run(self, cmd, **kwargs):
        args = cmd[2:]
        self.calls.append((args, kwargs.get("input")))
        result = ""
        if "deploy" in args:
            result = json.dumps(
                {
                    "metadata": {"uid": "broker", "generation": 1},
                    "spec": {"template": {"spec": {"containers": [{"image": "unchanged"}]}}},
                }
            )
        elif args[0] == "get" and args[1].lower() == "namespace":
            if self.namespace:
                result = (
                    json.dumps(self.namespace)
                    if args[-1] == "json"
                    else "namespace/" + self.namespace["metadata"]["name"]
                )
        elif args[0] == "create":
            obj = json.loads(kwargs["input"])["items"][0]
            assert obj["kind"] == "Namespace"
            self.namespace = {
                **obj,
                "metadata": {**obj["metadata"], "uid": "owned-uid", "resourceVersion": "1"},
            }
            if self.foreign:
                self.namespace["metadata"]["labels"]["kolibri-rehearsal"] = "foreign"
            raise subprocess.TimeoutExpired(cmd, 60)
        elif args[0] == "delete":
            if self.cleanup_failure:
                raise RuntimeError("mock cleanup failed")
            self.namespace = None
        elif args[0] == "wait":
            assert self.namespace is None
        elif args[:3] == ["-n", "kolibri-cpu-abcdef", "get"]:
            result = '{"items": []}'
        else:
            raise AssertionError(args)
        return subprocess.CompletedProcess(cmd, 0, result, "")


def invoke(monkeypatch, tmp_path, cluster):
    monkeypatch.setattr(controller, "BASE", tmp_path)
    monkeypatch.setattr(controller.secrets, "token_hex", lambda n: "abcdef")
    monkeypatch.setattr(
        controller.socket,
        "getaddrinfo",
        lambda *a: [(None, None, None, None, ("151.101.0.223", 443))],
    )
    monkeypatch.setattr(controller.subprocess, "run", cluster.run)
    monkeypatch.setattr(sys, "argv", ["cpu_rehearsal.py", "--execute-cpu"])
    controller.main()


def test_accepted_namespace_create_timeout_still_cleans_exact_namespace(monkeypatch, tmp_path):
    cluster = Cluster()
    with pytest.raises(subprocess.TimeoutExpired):
        invoke(monkeypatch, tmp_path, cluster)
    assert cluster.namespace is None, "accepted create must reconcile cleanup after client timeout"
    deletes = [(a, data) for a, data in cluster.calls if a[0] == "delete"]
    assert json.loads(deletes[0][1])["preconditions"] == {
        "uid": "owned-uid",
        "resourceVersion": "1",
    }
    report = json.loads((tmp_path / "evidence/kolibri-cpu-abcdef/summary.json").read_text())
    assert report["status"] == "failed" and report["namespace_absent"]


def test_foreign_namespace_is_preserved_after_ambiguous_create(monkeypatch, tmp_path):
    cluster = Cluster(foreign=True)
    with pytest.raises(RuntimeError, match="ownership mismatch"):
        invoke(monkeypatch, tmp_path, cluster)
    assert cluster.namespace is not None
    assert not any(a[0] == "delete" for a, _ in cluster.calls)
    report = json.loads((tmp_path / "evidence/kolibri-cpu-abcdef/summary.json").read_text())
    assert report["status"] == "failed" and report["namespace_absent"] is False


def test_cleanup_failure_retains_failed_summary(monkeypatch, tmp_path):
    cluster = Cluster(cleanup_failure=True)
    with pytest.raises(RuntimeError, match="cleanup failed"):
        invoke(monkeypatch, tmp_path, cluster)
    report = json.loads((tmp_path / "evidence/kolibri-cpu-abcdef/summary.json").read_text())
    assert report["status"] == "failed" and report["namespace_absent"] is False
    assert report["error_type"] == "TimeoutExpired"
    assert report["cleanup_error_type"] == "RuntimeError"


class ProbeCluster(Cluster):
    def __init__(self, *, positive_available=False, negative_unavailable=False):
        super().__init__()
        self.objects = {}
        self.positive_available = positive_available
        self.negative_unavailable = negative_unavailable
        self.probe_count = 0
        self.released = False
        self.record = None

    def run(self, cmd, **kwargs):
        import ast
        import re

        args = cmd[2:]
        if args[0] == "create":
            self.calls.append((args, kwargs.get("input")))
            for obj in json.loads(kwargs["input"])["items"]:
                obj["metadata"].update(uid="owned-uid", resourceVersion="1")
                if obj["kind"] == "Namespace":
                    self.namespace = obj
                else:
                    self.objects[(obj["kind"].lower(), obj["metadata"]["name"])] = obj
                    if obj["kind"] == "Service":
                        obj["spec"]["clusterIP"] = "10.43.1.2"
                    if obj["metadata"]["name"] == "cpu-record":
                        self.record = json.loads(obj["data"]["record.json"])
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if "exec" in args:
            self.calls.append((args, kwargs.get("input")))
            script = args[-1]
            if "audit" in script:
                result = {"attempts": 0, "remaining": {"fake-1": self.record}}
            elif "released" in script:
                self.released = True
                result = None
            elif "tcp_probe(" in script or "for name,host,port in " in script:
                expression = re.search(r"tcp_probe\((\[.*\])\)", script)
                if expression:
                    targets = ast.literal_eval(expression.group(1))
                else:
                    targets = ast.literal_eval(
                        script.split("for name,host,port in ")[1].split(":\n")[0]
                    )
                self.probe_count += 1
                connected = self.positive_available and self.probe_count == 1
                result = [
                    {
                        "name": n,
                        "host": h,
                        "port": p,
                        "connected": connected,
                        "denial_candidate": not self.negative_unavailable,
                        "errno": 111,
                    }
                    for n, h, p in targets
                ]
            else:
                result = None
            return subprocess.CompletedProcess(cmd, 0, json.dumps(result), "")
        if "get" in args and "namespace" not in [a.lower() for a in args] and "deploy" not in args:
            self.calls.append((args, kwargs.get("input")))
            index = args.index("get")
            kind = args[index + 1].lower()
            name = args[index + 2] if args[index + 2] != "-l" and args[index + 2] != "-o" else None
            namespace = args[args.index("-n") + 1]
            if kind in {"svc", "service", "endpoints"} and namespace != "kolibri-cpu-abcdef":
                api = name == "kubernetes"
                if kind == "endpoints":
                    obj = {
                        "subsets": [
                            {
                                "addresses": [{"ip": "192.168.178.4" if api else "10.42.0.7"}],
                                "ports": [
                                    {
                                        "name": "https" if api else "http",
                                        "port": 6443 if api else 8080,
                                        "protocol": "TCP",
                                    }
                                ],
                            }
                        ]
                    }
                else:
                    obj = {
                        "spec": {
                            "clusterIP": "10.43.0.1" if api else "10.43.212.37",
                            "ports": [
                                {
                                    "name": "https" if api else "http",
                                    "port": 443 if api else 8000,
                                    "protocol": "TCP",
                                }
                            ],
                        }
                    }
            elif kind == "pods":
                roles = (
                    [args[args.index("-l") + 1].removeprefix("role=")]
                    if "-l" in args
                    else ["runner", "provider"]
                )
                obj = {
                    "items": [
                        {
                            "metadata": {"name": role + "-pod"},
                            "status": {
                                "podIP": "10.42.0.8",
                                "conditions": [{"type": "Ready", "status": "True"}],
                            },
                        }
                        for role in roles
                    ]
                }
            elif name is None:
                obj = {"items": list(self.objects.values())}
            else:
                kind = {"svc": "service"}.get(kind, kind)
                obj = self.objects.get((kind, name))
                if obj is None and "--ignore-not-found" in args:
                    return subprocess.CompletedProcess(cmd, 0, "", "")
                assert obj is not None, args
            return subprocess.CompletedProcess(cmd, 0, json.dumps(obj), "")
        if args[:3] == ["-n", "kolibri-cpu-abcdef", "delete"]:
            self.calls.append((args, kwargs.get("input")))
            for name in args[4:]:
                self.objects.pop(("networkpolicy", name), None)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if "wait" in args and "job/cpu-runner" in args:
            raise RuntimeError("mock stop after release")
        return super().run(cmd, **kwargs)


def prepare_bundle(tmp_path):
    for name in (
        "run.py",
        "cpu_fixture.py",
        "cpu_probe.py",
        "cpu_watchdog.py",
        "cpu_fake_provider.py",
        "cpu-runtime.lock",
    ):
        (tmp_path / name).write_bytes((BASE / name).read_bytes())


def test_unavailable_positive_control_never_releases_runner(monkeypatch, tmp_path):
    prepare_bundle(tmp_path)
    cluster = ProbeCluster()
    with pytest.raises(RuntimeError):
        invoke(monkeypatch, tmp_path, cluster)
    assert not cluster.released, "unreachable baseline must not count as isolation"
    assert cluster.namespace is None


def test_broker_without_safe_ingress_control_is_explicitly_unverified(monkeypatch, tmp_path):
    prepare_bundle(tmp_path)
    cluster = ProbeCluster(positive_available=True)
    with pytest.raises(RuntimeError, match="stop after release"):
        invoke(monkeypatch, tmp_path, cluster)
    positive = json.loads(
        (tmp_path / "evidence/kolibri-cpu-abcdef/positive-controls.json").read_text()
    )
    assert all(not p["name"].startswith("private-broker") for p in positive)
    report = json.loads((tmp_path / "evidence/kolibri-cpu-abcdef/summary.json").read_text())
    assert len(report["unverified_isolation_targets"]) == 2
    assert all(t[0].startswith("private-broker") for t in report["unverified_isolation_targets"])
    assert cluster.namespace is None


def test_unavailable_negative_probe_never_releases_runner(monkeypatch, tmp_path):
    prepare_bundle(tmp_path)
    cluster = ProbeCluster(positive_available=True, negative_unavailable=True)
    with pytest.raises(RuntimeError, match="denial"):
        invoke(monkeypatch, tmp_path, cluster)
    assert not cluster.released
    assert cluster.namespace is None


def test_release_requires_readback_of_all_temporary_policy_revocations(monkeypatch, tmp_path):
    prepare_bundle(tmp_path)
    cluster = ProbeCluster(positive_available=True)
    with pytest.raises(RuntimeError, match="stop after release"):
        invoke(monkeypatch, tmp_path, cluster)
    release = next(
        i
        for i, (a, _) in enumerate(cluster.calls)
        if "exec" in a and "Path('/work/released').touch()" in a[-1]
    )
    for name in ("install-public", "control-exact-egress", "control-provider-ingress"):
        assert any(
            "get" in a and name in a and "--ignore-not-found" in a
            for a, _ in cluster.calls[:release]
        )
    controls = [
        json.loads(data)["items"]
        for a, data in cluster.calls
        if a[0] == "create" and "control-exact-egress" in data
    ]
    egress = next(o for o in controls[0] if o["metadata"]["name"] == "control-exact-egress")[
        "spec"
    ]["egress"]
    assert all(len(r["to"]) == 1 and r["to"][0]["ipBlock"]["cidr"].endswith("/32") for r in egress)
    assert all(len(r["ports"]) == 1 and r["ports"][0]["protocol"] == "TCP" for r in egress)


def test_same_label_replacement_uid_is_never_deleted(monkeypatch, tmp_path):
    prepare_bundle(tmp_path)

    class ReplacedCluster(ProbeCluster):
        def run(self, cmd, **kwargs):
            if cmd[2:4] == ["get", "namespace"] and self.released:
                self.namespace["metadata"]["uid"] = "foreign-replacement"
            return super().run(cmd, **kwargs)

    cluster = ReplacedCluster(positive_available=True)
    with pytest.raises(RuntimeError, match="ownership mismatch"):
        invoke(monkeypatch, tmp_path, cluster)
    assert cluster.namespace["metadata"]["uid"] == "foreign-replacement"
    assert not any(a[0] == "delete" for a, _ in cluster.calls)

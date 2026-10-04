"""Opt-in isolated CPU rehearsal; never calls Vast or a real inference API."""

import argparse
import base64
import hashlib
import io
import json
import os
import secrets
import socket
import subprocess
import tarfile
import time
from pathlib import Path

from cpu_k8s import IMAGE, resources
from cpu_probe import require_controls, require_denied

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-cpu", action="store_true")
    args = parser.parse_args()
    if args.execute_cpu and not __debug__:
        parser.error("optimized Python disables verification assertions; execution refused")
    if not args.execute_cpu:
        print(
            json.dumps(
                {
                    "execution": False,
                    "inference": False,
                    "provider": "fake",
                    "image": IMAGE,
                    "jobs": ["runner", "provider", "watchdog"],
                    "max_seconds": 600,
                }
            )
        )
        return
    ns = "kolibri-cpu-" + secrets.token_hex(6)
    out = BASE / "evidence" / ns
    out.mkdir(parents=True, exist_ok=False)
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/opt/data"),
        "KUBECONFIG": "/opt/kube/config",
    }
    commands = []

    def kube(*args, data=None, timeout=60, check=True):
        cmd = ["kubectl", "--kubeconfig=/opt/kube/config", *args]
        proc = subprocess.run(
            cmd,
            input=None if data is None else json.dumps(data),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        commands.append({"args": list(args), "returncode": proc.returncode})
        (out / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
        if check and proc.returncode:
            raise RuntimeError(proc.stderr[:2000])
        return proc

    def read(kind, name=None):
        return json.loads(
            kube("-n", ns, "get", kind, *([name] if name else []), "-o", "json").stdout
        )

    def apply(objects):
        nonlocal owned, namespace_attempted, namespace_uid
        if any(o["kind"] == "Namespace" for o in objects):
            namespace_attempted = True  # server may accept even if the client times out
        kube("create", "-f", "-", data={"apiVersion": "v1", "kind": "List", "items": objects})
        for obj in objects:
            kind, name = obj["kind"], obj["metadata"]["name"]
            target = json.loads(
                kube(
                    "get", kind, name, *([] if kind == "Namespace" else ["-n", ns]), "-o", "json"
                ).stdout
            )
            assert target["metadata"]["name"] == name
            if kind == "Namespace":
                assert target["metadata"]["labels"]["kolibri-rehearsal"] == record["owner"]
                namespace_uid = target["metadata"]["uid"]
                owned = True
            if kind != "Namespace":
                assert target["metadata"]["namespace"] == ns

    def pod(role, *, ready=True):
        until = time.monotonic() + 330
        while time.monotonic() < until:
            items = json.loads(
                kube("-n", ns, "get", "pods", "-l", "role=" + role, "-o", "json").stdout
            )["items"]
            if items:
                item = items[0]
                if not ready or any(
                    c.get("type") == "Ready" and c.get("status") == "True"
                    for c in item.get("status", {}).get("conditions", [])
                ):
                    return item["metadata"]["name"]
                if item.get("status", {}).get("phase") == "Failed":
                    raise RuntimeError("job failed before readiness: " + role)
            time.sleep(2)
        raise RuntimeError("job readiness timeout: " + role)

    def execute(target, script):
        return kube("-n", ns, "exec", target, "--", "python", "-c", script).stdout

    def broker_snapshot():
        d = json.loads(
            kube(
                "-n",
                "ephemeral-compute-broker",
                "get",
                "deploy",
                "ephemeral-compute-broker",
                "-o",
                "json",
            ).stdout
        )
        return {
            "uid": d["metadata"]["uid"],
            "generation": d["metadata"]["generation"],
            "spec_sha256": hashlib.sha256(
                json.dumps(d["spec"], sort_keys=True).encode()
            ).hexdigest(),
            "image": d["spec"]["template"]["spec"]["containers"][0]["image"],
        }

    owned = False
    namespace_attempted = False
    namespace_uid = None
    before = broker_snapshot()
    report = {
        "namespace": ns,
        "provider": "fake",
        "inference": False,
        "status": "running",
        "image": IMAGE,
    }
    try:
        existing = kube("get", "namespace", ns, "--ignore-not-found", "-o", "name").stdout.strip()
        assert not existing, "never reuse an existing namespace"
        ips = sorted(
            {
                x[4][0]
                for host in ("pypi.org", "files.pythonhosted.org")
                for x in socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
            }
        )
        record = {
            "provider": "fake",
            "instance": "fake-1",
            "owner": "kolibri-" + ns,
            "lease": "lease-" + secrets.token_hex(6),
            "created": time.time(),
            "deadline": time.time() + 30,
        }
        objects = resources(ns, record, ips)
        initial = [o for o in objects if o["kind"] != "Job"]
        jobs = {o["metadata"]["name"]: o for o in objects if o["kind"] == "Job"}
        apply([initial[0]])
        apply(initial[1:])
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w:gz") as tar:
            for path in sorted((ROOT / "src/aoc_agent").rglob("*.py")):
                if path.is_symlink():
                    raise ValueError("source symlink forbidden")
                tar.add(path, arcname=str(path.relative_to(ROOT / "src")), recursive=False)
        bundle = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "cpu-bundle", "namespace": ns},
            "immutable": True,
            "data": {
                name: (BASE / name).read_text()
                for name in (
                    "run.py",
                    "cpu_fixture.py",
                    "cpu_probe.py",
                    "cpu_watchdog.py",
                    "cpu_fake_provider.py",
                )
            },
            "binaryData": {
                "source.tar.gz": base64.b64encode(archive.getvalue()).decode(),
                "requirements.txt": base64.b64encode(
                    (BASE / "cpu-runtime.lock").read_bytes()
                ).decode(),
            },
        }
        apply([bundle])
        targets = []
        discovery = {}
        for label, namespace, name in (
            ("kubernetes-api", "default", "kubernetes"),
            ("private-broker", "ephemeral-compute-broker", "ephemeral-compute-broker-internal"),
        ):
            service = json.loads(kube("-n", namespace, "get", "svc", name, "-o", "json").stdout)
            endpoints = json.loads(
                kube("-n", namespace, "get", "endpoints", name, "-o", "json").stdout
            )
            discovery[label] = {"service": service, "endpoints": endpoints}
            ports = [p for p in service["spec"]["ports"] if p.get("protocol", "TCP") == "TCP"]
            assert len(ports) == 1, "ambiguous service port; refuse to guess"
            port = ports[0]
            targets.append([label, service["spec"]["clusterIP"], port["port"]])
            backend = sorted(
                {
                    (a["ip"], p["port"])
                    for subset in endpoints.get("subsets", [])
                    for a in subset.get("addresses", [])
                    for p in subset["ports"]
                    if p.get("protocol", "TCP") == "TCP"
                    and p.get("name", "") == port.get("name", "")
                }
            )
            assert backend, "no ready backend TCP endpoint"
            # Bound the number of probes and never widen to whole private CIDRs.
            assert len(backend) <= 2, "too many backend endpoints for bounded rehearsal"
            targets.extend(
                [[label + "-endpoint-" + str(i), ip, p] for i, (ip, p) in enumerate(backend)]
            )
        fake_service = read("svc", "fake-provider")
        targets.extend(
            [
                ["provider-control-plane", fake_service["spec"]["clusterIP"], 8081],
                ["public-pypi", ips[0], 443],
            ]
        )
        assert len(targets) <= 6, "probe deadline budget exceeded"
        all_targets = targets
        broker_targets = [t for t in all_targets if t[0].startswith("private-broker")]
        targets = [t for t in all_targets if t not in broker_targets]
        # Production broker ingress admits only existing production namespaces.
        # Do not change it or spoof its callers to manufacture a positive control.
        discovery["private-broker"]["networkpolicies"] = json.loads(
            kube("-n", "ephemeral-compute-broker", "get", "networkpolicy", "-o", "json").stdout
        )
        report["unverified_isolation_targets"] = broker_targets
        report["unverified_isolation_reason"] = (
            "broker ingress cannot be safely controlled within dedicated-namespace-only write scope"
        )
        (out / "target-discovery.json").write_text(json.dumps(discovery, indent=2) + "\n")
        jobs["cpu-runner"]["spec"]["template"]["spec"]["containers"][0]["env"].append(
            {"name": "DENIED_TARGETS", "value": json.dumps(targets)}
        )
        (out / "requested-resources.json").write_text(
            json.dumps({"items": objects}, indent=2) + "\n"
        )
        (out / "bundle-manifest.json").write_text(
            json.dumps(
                {
                    "source_sha256": hashlib.sha256(archive.getvalue()).hexdigest(),
                    "requirements_sha256": hashlib.sha256(
                        (BASE / "cpu-runtime.lock").read_bytes()
                    ).hexdigest(),
                    "script_sha256": {
                        n: hashlib.sha256((BASE / n).read_bytes()).hexdigest()
                        for n in bundle["data"]
                    },
                    "public_install_ips": ips,
                },
                indent=2,
            )
            + "\n"
        )
        apply([jobs["cpu-runner"]])
        runner = pod("runner")
        # No generated code executes while init has egress. Gate stays shut.
        kube("-n", ns, "delete", "networkpolicy", "install-public", "--wait=true")
        assert not kube(
            "-n", ns, "get", "networkpolicy", "install-public", "--ignore-not-found", "-o", "name"
        ).stdout.strip()
        policies = read("networkpolicy")
        (out / "runtime-networkpolicies.json").write_text(json.dumps(policies, indent=2) + "\n")
        # Start provider independently only after runtime packages are ready.
        now = time.time()
        record.update(created=now, deadline=now + 90)
        binding = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "cpu-record", "namespace": ns},
            "immutable": True,
            "data": {"record.json": json.dumps(record)},
        }
        apply([binding, jobs["cpu-provider"]])
        provider = pod("provider")
        audit_script = "import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8081/audit',timeout=3))))"
        initial_audit = json.loads(execute(provider, audit_script))
        assert initial_audit["attempts"] == 0 and initial_audit["remaining"]["fake-1"] == record
        (out / "fake-provider-before.json").write_text(json.dumps(initial_audit, indent=2) + "\n")
        # Trusted TCP-only reachability control while the model-code gate is shut.
        # Include exact backend IP/port to handle Service DNAT, not private CIDRs.
        provider_ip = next(
            p["status"]["podIP"] for p in read("pods")["items"] if p["metadata"]["name"] == provider
        )
        control_targets = [*all_targets, ["provider-backend", provider_ip, 8081]]
        control = {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {"name": "control-exact-egress", "namespace": ns},
            "spec": {
                "podSelector": {"matchLabels": {"role": "runner"}},
                "policyTypes": ["Egress"],
                "egress": [
                    {
                        "to": [{"ipBlock": {"cidr": host + "/32"}}],
                        "ports": [{"port": port, "protocol": "TCP"}],
                    }
                    for _, host, port in control_targets
                ],
            },
        }
        provider_control = {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {"name": "control-provider-ingress", "namespace": ns},
            "spec": {
                "podSelector": {"matchLabels": {"role": "provider"}},
                "policyTypes": ["Ingress"],
                "ingress": [
                    {
                        "from": [{"podSelector": {"matchLabels": {"role": "runner"}}}],
                        "ports": [{"port": 8081, "protocol": "TCP"}],
                    }
                ],
            },
        }
        apply([control, provider_control])
        (out / "control-networkpolicies.json").write_text(
            json.dumps(read("networkpolicy"), indent=2) + "\n"
        )
        preprobe = (
            "import json; from cpu_probe import tcp_probe; print(json.dumps(tcp_probe("
            + repr(all_targets)
            + ")))"
        )
        control_probes = json.loads(execute(runner, preprobe))
        positive = [p for p in control_probes if not p["name"].startswith("private-broker")]
        (out / "positive-controls.json").write_text(json.dumps(positive, indent=2) + "\n")
        require_controls(targets, positive)
        kube(
            "-n",
            ns,
            "delete",
            "networkpolicy",
            "control-exact-egress",
            "control-provider-ingress",
            "--wait=true",
        )
        for name in ("install-public", "control-exact-egress", "control-provider-ingress"):
            assert not kube(
                "-n", ns, "get", "networkpolicy", name, "--ignore-not-found", "-o", "name"
            ).stdout.strip()
        (out / "runtime-networkpolicies.json").write_text(
            json.dumps(read("networkpolicy"), indent=2) + "\n"
        )
        apply([jobs["cpu-watchdog"]])
        watchdog = pod("watchdog", ready=False)
        # Fresh negative attempts on exactly the same IP/ports after revocation.
        negative_probes = json.loads(execute(runner, preprobe))
        pre = [p for p in negative_probes if not p["name"].startswith("private-broker")]
        (out / "unverified-broker-probes.json").write_text(
            json.dumps(
                {
                    "isolation_proven": False,
                    "control_phase": [
                        p for p in control_probes if p["name"].startswith("private-broker")
                    ],
                    "restricted_phase": [
                        p for p in negative_probes if p["name"].startswith("private-broker")
                    ],
                },
                indent=2,
            )
            + "\n"
        )
        (out / "pre-release-denied-probes.json").write_text(json.dumps(pre, indent=2) + "\n")
        require_denied(targets, pre, positive)
        execute(
            runner,
            "from pathlib import Path; Path('/work/positive-controls.json').write_text("
            + repr(json.dumps(positive))
            + ")",
        )
        execute(runner, "from pathlib import Path; Path('/work/released').touch()")
        kube(
            "-n",
            ns,
            "wait",
            "--for=condition=failed",
            "job/cpu-runner",
            "--timeout=150s",
            timeout=165,
        )
        kube(
            "-n",
            ns,
            "wait",
            "--for=condition=complete",
            "job/cpu-watchdog",
            "--timeout=150s",
            timeout=165,
        )
        pods = read("pods")
        (out / "live-pods.json").write_text(json.dumps(pods, indent=2) + "\n")
        (out / "live-jobs.json").write_text(json.dumps(read("jobs"), indent=2) + "\n")
        for role, target in (
            ("runner", runner),
            ("provider", provider),
            ("watchdog", watchdog),
        ):
            logs = kube("-n", ns, "logs", target, "-c", role).stdout
            (out / (role + ".log")).write_text(logs)
        (out / "install.log").write_text(
            kube("-n", ns, "logs", runner, "-c", "install-public-deps").stdout
        )
        runner_log = (out / "runner.log").read_text()
        result = next(
            json.loads(line) for line in runner_log.splitlines() if line.startswith('{"model":')
        )
        assert result["jupyter"]["uid"] == 10001 and not result["jupyter"]["token_present"]
        assert (
            result["fixture_http_allowed"] and result["part1_correct"] and result["part2_correct"]
        )
        require_denied(targets, result["jupyter"]["denied_targets"], positive)
        row = next(
            line.removeprefix("RESULT_JSONL ")
            for line in runner_log.splitlines()
            if line.startswith("RESULT_JSONL ")
        )
        assert json.loads(row)["model"] == "SYNTHETIC_CPU_FIXTURE_NOT_KOLIBRI"
        (out / "synthetic-results.jsonl").write_text(row + "\n")
        final_audit = json.loads(execute(provider, audit_script))
        assert (
            final_audit["attempts"] == 3
            and "fake-1" not in final_audit["remaining"]
            and "fake-foreign" in final_audit["remaining"]
        )
        crash_event = next(
            json.loads(line)
            for line in runner_log.splitlines()
            if line.startswith('{"actual_agent_runner_crash":')
        )
        crash_pod = next(p for p in pods["items"] if p["metadata"]["name"] == runner)
        assert crash_pod["status"]["containerStatuses"][0]["state"]["terminated"]["exitCode"] == 42
        assert all(
            e["time"] >= record["deadline"] and e["time"] > crash_event["time"]
            for e in final_audit["events"]
        )
        absence = execute(
            provider,
            "import urllib.request,urllib.error,json\ntry: urllib.request.urlopen('http://127.0.0.1:8081/instances/fake-1',timeout=3); print(json.dumps({'absent':False}))\nexcept urllib.error.HTTPError as e: print(json.dumps({'absent':e.code==404,'status':e.code}))",
        )
        assert json.loads(absence) == {"absent": True, "status": 404}
        (out / "fake-provider-after.json").write_text(json.dumps(final_audit, indent=2) + "\n")
        (out / "exact-instance-readback.json").write_text(absence)
        report.update(
            status="passed",
            fixture_result=result,
            crash_exit=42,
            actual_agent_runner_crashed=True,
            fake_delete_attempts=3,
            exact_instance_absent=True,
            foreign_preserved=True,
            deadline=record["deadline"],
            isolation_controls=positive,
        )
    except BaseException as error:
        report.update(status="failed", error_type=type(error).__name__)
        if owned:
            for kind in ("pods", "jobs", "events"):
                try:
                    (out / ("failure-" + kind + ".json")).write_text(
                        json.dumps(read(kind), indent=2)
                    )
                except Exception:
                    pass
            try:
                for p in read("pods")["items"]:
                    for c in p["spec"].get("initContainers", []) + p["spec"]["containers"]:
                        proc = kube(
                            "-n", ns, "logs", p["metadata"]["name"], "-c", c["name"], check=False
                        )
                        (out / ("failure-" + c["name"] + ".log")).write_text(
                            proc.stdout + proc.stderr
                        )
            except Exception:
                pass
        raise
    finally:
        try:
            if namespace_attempted:
                raw = kube(
                    "get", "namespace", ns, "--ignore-not-found", "-o", "json"
                ).stdout.strip()
                if raw:
                    metadata = json.loads(raw)["metadata"]
                    if (
                        metadata["name"] != ns
                        or metadata.get("labels", {}).get("kolibri-rehearsal") != record["owner"]
                        or (namespace_uid is not None and metadata["uid"] != namespace_uid)
                    ):
                        raise RuntimeError(
                            "namespace ownership mismatch; foreign namespace preserved"
                        )
                    namespace_uid = metadata["uid"]
                    report["namespace_cleanup_binding"] = {
                        "name": ns,
                        "owner": record["owner"],
                        "uid": namespace_uid,
                    }
                    kube(
                        "delete",
                        "--raw",
                        "/api/v1/namespaces/" + ns,
                        "-f",
                        "-",
                        data={
                            "apiVersion": "v1",
                            "kind": "DeleteOptions",
                            "preconditions": {
                                "uid": namespace_uid,
                                "resourceVersion": metadata["resourceVersion"],
                            },
                        },
                    )
                    kube("wait", "--for=delete", "namespace/" + ns, "--timeout=120s", timeout=135)
                absent = kube(
                    "get", "namespace", ns, "--ignore-not-found", "-o", "name"
                ).stdout.strip()
                assert not absent, "namespace cleanup not verified"
                report["namespace_absent"] = True
        except BaseException as cleanup_error:
            report.update(
                status="failed",
                namespace_absent=False,
                cleanup_error_type=type(cleanup_error).__name__,
            )
            raise
        finally:
            try:
                after = broker_snapshot()
                assert before == after, "production broker spec changed during rehearsal"
                report["production_broker_unchanged"] = {"before": before, "after": after}
            except BaseException as verification_error:
                report.update(
                    status="failed",
                    broker_verification_error_type=type(verification_error).__name__,
                )
                raise
            finally:
                (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": report["status"],
                "evidence": str(out),
                "namespace_absent": report["namespace_absent"],
            }
        )
    )


if __name__ == "__main__":
    main()

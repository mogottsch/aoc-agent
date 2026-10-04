"""Trusted Kolibri controller; only --execute-approved rents or infers.

The CPU rehearsal deploys the same isolated pod but runs run.py preflight only.
"""

import argparse
import base64
import copy
import hashlib
import io
import ipaddress
import json
import os
import re
import secrets
import socket
import subprocess
import tarfile
import time
from collections.abc import Callable
from pathlib import Path

from diagnostics import private_write, redact, save_failure
from provider_logs import capture_provider_logs
from real_lifecycle import (
    DEFAULT_TTL_SECONDS,
    MAX_TTL_SECONDS,
    STATE,
    Vast,
    identity,
    launch_command,
    locked,
    read,
    reconcile,
    secure_dir,
    store,
    watchdog,
)
from real_transport import material, request

from cpu_k8s import IMAGE, PSC, SC  # isort: skip

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]


def publish_offline_receipt(directory, *, numpy_path=None):
    """Execute fixed offline checks, publishing proof only after all succeed.

    This producer's test evidence is never independent review, launch approval,
    watchdog evidence or proof that the real 50-row campaign completed.
    """
    directory = Path(directory).absolute()
    if ".." in directory.parts or any(p.is_symlink() for p in directory.parents):
        raise ValueError("unsafe offline receipt directory")
    directory.mkdir(mode=0o700)
    scoped = [
        "experiments/kolibri/real_runner.py",
        "experiments/kolibri/real_controller.py",
        "experiments/kolibri/real_resume.py",
        "experiments/kolibri/tests/test_runner_environment.py",
        "experiments/kolibri/tests/test_fresh_rental_checkpoint.py",
        "experiments/kolibri/tests/test_offline_receipt.py",
        "experiments/kolibri/tests/test_dead_runner_replacement.py",
    ]
    hashed = scoped + [
        "experiments/kolibri/run.py",
        "experiments/kolibri/checkpoint.py",
        "experiments/kolibri/real_transport.py",
        "experiments/kolibri/config.yaml",
        "experiments/kolibri/pins.json",
        "experiments/kolibri/cpu-ruff.toml",
        "src/aoc_agent/core/settings.py",
        "src/aoc_agent/adapters/execution/jupyter.py",
        "src/aoc_agent/adapters/execution/sandbox.py",
        "src/aoc_agent/adapters/execution/executor.py",
    ]

    def hashes():
        return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in hashed}

    before = hashes()
    python = str(ROOT / ".venv/bin/python")
    ruff = str(ROOT / ".venv/bin/ruff")
    checks = [
        [python, "-m", "pytest", "tests", "experiments/kolibri/tests", "-q"],
        [ruff, "check", "--config", "experiments/kolibri/cpu-ruff.toml", *scoped],
        [ruff, "format", "--check", "--config", "experiments/kolibri/cpu-ruff.toml", *scoped],
    ]
    env = {
        k: v
        for k, v in os.environ.items()
        if not re.search(r"TOKEN|SECRET|PASSWORD|API_KEY", k)
        and not k.startswith("EXECUTION_")
        and k not in {"PYTHONPATH", "PYTHONHOME"}
    }
    env.update(
        AOC_SESSION_TOKEN="OFFLINE_NOT_A_COOKIE",  # noqa: S106 - offline sentinel, not a credential
        LOGFIRE_SEND_TO_LOGFIRE="false",
        LOGFIRE_IGNORE_NO_CONFIG="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    if numpy_path is not None:
        env["AOC_TEST_NUMPY_PATH"] = str(numpy_path)
    completed = []
    for index, command in enumerate(checks, 1):
        result = subprocess.run(
            command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=600
        )
        body = result.stdout + result.stderr
        private_write(directory / f"check-{index}.log", body)
        if result.returncode:
            raise RuntimeError("offline scoped check failed; completion receipt not published")
        completed.append(
            {
                "command": command,
                "returncode": result.returncode,
                "output_sha256": hashlib.sha256(body.encode()).hexdigest(),
            }
        )
    if hashes() != before:
        raise ValueError("source changed during offline checks; receipt refused")
    receipt = {
        "schema_version": 1,
        "kind": "offline-test-completion",
        "all_scoped_checks_passed": True,
        "independent_review": False,
        "launch_approved": False,
        "benchmark_complete": False,
        "checks": completed,
        "source_sha256": before,
    }
    private_write(directory / "test-completion.json", json.dumps(receipt, indent=2) + "\n")
    return receipt


def prepare_checkpoint(
    source: Path, directory: Path | None = None
) -> tuple[tuple[str, bytes], ...]:
    """Delegate validation once; freeze and privately stage only validated source bytes."""
    from checkpoint import validated_checkpoint

    from run import load_experiment

    validated = validated_checkpoint(
        source, load_experiment(BASE / "config.yaml"), json.loads((BASE / "pins.json").read_text())
    )
    payload = (
        ("results.jsonl", validated["results_bytes"]),
        ("manifest.json", validated["manifest_bytes"]),
    )
    if any(type(data) is not bytes for _, data in payload):
        raise ValueError("checkpoint helper must return immutable file bytes")
    if directory is not None:
        staged = secure_dir(directory / "checkpoint-source")
        for name, data in payload:
            private_write(staged / name, data.decode("utf-8"))
        private_write(
            directory / "checkpoint-source.json",
            json.dumps({"source": str(source), "provenance": validated["provenance"]}),
        )
    return payload


def recover_checkpoint(directory: Path) -> tuple[tuple[str, bytes], ...]:
    """Recover only private frozen bytes, bound to the original validation metadata."""
    from checkpoint import validated_checkpoint

    from run import load_experiment

    metadata_path = directory / "checkpoint-source.json"
    staged = directory / "checkpoint-source"
    if not any(p.exists() or p.is_symlink() for p in (metadata_path, staged)):
        return ()
    for path in (
        directory,
        staged,
        metadata_path,
        staged / "results.jsonl",
        staged / "manifest.json",
    ):
        info = path.lstat()
        if path.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("unsafe private frozen checkpoint")
    if metadata_path.stat().st_size > 32768:
        raise ValueError("overlimit checkpoint source metadata")
    metadata = json.loads(metadata_path.read_text())
    if not isinstance(metadata, dict) or not isinstance(metadata.get("provenance"), dict):
        raise ValueError("malformed frozen checkpoint source metadata")
    validated = validated_checkpoint(
        staged, load_experiment(BASE / "config.yaml"), json.loads((BASE / "pins.json").read_text())
    )
    provenance = dict(validated["provenance"])
    original = metadata.get("provenance", {})
    provenance["source_directory"] = original.get("source_directory")
    if (
        set(metadata) != {"source", "provenance"}
        or not isinstance(metadata["source"], str)
        or provenance != original
        or original.get("source_directory") != str(Path(metadata["source"]).absolute())
    ):
        raise ValueError("frozen checkpoint source metadata or hash mismatch")
    return (
        ("results.jsonl", validated["results_bytes"]),
        ("manifest.json", validated["manifest_bytes"]),
    )


def deliver_checkpoint(
    execute: Callable[[str], str], payload: tuple[tuple[str, bytes], ...]
) -> None:
    """Bounded exec transport with exact-byte readback before benchmark release."""
    if tuple(name for name, _ in payload) != ("results.jsonl", "manifest.json"):
        raise ValueError("checkpoint transport accepts only known files")
    execute("import os; os.mkdir('/work/checkpoint',0o700)")
    expected = {}
    for name, data in payload:
        if type(data) is not bytes:
            raise ValueError("checkpoint transport requires immutable bytes")
        path = "/work/checkpoint/" + name
        execute(
            "import os; fd=os.open("
            + repr(path)
            + ",os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600); os.close(fd)"
        )
        for offset in range(0, len(data), 32768):
            chunk = base64.b64encode(data[offset : offset + 32768]).decode()
            execute(
                "import os,base64; fd=os.open("
                + repr(path)
                + ",os.O_WRONLY|os.O_APPEND|os.O_NOFOLLOW); "
                + "assert os.fstat(fd).st_size=="
                + str(offset)
                + "; "
                + "f=os.fdopen(fd,'ab'); f.write(base64.b64decode("
                + repr(chunk)
                + ",validate=True)); f.flush(); os.fsync(f.fileno()); f.close()"
            )
        expected[name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    actual = json.loads(
        execute("""import os,json,hashlib
files={}
for name in ('results.jsonl','manifest.json'):
 fd=os.open('/work/checkpoint/'+name,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as f:
  size=os.fstat(f.fileno()).st_size
  h=hashlib.sha256()
  for chunk in iter(lambda:f.read(32768),b''): h.update(chunk)
 files[name]={'size':size,'sha256':h.hexdigest()}
print(json.dumps(files))
""")
    )
    if actual != expected:
        raise ValueError("checkpoint delivery hash readback mismatch")


def bundle_archive():
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as tar:
        paths = [
            (p, str(p.relative_to(ROOT))) for p in sorted((ROOT / "src/aoc_agent").rglob("*.py"))
        ]
        paths += [
            (BASE / n, "experiments/kolibri/" + n)
            for n in (
                "run.py",
                "diagnostics.py",
                "verify_pins.py",
                "pins.json",
                "config.yaml",
                "checkpoint.py",
                "memory_telemetry.py",
            )
        ]
        paths += [
            (ROOT / "cache" / str(y) / f"day_{d}.{suffix}", f"cache/{y}/day_{d}.{suffix}")
            for y in (2022, 2023)
            for d in range(1, 26)
            for suffix in ("input.txt", "unsolved.html", "part1_solved.html", "part2_solved.html")
            if suffix != "part2_solved.html" or d != 25
        ]
        for path, name in paths:
            if path.is_symlink() or not path.is_file():
                raise ValueError("missing or unsafe public bundle member")
            data = path.read_bytes()
            if name.endswith(".html"):
                text = data.decode()
                public = re.findall(
                    r"<article\b.*?</article>|<p>Your puzzle answer was <code>.*?</code>.*?</p>",
                    text,
                    flags=re.DOTALL,
                )
                if not any(x.startswith("<article") for x in public):
                    raise ValueError("cache lacks public puzzle content")
                data = "\n".join(public).encode()
            member = tarfile.TarInfo(name)
            member.size = len(data)
            member.mode = 0o644
            member.mtime = 0
            tar.addfile(member, io.BytesIO(data))
    blob = stream.getvalue()
    if len(blob) > 700000:
        raise ValueError("public bundle exceeds ConfigMap bound")
    return blob


def resources(namespace, label, config, public_ips, *, remaining_seconds=DEFAULT_TTL_SECONDS):
    if type(remaining_seconds) is not int or not 1 <= remaining_seconds <= MAX_TTL_SECONDS:
        raise ValueError("positive bounded remaining lifetime required")
    if not re.fullmatch(r"kolibri-real-[0-9a-f]{12}", namespace) or not re.fullmatch(
        r"hermes-kolibri-[0-9a-f]{32}", label
    ):
        raise ValueError("dedicated ownership required")
    if not public_ips or any(
        not ipaddress.ip_address(ip).is_global or ipaddress.ip_address(ip).version != 4
        for ip in public_ips
    ):
        raise ValueError("nonempty public package IP allowlist required")
    if (
        not ipaddress.ip_address(config["host"]).is_global
        or ipaddress.ip_address(config["host"]).version != 4
    ):
        raise ValueError("public IPv4 serving host required")
    if type(config["port"]) is not int or not 1 <= config["port"] <= 65535:
        raise ValueError("invalid serving port")

    def obj(kind, name, spec=None):
        o = {
            "apiVersion": {"Job": "batch/v1", "NetworkPolicy": "networking.k8s.io/v1"}.get(
                kind, "v1"
            ),
            "kind": kind,
            "metadata": {"name": name, "namespace": namespace},
        }
        if spec is not None:
            o["spec"] = spec
        return o

    ns = obj("Namespace", namespace)
    ns["metadata"].pop("namespace")
    ns["metadata"]["labels"] = {
        "kolibri-real": label,
        "pod-security.kubernetes.io/enforce": "restricted",
        "pod-security.kubernetes.io/enforce-version": "v1.32",
    }
    objects = [
        ns,
        obj(
            "ResourceQuota",
            "bounded",
            {
                "hard": {
                    "limits.cpu": "3",
                    "limits.memory": "9Gi",
                    "limits.ephemeral-storage": "6Gi",
                    "pods": "1",
                    "count/jobs.batch": "1",
                    "services": "0",
                    "persistentvolumeclaims": "0",
                    "count/secrets": "1",
                }
            },
        ),
        obj(
            "NetworkPolicy",
            "default-deny",
            {"podSelector": {}, "policyTypes": ["Ingress", "Egress"], "ingress": [], "egress": []},
        ),
    ]
    for name, ips, port in [
        ("install-public", public_ips, 443),
        ("serving-tls", [config["host"]], config["port"]),
    ]:
        objects.append(
            obj(
                "NetworkPolicy",
                name,
                {
                    "podSelector": {"matchLabels": {"role": "runner"}},
                    "policyTypes": ["Egress"],
                    "egress": [
                        {
                            "to": [{"ipBlock": {"cidr": ip + "/32"}} for ip in ips],
                            "ports": [{"port": port, "protocol": "TCP"}],
                        }
                    ],
                },
            )
        )
    # DNS is installer-only policy: delete this and public package access before release.
    objects.append(
        obj(
            "NetworkPolicy",
            "install-dns",
            {
                "podSelector": {"matchLabels": {"role": "runner"}},
                "policyTypes": ["Egress"],
                "egress": [
                    {
                        "to": [
                            {
                                "namespaceSelector": {
                                    "matchLabels": {"kubernetes.io/metadata.name": "kube-system"}
                                },
                                "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
                            }
                        ],
                        "ports": [{"port": 53, "protocol": "UDP"}, {"port": 53, "protocol": "TCP"}],
                    }
                ],
            },
        )
    )
    secret = obj("Secret", "serving")
    secret.update(
        immutable=True,
        type="Opaque",
        data={"transport.json": base64.b64encode(json.dumps(config).encode()).decode()},
    )
    objects.append(secret)
    env = {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "HOME": "/work",
        "TMPDIR": "/tmp",
        "PYTHONPATH": "/work/deps:/work/repo/src:/bundle",
        "LOGFIRE_SEND_TO_LOGFIRE": "false",
        "EXECUTION_SANDBOX": "rlimit",
        "EXECUTION_MEMORY_MB": "4096",
        "AOC_SESSION_TOKEN": "OFFLINE_NOT_A_COOKIE",
    }

    def container(name, command, big=False):
        return {
            "name": name,
            "image": IMAGE,
            "imagePullPolicy": "IfNotPresent",
            "command": command,
            "workingDir": "/work",
            "env": [{"name": k, "value": v} for k, v in env.items()],
            "securityContext": copy.deepcopy(SC),
            "resources": {
                "requests": {
                    "cpu": "25m",
                    "memory": "256Mi" if big else "32Mi",
                    "ephemeral-storage": "64Mi",
                },
                "limits": {
                    "cpu": "1" if big else "100m",
                    "memory": "1Gi" if big else "128Mi",
                    "ephemeral-storage": "2Gi" if big else "128Mi",
                },
            },
            "volumeMounts": [
                {"name": "bundle", "mountPath": "/bundle", "readOnly": True},
                {"name": "work", "mountPath": "/work"},
                {"name": "tmp", "mountPath": "/tmp"},
            ],
        }

    runner = container("runner", ["python", "/bundle/real_runner.py"], True)
    # Runner log/agent state needs headroom; the installer keeps its original 1Gi cap.
    runner["resources"]["requests"]["memory"] = "512Mi"
    runner["resources"]["limits"]["memory"] = "8Gi"
    proxy = container(
        "tls-proxy", ["python", "/bundle/real_transport.py", "/serving/transport.json"]
    )
    # Proxy does not inherit a writable module search path controlled by generated code.
    proxy["env"] = [e for e in proxy["env"] if e["name"] != "PYTHONPATH"]
    proxy["command"].insert(1, "-I")
    for c in (runner, proxy):
        c["volumeMounts"].append({"name": "serving", "mountPath": "/serving", "readOnly": True})
    install = container(
        "install-public-deps",
        [
            "python",
            "-c",
            "import tarfile,subprocess; tarfile.open('/bundle/source.tar.gz').extractall('/work/repo',filter='data'); subprocess.run(['python','-m','pip','--isolated','install','--index-url','https://pypi.org/simple','--only-binary=:all:','--require-hashes','--no-cache-dir','--target','/work/deps','-r','/bundle/requirements.txt'],check=True)",
        ],
        True,
    )
    next(e for e in install["env"] if e["name"] == "TMPDIR")["value"] = "/work"
    pod = {
        "automountServiceAccountToken": False,
        "enableServiceLinks": False,
        "restartPolicy": "Never",
        "securityContext": copy.deepcopy(PSC),
        "terminationGracePeriodSeconds": 5,
        "containers": [runner, proxy],
        "initContainers": [install],
        "volumes": [
            {"name": "bundle", "configMap": {"name": "bundle", "defaultMode": 292}},
            {"name": "serving", "secret": {"secretName": "serving", "defaultMode": 292}},
            {"name": "work", "emptyDir": {"sizeLimit": "2Gi"}},
            {"name": "tmp", "emptyDir": {"sizeLimit": "128Mi"}},
        ],
    }
    objects.append(
        obj(
            "Job",
            "benchmark",
            {
                "backoffLimit": 0,
                "activeDeadlineSeconds": remaining_seconds,
                "ttlSecondsAfterFinished": 3600,
                "template": {"metadata": {"labels": {"role": "runner"}}, "spec": pod},
            },
        )
    )
    return objects


class KubeError(RuntimeError):
    def __init__(self, message, body):
        super().__init__(message)
        self.body = body


class Kube:
    def call(self, *args, data=None, timeout=60):
        p = subprocess.run(
            ["/usr/local/bin/kubectl", "--kubeconfig=/opt/kube/config", *args],
            input=None if data is None else json.dumps(data),
            capture_output=True,
            text=True,
            timeout=timeout,
            env={"PATH": os.environ["PATH"], "HOME": "/opt/data", "KUBECONFIG": "/opt/kube/config"},
        )
        if p.returncode:
            stage = "create" if "create" in args else "read-or-exec"
            raise KubeError(
                "Kubernetes " + stage + " failed; private diagnostic body retained", p.stderr
            )
        return p.stdout

    def get(self, namespace, kind, name):
        text = self.call(
            *(["-n", namespace] if namespace else []),
            "get",
            kind,
            name,
            "--ignore-not-found",
            "-o",
            "json",
        )
        return json.loads(text) if text.strip() else None


def cleanup_namespace(kube, namespace, label):
    current = kube.get(None, "namespace", namespace)
    if current is None:
        return True
    meta = current["metadata"]
    if meta.get("labels", {}).get("kolibri-real") != label:
        raise ValueError("namespace ownership mismatch")
    kube.call(
        "delete",
        "--raw",
        "/api/v1/namespaces/" + namespace,
        "-f",
        "-",
        data={
            "apiVersion": "v1",
            "kind": "DeleteOptions",
            "preconditions": {"uid": meta["uid"], "resourceVersion": meta["resourceVersion"]},
        },
    )
    kube.call("wait", "--for=delete", "namespace/" + namespace, "--timeout=90s", timeout=100)
    if kube.get(None, "namespace", namespace) is not None:
        raise RuntimeError("namespace still exists")
    return True


def controls_ready(targets, probe, *, pause=lambda: time.sleep(2), save=lambda r: None):
    from cpu_probe import require_controls

    for _ in range(8):
        result = probe()
        save(result)
        try:
            require_controls(targets, result)
            return result
        except RuntimeError:
            pause()
    raise RuntimeError("positive control unavailable after bounded CNI propagation wait")


def denial_ready(targets, probe, positive, *, pause=lambda: time.sleep(2), save=lambda r: None):
    from cpu_probe import require_denied

    for _ in range(8):
        result = probe()
        save(result)
        try:
            require_denied(targets, result, positive)
            return result
        except RuntimeError:
            pause()
    raise RuntimeError("exact denial unavailable after bounded CNI revocation wait")


def create_fresh(kube, record, directory, recipe, bundle, cpu):
    """Fresh namespace path remains separate from explicit owned replacement."""
    (directory / "namespace-attempted").write_text(record["namespace"])
    kube.call("create", "-f", "-", data=recipe[0])
    if not cpu:
        recipe[-1]["spec"]["activeDeadlineSeconds"] = int(record["deadline"] - time.time())
        if recipe[-1]["spec"]["activeDeadlineSeconds"] < 1:
            raise RuntimeError("original lease expired before runner creation")
    kube.call(
        "create",
        "-f",
        "-",
        data={"apiVersion": "v1", "kind": "List", "items": recipe[1:-1] + [bundle, recipe[-1]]},
    )


def owned_dead_runner(kube, record, directory):
    """Bind exact retained namespace/pod/job; require terminated runner and trusted proxy."""
    hold = json.loads((directory / "debug-hold.json").read_text())
    binding = record
    if "extension" in record:
        from real_extend import validate_extension

        # The caller's read() verifies the immutable receipt; independently validate
        # the audit before accepting unchanged pre-extension hold evidence.
        validate_extension(record)
        if hold.get("deadline") != record["deadline"]:
            binding = record["extension"]["original"]
    for name in ("label", "namespace", "instance", "start_date", "deadline"):
        if hold.get(name) != binding[name]:
            raise ValueError("debug hold lease binding mismatch")
    ns = kube.get(None, "namespace", record["namespace"])
    if not ns or ns["metadata"].get("labels", {}).get("kolibri-real") != record["label"]:
        raise ValueError("retained namespace ownership mismatch")
    pod = kube.get(record["namespace"], "pod", hold["pod"])
    # Historical holds predate UID fields. Use the already exported exact pod evidence.
    uid = hold.get("pod_uid")
    if uid is None:
        evidence = json.loads((directory / "kubernetes-pods.json").read_text())
        matches = [p for p in evidence if p["metadata"]["name"] == hold["pod"]]
        if len(matches) != 1:
            raise ValueError("missing original pod UID evidence")
        uid = matches[0]["metadata"].get("uid")
    if (
        not uid
        or not pod
        or pod["metadata"].get("uid") != uid
        or pod["metadata"].get("namespace") != record["namespace"]
        or hold.get("namespace_uid", ns["metadata"]["uid"]) != ns["metadata"]["uid"]
    ):
        raise ValueError("retained pod or namespace UID mismatch")
    statuses = {c["name"]: c for c in pod.get("status", {}).get("containerStatuses", [])}
    if (
        "terminated" not in statuses.get("runner", {}).get("state", {})
        or "running" not in statuses.get("tls-proxy", {}).get("state", {})
        or statuses.get("tls-proxy", {}).get("ready") is not True
    ):
        raise ValueError("replacement requires terminated runner and ready live proxy")
    containers = {c["name"]: c for c in pod["spec"]["containers"]}
    proxy = containers.get("tls-proxy", {})
    mounts = {m["name"]: m for m in proxy.get("volumeMounts", [])}
    volumes = {v["name"]: v for v in pod["spec"].get("volumes", [])}
    if (
        proxy.get("image") != IMAGE
        or proxy.get("command")
        != ["python", "-I", "/bundle/real_transport.py", "/serving/transport.json"]
        or mounts.get("work", {}).get("mountPath") != "/work"
        or mounts.get("bundle", {}).get("mountPath") != "/bundle"
        or mounts.get("bundle", {}).get("readOnly") is not True
        or mounts.get("serving", {}).get("mountPath") != "/serving"
        or mounts.get("serving", {}).get("readOnly") is not True
        or "emptyDir" not in volumes.get("work", {})
        or volumes.get("serving", {}).get("secret", {}).get("secretName") != "serving"
    ):
        raise ValueError("untrusted proxy or shared mounts")
    bundle_name = volumes.get("bundle", {}).get("configMap", {}).get("name")
    bundle = kube.get(record["namespace"], "configmap", bundle_name) if bundle_name else None
    if (
        not bundle
        or bundle.get("immutable") is not True
        or bundle.get("data", {}).get("real_transport.py")
        != (BASE / "real_transport.py").read_text()
        or any(e.get("name") in {"PYTHONPATH", "PYTHONHOME"} for e in proxy.get("env", []))
    ):
        raise ValueError("untrusted immutable proxy source or module path")
    owners = [
        o
        for o in pod["metadata"].get("ownerReferences", [])
        if o.get("kind") == "Job" and o.get("name") == "benchmark" and o.get("controller") is True
    ]
    job = kube.get(record["namespace"], "job", "benchmark")
    if len(owners) != 1 or not job or owners[0].get("uid") != job["metadata"].get("uid"):
        raise ValueError("retained job UID ownership mismatch")
    return {
        "pod": hold["pod"],
        "pod_uid": uid,
        "namespace_uid": ns["metadata"]["uid"],
        "job_uid": job["metadata"]["uid"],
        "job_resource_version": job["metadata"]["resourceVersion"],
    }


def prepare_dead_runner(kube, record, directory, config, *, check_active):
    """Export and freeze evidence/filtered seed before permitting owned CPU replacement."""
    from checkpoint import filtered_checkpoint

    from run import load_experiment

    check_active()
    binding = owned_dead_runner(kube, record, directory)
    export_namespace(
        kube, record, binding["pod"], directory, secrets=(config.get("api_key", ""),), bounded=True
    )
    validated = filtered_checkpoint(
        directory,
        load_experiment(BASE / "config.yaml"),
        json.loads((BASE / "pins.json").read_text()),
    )
    raw_inventory = json.loads((directory / "artifact-export.json").read_text())
    for name, body in (
        ("results.jsonl", validated["raw_results_bytes"]),
        ("manifest.json", validated["raw_manifest_bytes"]),
    ):
        if raw_inventory.get(name) != {
            "size": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        }:
            raise ValueError("raw checkpoint export hash mismatch")
    archive = directory / ("dead-runner-" + binding["pod_uid"])
    archive.mkdir(mode=0o700)  # Never overwrite an archived attempt.
    candidates = [
        p
        for p in directory.iterdir()
        if p.is_file()
        and (
            p.name
            in {
                "results.jsonl",
                "manifest.json",
                "artifact-export.json",
                "namespace-export.json",
                "debug-hold.json",
            }
            or p.name.startswith(("runner-", "failure", "client-close", "memory-", "kubernetes-"))
        )
    ]
    candidates += (
        list((directory / "attempts").rglob("*")) if (directory / "attempts").exists() else []
    )
    total = 0
    for source in candidates:
        if source.is_symlink():
            raise ValueError("unsafe replacement archive")
        if not source.is_file():
            continue
        total += source.stat().st_size
        if total > 268435456:
            raise ValueError("replacement archive exceeded bound")
        destination = archive / source.relative_to(directory)
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(source.read_bytes())
        destination.chmod(0o400)
    derived = secure_dir(directory / "replacement-seed")
    for name in ("results.jsonl", "manifest.json"):
        private_write(
            derived / name,
            validated["results_bytes" if name == "results.jsonl" else "manifest_bytes"].decode(),
        )
    previous = recover_checkpoint(directory)
    if previous:
        from checkpoint import validated_results

        prior = validated_results(
            dict(previous)["results.jsonl"], load_experiment(BASE / "config.yaml")
        )
        if not prior <= validated["completed"]:
            raise ValueError("replacement checkpoint regression")
    payload = prepare_checkpoint(derived, directory)
    if recover_checkpoint(directory) != payload:
        raise ValueError("replacement checkpoint freeze verification failed")
    private_write(
        directory / "replacement-ready.json",
        json.dumps(
            {
                "binding": binding,
                "deadline": record["deadline"],
                "instance": record["instance"],
                "archive": str(archive),
                "saved_rows": len(validated["completed"]),
            }
        ),
    )
    check_active()
    if owned_dead_runner(kube, record, directory) != binding:
        raise ValueError("replacement ownership changed during export")
    return binding, payload


def deploy(
    kube,
    record,
    config,
    directory,
    *,
    cpu=False,
    checkpoint=(),
    owned_replace=None,
    check_active=lambda: None,
):
    namespace, label = record["namespace"], record["label"]
    if owned_replace is None:
        if kube.get(None, "namespace", namespace):
            raise ValueError("namespace must be fresh")
    else:
        check_active()
        if cpu or not checkpoint or recover_checkpoint(directory) != checkpoint:
            raise ValueError("owned replacement requires verified frozen checkpoint")
        ready = json.loads((directory / "replacement-ready.json").read_text())
        if (
            ready.get("binding") != owned_replace
            or ready.get("deadline") != record["deadline"]
            or ready.get("instance") != record["instance"]
            or owned_dead_runner(kube, record, directory) != owned_replace
        ):
            raise ValueError("replacement receipt or ownership mismatch")
        secret = kube.get(namespace, "secret", "serving")
        if (
            not secret
            or secret.get("immutable") is not True
            or secret.get("data")
            != {"transport.json": base64.b64encode(json.dumps(config).encode()).decode()}
        ):
            raise ValueError("replacement must preserve frozen serving transport")
    ips = sorted(
        {
            r[4][0]
            for host in ("pypi.org", "files.pythonhosted.org")
            for r in socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
        }
    )
    recipe = resources(
        namespace,
        label,
        config,
        ips,
        remaining_seconds=int(record["deadline"] - time.time()),
    )
    archive = bundle_archive()
    scripts = {
        n: (BASE / n).read_text()
        for n in (
            "real_runner.py",
            "diagnostics.py",
            "real_transport.py",
            "cpu_probe.py",
            "checkpoint.py",
            "memory_telemetry.py",
        )
    }
    (directory / "bundle-manifest.json").write_text(
        json.dumps(
            {
                "archive_sha256": hashlib.sha256(archive).hexdigest(),
                "requirements_sha256": hashlib.sha256(
                    (BASE / "cpu-runtime.lock").read_bytes()
                ).hexdigest(),
                "scripts_sha256": {
                    n: hashlib.sha256(s.encode()).hexdigest() for n, s in scripts.items()
                },
            }
        )
    )
    (directory / "requested-resources.json").write_text(
        json.dumps([o for o in recipe if o["kind"] != "Secret"])
    )
    bundle = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": "bundle", "namespace": namespace},
        "immutable": True,
        "data": scripts,
        "binaryData": {
            "source.tar.gz": base64.b64encode(archive).decode(),
            "requirements.txt": base64.b64encode((BASE / "cpu-runtime.lock").read_bytes()).decode(),
        },
    }
    if owned_replace is not None:
        # New content-addressed immutable ConfigMap; never mutate a mounted bundle.
        bundle_name = (
            "bundle-" + hashlib.sha256(json.dumps(bundle, sort_keys=True).encode()).hexdigest()[:16]
        )
        bundle["metadata"]["name"] = bundle_name
        recipe[-1]["spec"]["template"]["spec"]["volumes"][0]["configMap"]["name"] = bundle_name
        check_active()
        if owned_dead_runner(kube, record, directory) != owned_replace:
            raise ValueError("replacement ownership changed before deletion")
        kube.call(
            "delete",
            "--raw",
            "/apis/batch/v1/namespaces/" + namespace + "/jobs/benchmark",
            "-f",
            "-",
            data={
                "apiVersion": "v1",
                "kind": "DeleteOptions",
                "propagationPolicy": "Foreground",
                "preconditions": {
                    "uid": owned_replace["job_uid"],
                    "resourceVersion": owned_replace["job_resource_version"],
                },
            },
        )
        kube.call(
            "-n", namespace, "wait", "--for=delete", "job/benchmark", "--timeout=90s", timeout=100
        )
        kube.call(
            "-n",
            namespace,
            "wait",
            "--for=delete",
            "pod/" + owned_replace["pod"],
            "--timeout=90s",
            timeout=100,
        )
        if (
            kube.get(namespace, "job", "benchmark") is not None
            or kube.get(namespace, "pod", owned_replace["pod"]) is not None
        ):
            raise RuntimeError("old job/pod still exists")
        check_active()
        current_ns = kube.get(None, "namespace", namespace)
        if not current_ns or current_ns["metadata"].get("uid") != owned_replace["namespace_uid"]:
            raise ValueError("namespace changed after deletion")
        # Reinstall temporary installer gates only after the old pod is absent.
        kube.call(
            "apply",
            "-f",
            "-",
            data={
                "apiVersion": "v1",
                "kind": "List",
                "items": [o for o in recipe[1:-1] if o["kind"] != "Secret"],
            },
        )
        existing_bundle = kube.get(namespace, "configmap", bundle_name)
        if existing_bundle is None:
            kube.call("create", "-f", "-", data=bundle)
        elif any(
            existing_bundle.get(key) != bundle[key] for key in ("immutable", "data", "binaryData")
        ):
            raise ValueError("replacement bundle hash collision")
        check_active()
        recipe[-1]["spec"]["activeDeadlineSeconds"] = int(record["deadline"] - time.time())
        if recipe[-1]["spec"]["activeDeadlineSeconds"] < 1:
            raise RuntimeError("original lease expired before replacement job")
        kube.call("create", "-f", "-", data=recipe[-1])
    else:
        create_fresh(kube, record, directory, recipe, bundle, cpu)
    end = time.monotonic() + 420
    pod = None
    while time.monotonic() < end:
        if owned_replace is not None:
            check_active()
        items = json.loads(
            kube.call("-n", namespace, "get", "pods", "-l", "role=runner", "-o", "json")
        )["items"]
        if items:
            p = items[0]
            if p.get("status", {}).get("phase") == "Failed":
                raise RuntimeError("runner failed before gate")
            if any(
                c.get("type") == "Ready" and c.get("status") == "True"
                for c in p.get("status", {}).get("conditions", [])
            ):
                pod = p["metadata"]["name"]
                break
        time.sleep(2)
    if not pod:
        raise RuntimeError("runner initialization timeout")

    def execute(script):
        return kube.call("-n", namespace, "exec", pod, "-c", "runner", "--", "python", "-c", script)

    # Establish TCP positive controls for package and Kubernetes API exact tuples.
    service = kube.get("default", "service", "kubernetes")
    endpoints = kube.get("default", "endpoints", "kubernetes")
    targets = [
        ["public-pypi", ips[0], 443],
        ["kubernetes-api", service["spec"]["clusterIP"], service["spec"]["ports"][0]["port"]],
    ]
    targets += [
        ["kubernetes-api-backend-" + str(i), a["ip"], p["port"]]
        for i, (a, p) in enumerate(
            (a, p)
            for s in endpoints.get("subsets", [])
            for a in s.get("addresses", [])
            for p in s["ports"]
        )
    ]
    if len(targets) > 5:
        raise ValueError("probe set exceeds bound")
    temporary = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": "positive-controls", "namespace": namespace},
        "spec": {
            "podSelector": {"matchLabels": {"role": "runner"}},
            "policyTypes": ["Egress"],
            "egress": [
                {
                    "to": [{"ipBlock": {"cidr": ip + "/32"}}],
                    "ports": [{"port": port, "protocol": "TCP"}],
                }
                for _, ip, port in targets
            ],
        },
    }
    kube.call("create", "-f", "-", data=temporary)
    probe = (
        "from cpu_probe import tcp_probe; import json; print(json.dumps(tcp_probe("
        + repr(targets)
        + ")))"
    )

    controls = controls_ready(
        targets,
        lambda: json.loads(execute(probe)),
        save=lambda r: (directory / "positive-controls.json").write_text(json.dumps(r)),
    )
    for name in ("positive-controls", "install-public", "install-dns"):
        kube.call("-n", namespace, "delete", "networkpolicy", name)
        if kube.get(namespace, "networkpolicy", name) is not None:
            raise RuntimeError("installer policy remained")
    denied = denial_ready(
        targets,
        lambda: json.loads(execute(probe)),
        controls,
        save=lambda r: (directory / "denied-probes.json").write_text(json.dumps(r)),
    )
    (directory / "isolation.json").write_text(
        json.dumps(
            {
                "positive": controls,
                "denied": denied,
                "private_broker_positive_control": "not attempted; ingress does not admit this namespace",
            }
        )
    )
    # Preflight only in CPU mode, actual inference only after operator explicit approval.
    if owned_replace is not None:
        check_active()
    release = {"action": "preflight" if cpu else "run", "run_id": label}
    if checkpoint:
        deliver_checkpoint(execute, checkpoint)
    if time.time() >= record["deadline"]:
        raise RuntimeError("original lease expired before benchmark release")
    execute(
        "import pathlib,json; pathlib.Path('/work/released.json').write_text("
        + repr(json.dumps(release))
        + ")"
    )
    return pod


def require_complete_checkpoint(directory):
    """Success is shared-validator evidence, never a runner label or row count."""
    from checkpoint import validated_checkpoint

    from run import load_experiment

    validated = validated_checkpoint(
        directory,
        load_experiment(BASE / "config.yaml"),
        json.loads((BASE / "pins.json").read_text()),
    )
    expected = {(year, day) for year in (2022, 2023) for day in range(1, 26)}
    if validated["completed"] != expected or validated["provenance"]["source_status"] != "complete":
        raise ValueError(
            "benchmark incomplete; validated complete manifest and all 50 keys required"
        )
    return validated


def collect(
    kube, record, pod, directory, *, secrets=(), final=False, container="runner", bounded=False
):
    """Export every allowlisted byte in verified segments, never silently omit large files."""
    if container not in {"runner", "tls-proxy"}:
        raise ValueError("unsupported artifact export container")
    if not re.fullmatch(r"hermes-kolibri-[0-9a-f]{32}", record["label"]):
        raise ValueError("invalid diagnostic run label")
    run = "/work/repo/experiments/kolibri/runs/" + record["label"] + "/"
    paths = {
        n: run + n
        for n in (
            "manifest.json",
            "results.jsonl",
            "failure.json",
            "failure-traceback.txt",
            "client-close-failure.json",
            "client-close-failure-traceback.txt",
        )
    }
    paths.update(
        {
            n: "/work/" + n
            for n in (
                "runner-status.json",
                "runner-stdout.log",
                "runner-stderr.log",
                "runner-failure.json",
                "runner-failure-traceback.txt",
                "memory-metrics.jsonl",
                "memory-metrics.metadata.json",
            )
        }
    )

    def execute(script):
        return kube.call(
            "-n",
            record["namespace"],
            "exec",
            pod,
            "-c",
            container,
            "--",
            "python",
            "-I",
            "-c",
            script,
        )

    archived = json.loads(
        execute("""import pathlib,json,re
root=pathlib.Path('/work/attempts/')
if root.is_symlink(): raise ValueError('unsafe attempts root')
names=[]
if root.exists():
 for child in sorted(root.iterdir()):
  if child.is_symlink() or not child.is_dir() or not re.fullmatch('[0-9]{4}',child.name):
   raise ValueError('unsafe attempt directory')
  if (child/'benchmark').is_symlink(): raise ValueError('unsafe benchmark directory')
  names.append(child.name)
print(json.dumps(names))
""")
    )
    if bounded and len(archived) > 16:
        raise ValueError("attempt export exceeded bound")
    original_paths = dict(paths)
    for attempt in archived:
        if not isinstance(attempt, str) or not re.fullmatch(r"[0-9]{4}", attempt):
            raise ValueError("invalid archived attempt")
        for name, path in original_paths.items():
            relative = name if path == "/work/" + name else "benchmark/" + name
            key = "attempts/" + attempt + "/" + relative
            paths[key] = "/work/" + key

    script = """import pathlib,json,hashlib
files={}
for name,path in PATHS.items():
 f=pathlib.Path(path)
 if f.is_symlink(): raise ValueError('unsafe artifact')
 if not f.exists(): continue
 if not f.is_file(): raise ValueError('non-file artifact')
 size=f.stat().st_size
 h=hashlib.sha256()
 with f.open('rb') as stream:
  remaining=size
  while remaining:
   chunk=stream.read(min(262144,remaining))
   if not chunk: raise ValueError('artifact shrank')
   h.update(chunk); remaining-=len(chunk)
 files[name]={'size':size,'sha256':h.hexdigest()}
print(json.dumps(files))
""".replace("PATHS", repr(paths))
    inventory = json.loads(execute(script))
    if bounded and (
        len(inventory) > 512
        or any(
            type(m.get("size")) is not int or not 0 <= m["size"] <= 67108864
            for m in inventory.values()
        )
        or sum(m["size"] for m in inventory.values()) > 268435456
    ):
        raise ValueError("artifact export exceeded bound")
    if final:
        required = {"runner-status.json", "runner-stdout.log", "runner-stderr.log"}
        if record["status"] == "running":
            required.add("manifest.json")
        if not required <= inventory.keys():
            raise ValueError("missing required final diagnostic artifacts")
    files = {}
    for name, meta in inventory.items():
        if name not in paths or type(meta.get("size")) is not int or meta["size"] < 0:
            raise ValueError("invalid artifact inventory")
        blob = bytearray()
        for offset in range(0, meta["size"], 262144):
            count = min(262144, meta["size"] - offset)
            script = (
                "import pathlib,base64; f=pathlib.Path(" + repr(paths[name]) + "); "
                "assert not f.is_symlink(); s=f.open('rb'); s.seek(" + str(offset) + "); "
                "print(base64.b64encode(s.read(" + str(count) + ")).decode())"
            )
            chunk = base64.b64decode(execute(script).strip(), validate=True)
            if len(chunk) != count:
                raise ValueError("incomplete artifact segment")
            blob.extend(chunk)
        if hashlib.sha256(blob).hexdigest() != meta["sha256"]:
            raise ValueError("artifact changed during export; retry before cleanup")
        text = redact(blob.decode("utf-8"), secrets)
        if name.startswith("attempts/"):
            parent = directory / Path(name).parent
            secure_dir(directory / "attempts")
            secure_dir(parent.parent if parent.name == "benchmark" else parent)
            secure_dir(parent)
        private_write(directory / name, text)
        files[name] = text
    private_write(directory / "artifact-export.json", json.dumps(inventory, indent=2))
    rows = [json.loads(line) for line in files.get("results.jsonl", "").splitlines() if line]
    status = json.loads(files.get("runner-status.json", "{}"))
    attempt = status.get("attempt")
    if attempt is not None:
        if type(attempt) is not int or not 1 <= attempt <= 9999:
            raise ValueError("invalid runner attempt")
        secure_dir(directory / "attempts")
        snapshot = secure_dir(directory / "attempts" / f"{attempt:04d}")
        for name, text in files.items():
            if not name.startswith("attempts/"):
                private_write(snapshot / name, text)
    progress = {
        "label": record["label"],
        "saved_rows": len(rows),
        "expected_rows": 50,
        "error_rows": sum(r.get("error") is not None for r in rows),
        "runner": status.get("status", "waiting"),
        "attempt": attempt,
        "updated": time.time(),
        "completion_validated": False,
    }
    if progress["runner"] == "complete" and {"results.jsonl", "manifest.json"} <= files.keys():
        try:
            require_complete_checkpoint(directory)
        except ValueError:
            # Invalid terminal evidence still exports rows/progress for gated retention.
            progress["completion_validated"] = False
        else:
            progress["completion_validated"] = True
    (directory / "progress.json").write_text(json.dumps(progress))
    return progress


def select_offer(offers, offer_id, ceiling):
    import math

    selected = [o for o in offers if o.get("id") == offer_id]
    if len(selected) != 1:
        raise ValueError("offer absent or ambiguous")
    offer = selected[0]
    for name in ("disk_space", "cuda_max_good", "dph_total", "gpu_ram", "reliability"):
        if type(offer.get(name)) not in (int, float) or not math.isfinite(offer[name]):
            raise ValueError("invalid offer metadata")
    driver = offer.get("driver_version", "")
    if (
        not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", driver)
        or int(driver.split(".")[0]) < 580
        or offer.get("gpu_name") not in {"H200", "H200 NVL"}
        or offer["gpu_ram"] < 140000
        or offer["disk_space"] < 200
        or offer["cuda_max_good"] < 13
        or offer["reliability"] < 0.99
        or not 0 < offer["dph_total"] <= ceiling
    ):
        raise ValueError("offer does not pass refreshed capacity gates")
    return offer


def export_namespace(kube, record, pod, directory, *, secrets=(), bounded=False):
    """Persist pod termination metadata, events and complete available container logs."""
    namespace = record["namespace"]
    pods = json.loads(kube.call("-n", namespace, "get", "pods", "-o", "json"))["items"]
    # Never export the pod spec: environment may contain credentials.
    evidence = [{"metadata": p["metadata"], "status": p.get("status", {})} for p in pods]
    private_write(directory / "kubernetes-pods.json", redact(json.dumps(evidence), secrets))
    events = kube.call("-n", namespace, "get", "events", "-o", "json")
    private_write(directory / "kubernetes-events.json", redact(events, secrets))
    if pod and not any(p["metadata"]["name"] == pod for p in pods):
        raise RuntimeError("runner pod disappeared before evidence export")
    if bounded and len(pods) != 1:
        raise ValueError("replacement requires exactly one owned pod")
    for item in pods:
        name = item["metadata"]["name"]
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
            raise ValueError("unsafe pod evidence name")
        status = item.get("status", {})
        containers = status.get("initContainerStatuses", []) + status.get("containerStatuses", [])
        runner_running = any(
            c["name"] == "runner" and "running" in c.get("state", {}) for c in containers
        )
        for container in containers:
            c = container["name"]
            if c not in {"runner", "tls-proxy", "install-public-deps"}:
                raise ValueError("unexpected diagnostic container")
            state = container.get("state", {})
            if "running" in state or "terminated" in state:
                log = kube.call(
                    "-n",
                    namespace,
                    "logs",
                    name,
                    "-c",
                    c,
                    "--timestamps=true",
                    "--tail=-1",
                    *(["--limit-bytes=67108865"] if bounded else []),
                    timeout=120,
                )
                if bounded and len(log.encode()) > 67108864:
                    raise ValueError("container log export exceeded bound")
                private_write(directory / f"kubernetes-{name}-{c}.log", redact(log, secrets))
            if container.get("lastState", {}).get("terminated") or container.get("restartCount", 0):
                log = kube.call(
                    "-n",
                    namespace,
                    "logs",
                    name,
                    "-c",
                    c,
                    "--previous",
                    "--timestamps=true",
                    "--tail=-1",
                    *(["--limit-bytes=67108865"] if bounded else []),
                    timeout=120,
                )
                if bounded and len(log.encode()) > 67108864:
                    raise ValueError("previous log export exceeded bound")
                private_write(
                    directory / f"kubernetes-{name}-{c}-previous.log", redact(log, secrets)
                )
            if c == "runner" and "running" in state:
                collect(kube, record, name, directory, secrets=secrets, final=True)
            elif c == "tls-proxy" and "running" in state and not runner_running:
                # The immutable proxy shares /work; no generated modules are imported here.
                collect(
                    kube,
                    record,
                    name,
                    directory,
                    secrets=secrets,
                    final=True,
                    container="tls-proxy",
                    bounded=bounded,
                )
    private_write(directory / "namespace-export.json", json.dumps({"complete": True}))


def finish_namespace(kube, record, pod, directory, *, secrets=()):
    """Deletion is fail-closed on export; failure never raises to block GPU cleanup."""
    if not (directory / "namespace-attempted").exists():
        return True
    try:
        export_namespace(kube, record, pod, directory, secrets=secrets)
    except BaseException as error:
        try:
            save_failure(directory, error, prefix="export-failure", secrets=secrets)
            private_write(
                directory / "namespace-cleanup.json",
                json.dumps(
                    {
                        "absent": False,
                        "retained": True,
                        "reason": "evidence export failed",
                    }
                ),
            )
        except BaseException:  # evidence write failure cannot prevent independent GPU cleanup
            return False
        return False
    try:
        absent = cleanup_namespace(kube, record["namespace"], record["label"])
        private_write(directory / "namespace-cleanup.json", json.dumps({"absent": absent}))
        return absent
    except BaseException as error:
        try:
            save_failure(directory, error, prefix="namespace-cleanup-failure", secrets=secrets)
            private_write(directory / "namespace-cleanup.json", '{"absent":false}')
        except BaseException:  # evidence write failure cannot prevent independent GPU cleanup
            return False
        return False


def finish_provider_logs(record, directory, config, provider):
    """Preserve server logs before delete; never block mandatory GPU cleanup."""
    if record.get("instance") is None:
        return True
    values = (config.get("api_key", ""),)
    try:
        material = {
            "api_key": config["api_key"],
            "cert": (directory / "server.crt").read_text(),
            "key": (directory / "server.key").read_text(),
        }
        encoded = base64.b64encode(json.dumps(material).encode()).decode()
        values = (material["api_key"], material["key"], encoded)
        metadata = capture_provider_logs(record, directory, values, provider=provider)
        private_write(directory / "provider-log-capture.json", json.dumps(metadata))
        return metadata["status"] == "captured"
    except BaseException as error:
        try:
            save_failure(directory, error, prefix="provider-log-failure", secrets=values)
        except BaseException:
            pass
        return False


def serving_port(ports):
    """Select one public IPv4 port, allowing Docker's duplicate IPv6 binding."""
    bindings = ports.get("8000/tcp") if isinstance(ports, dict) else None
    if not isinstance(bindings, list) or not 1 <= len(bindings) <= 16:
        raise ValueError("invalid serving port metadata")
    candidates = set()
    for binding in bindings:
        if not isinstance(binding, dict):
            raise ValueError("invalid serving port binding")
        host = binding.get("HostIp", "0.0.0.0")
        if host == "::":
            continue  # Transport intentionally uses public IPv4 only.
        if host != "0.0.0.0":
            raise ValueError("unexpected serving bind address")
        raw = binding.get("HostPort")
        if not isinstance(raw, str) or not re.fullmatch(r"[0-9]{1,5}", raw):
            raise ValueError("invalid serving port")
        value = int(raw)
        if not 1 <= value <= 65535:
            raise ValueError("invalid serving port")
        candidates.add(value)
    if len(candidates) != 1:
        raise ValueError("ambiguous serving IPv4 port")
    return candidates.pop()


def retain_failure(path, record, kube, pod, directory, config, provider):
    """Retain only a gated benchmark failure on an exact, still affordable lease."""
    if not pod or record["instance"] is None or record["start_date"] is None:
        return False
    binding = (record["instance"], record["start_date"], record["deadline"])
    with locked():
        current = read(path)
        if (
            current["status"] not in {"running", "debug-retained"}
            or (current["instance"], current["start_date"], current["deadline"]) != binding
        ):
            return False
        outcome = watchdog(
            current,
            provider,
            now=time.time(),
            execute=True,
            save=lambda r: store(path, r),
        )
        if outcome != "not-due":
            return False
        current["status"] = "debug-retained"
        store(path, current)
    hold = {
        "status": "debug-retained",
        "label": current["label"],
        "namespace": current["namespace"],
        "pod": pod,
        "instance": current["instance"],
        "start_date": current["start_date"],
        "deadline": current["deadline"],
    }
    private_write(directory / "debug-hold.json", json.dumps(hold))
    try:
        export_namespace(kube, current, pod, directory, secrets=(config["api_key"],))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        save_failure(directory, error, prefix="export-failure", secrets=(config["api_key"],))
    print(json.dumps(hold), flush=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-approved", action="store_true")
    parser.add_argument("--execute-cpu-preflight", action="store_true")
    parser.add_argument("--offer", type=int)
    parser.add_argument("--hourly-ceiling", type=float, default=4.25)
    parser.add_argument("--reserve", type=float, default=2.5, choices=(0.0, 2.5))
    parser.add_argument("--download-ceiling", type=float, default=0.6)
    parser.add_argument(
        "--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS, metavar="600..10800"
    )
    parser.add_argument("--watchdog-receipt", type=Path)
    parser.add_argument("--resume-from", type=Path)
    args = parser.parse_args()
    if not 600 <= args.ttl_seconds <= MAX_TTL_SECONDS:
        parser.error("TTL must be between 600 and 10800 seconds")
    if args.execute_approved and args.execute_cpu_preflight:
        parser.error("choose one execution mode")
    if not (args.execute_approved or args.execute_cpu_preflight):
        if args.resume_from:
            prepare_checkpoint(args.resume_from)
        blob = bundle_archive()
        print(
            json.dumps(
                {
                    "execution": False,
                    "inference": False,
                    "tasks": 50,
                    "bundle_bytes": len(blob),
                    "bundle_sha256": hashlib.sha256(blob).hexdigest(),
                    "state": str(STATE),
                }
            )
        )
        return 0
    if not __debug__:
        parser.error("optimized execution refused")
    secure_dir()
    label = "hermes-kolibri-" + secrets.token_hex(16)
    namespace = "kolibri-real-" + secrets.token_hex(6)
    directory = STATE / label
    directory.mkdir(mode=0o700)
    config = material(directory)
    private_write(directory / "resume-transport.json", json.dumps(config))
    created = time.time()
    record = {
        "version": 1,
        "label": label,
        "created": created,
        "deadline": created + args.ttl_seconds,
        "reserve": args.reserve,
        "hourly_ceiling": args.hourly_ceiling,
        "download_ceiling": args.download_ceiling,
        "instance": None,
        "start_date": None,
        "status": "prepared",
        "offer": args.offer or 1,
        "namespace": namespace,
    }
    lease_path = STATE / (label + ".json")
    provider = Vast()
    kube = Kube()
    attempted = False
    benchmark_failed = False
    pod = None
    try:
        checkpoint = prepare_checkpoint(args.resume_from, directory) if args.resume_from else ()
        if args.execute_approved:
            if not args.offer or not args.watchdog_receipt:
                parser.error("fresh offer and verified independent watchdog receipt required")
            receipt = json.loads(args.watchdog_receipt.read_text())
            if (
                set(receipt) != {"job_id", "schedule_seconds", "verified_at"}
                or not isinstance(receipt["job_id"], str)
                or not receipt["job_id"]
                or not 0 < receipt["schedule_seconds"] <= 60
                or not 0 <= time.time() - receipt["verified_at"] <= 300
            ):
                raise ValueError("fresh watchdog attestation required")
            with locked():
                if any(
                    read(p)["status"] not in {"destroyed", "prepared"}
                    for p in STATE.glob("hermes-kolibri-*.json")
                ):
                    raise ValueError("another unresolved lease exists")
                credit = identity(provider)
                if provider.call("list"):
                    raise ValueError("existing provider inventory; refuse rental")
                offers = provider.call(
                    "search",
                    "num_gpus=1 gpu_ram>=140 verified=true reliability>=0.99 rentable=true dph_total<=4.7",
                )
                selected = select_offer(offers, args.offer, args.hourly_ceiling)
                maximum = args.hourly_ceiling * args.ttl_seconds / 3600 + args.download_ceiling
                (directory / "quote.json").write_text(
                    json.dumps(
                        {
                            "offer": selected,
                            "credit": credit,
                            "ttl_seconds": args.ttl_seconds,
                            "hourly_ceiling": args.hourly_ceiling,
                            "download_allowance": args.download_ceiling,
                            "estimated_maximum": maximum,
                            "reserve": args.reserve,
                            "observed_at": time.time(),
                        }
                    )
                )
                if credit < maximum + args.reserve:
                    raise ValueError("credit insufficient for quoted ceiling and reserve")
                record["status"] = "launching"
                store(lease_path, record)
                # From here the independent watchdog owns lost-response reconciliation.
                attempted = True
                response = provider.call(*launch_command(record, config))
            if type(response.get("new_contract")) is not int or response.get("success") is not True:
                raise RuntimeError("ambiguous create; no retry")
            until = time.monotonic() + 900
            while time.monotonic() < until:
                with locked():
                    record = read(lease_path)
                    if record["status"] in {"cleanup", "absent", "destroyed"}:
                        raise RuntimeError("watchdog ended lease")
                    current = reconcile(record, provider.call("list"))
                    store(lease_path, record)
                if current:
                    if record["instance"] != response["new_contract"]:
                        raise ValueError("create ID binding mismatch")
                    info = provider.call("status", record["instance"])
                    if info["actual_status"] == "running":
                        break
                    if info["actual_status"] in {"exited", "offline"}:
                        raise RuntimeError("serving instance failed")
                time.sleep(5)
            else:
                raise RuntimeError("instance startup timeout")
            (directory / "serving-port-metadata.json").write_text(
                json.dumps({"instance": record["instance"], "ports": info.get("ports")})
            )
            config.update(host=info["public_ipaddr"], port=serving_port(info.get("ports")))
            until = time.monotonic() + 1800
            while time.monotonic() < until:
                with locked():
                    record = read(lease_path)
                    if record["status"] in {"cleanup", "absent", "destroyed"}:
                        raise RuntimeError("watchdog ended lease")
                if time.time() >= record["deadline"]:
                    raise RuntimeError("lease expired before readiness")
                try:
                    status, body = request(
                        config["host"],
                        config["port"],
                        config["cert"],
                        config["api_key"],
                        "GET",
                        "/v1/models",
                        timeout=10,
                    )
                    if status == 200 and any(
                        x.get("id") == "Aleph-Alpha/Kolibri-1" for x in json.loads(body)["data"]
                    ):
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(10)
            else:
                raise RuntimeError("TLS model readiness timeout")
            with locked():
                record = read(lease_path)
                if record["status"] in {"cleanup", "absent", "destroyed"}:
                    raise RuntimeError("watchdog ended lease")
                record["status"] = "running"
                store(lease_path, record)
            print(
                json.dumps(
                    {"label": label, "instance": record["instance"], "status": "serving-ready"}
                ),
                flush=True,
            )
        else:
            config.update(host="1.1.1.1", port=443)
        # Private key never enters runner namespace, only public certificate + disposable token.
        config.pop("key")
        pod = deploy(
            kube, record, config, directory, cpu=args.execute_cpu_preflight, checkpoint=checkpoint
        )
        end = time.monotonic() + max(0, record["deadline"] - time.time())
        first_result = False
        while time.monotonic() < end:
            progress = collect(kube, record, pod, directory)
            if progress["saved_rows"] and not first_result:
                event = {
                    "event": "first-result",
                    "label": label,
                    "saved_rows": progress["saved_rows"],
                    "error_rows": progress.get("error_rows", 0),
                }
                (directory / "first-result.json").write_text(json.dumps(event))
                print(json.dumps(event), flush=True)
                first_result = True
            if progress["runner"] in {"complete", "failed", "preflight-complete"}:
                if args.execute_approved and (
                    progress["runner"] != "complete" or progress["saved_rows"] != 50
                ):
                    benchmark_failed = True
                    raise RuntimeError("benchmark incomplete; partial rows retained")
                if args.execute_approved:
                    if progress.get("completion_validated") is False:
                        raise ValueError("current exported checkpoint is not validated complete")
                    require_complete_checkpoint(directory)
                if progress["runner"] == "failed":
                    raise RuntimeError("runner failed")
                print(json.dumps(progress), flush=True)
                return 0
            if args.execute_approved and time.time() >= record["deadline"]:
                raise RuntimeError("benchmark exceeded TTL")
            time.sleep(10)
        raise RuntimeError("controller deadline exceeded")
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        import traceback

        benchmark_failed = benchmark_failed or (args.execute_approved and pod is not None)
        save_failure(directory, error, prefix="controller-failure", secrets=(config["api_key"],))
        frames = [
            {"function": f.name, "line": f.lineno}
            for f in traceback.extract_tb(error.__traceback__)
        ]
        (directory / "controller-status.json").write_text(
            json.dumps(
                {
                    "status": "failed",
                    "label": label,
                    "error_type": type(error).__name__,
                    "frames": frames,
                }
            )
        )
        print(
            json.dumps({"status": "failed", "label": label, "artifacts": str(directory)}),
            flush=True,
        )
        return 2
    finally:
        if (
            attempted
            and benchmark_failed
            and retain_failure(lease_path, record, kube, pod, directory, config, provider)
        ):
            private_write(directory / "cleanup-summary.json", '{"verified":false,"retained":true}')
            return 2
        cleanup_ok = finish_namespace(kube, record, pod, directory, secrets=(config["api_key"],))
        if attempted:
            logs_ok = finish_provider_logs(record, directory, config, provider)
            cleanup_ok = cleanup_ok and logs_ok
            with locked():
                record = read(lease_path)
                result = watchdog(
                    record,
                    provider,
                    now=time.time(),
                    execute=True,
                    finish=True,
                    save=lambda r: store(lease_path, r),
                )
                (directory / "provider-cleanup.json").write_text(json.dumps({"status": result}))
                cleanup_ok = cleanup_ok and result == "absent"
        (directory / "cleanup-summary.json").write_text(json.dumps({"verified": cleanup_ok}))
        if not cleanup_ok:
            print(json.dumps({"status": "cleanup-unresolved", "label": label}), flush=True)
            return 2


if __name__ == "__main__":
    raise SystemExit(main())

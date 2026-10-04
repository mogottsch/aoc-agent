"""Bounded fake-only Kubernetes recipe; rendering never deploys resources."""

import copy
import ipaddress
import re

IMAGE = "python:3.13-slim-bookworm@sha256:88310c082760d93ac7c74d579e95e53a4ab6ea52dd8901abc61a103daf488ac4"
SC = {
    "allowPrivilegeEscalation": False,
    "readOnlyRootFilesystem": True,
    "capabilities": {"drop": ["ALL"]},
}
PSC = {
    "runAsNonRoot": True,
    "runAsUser": 10001,
    "runAsGroup": 10001,
    "fsGroup": 10001,
    "seccompProfile": {"type": "RuntimeDefault"},
}


def resources(namespace, record, public_ips):
    from cpu_watchdog import validate

    validate(record)
    if not re.fullmatch(r"kolibri-cpu-[a-z0-9-]{1,32}", namespace):
        raise ValueError("dedicated namespace required")
    if not public_ips:
        raise ValueError("nonempty public IPv4 package allowlist required")
    for ip in public_ips:
        if not ipaddress.ip_address(ip).is_global or ipaddress.ip_address(ip).version != 4:
            raise ValueError("public IPv4 package sources only")

    def obj(kind, name, spec=None):
        o = {"apiVersion": "v1", "kind": kind, "metadata": {"name": name, "namespace": namespace}}
        if kind == "Job":
            o["apiVersion"] = "batch/v1"
        if kind == "NetworkPolicy":
            o["apiVersion"] = "networking.k8s.io/v1"
        if spec is not None:
            o["spec"] = spec
        return o

    ns = obj("Namespace", namespace)
    ns["metadata"].pop("namespace")
    ns["metadata"]["labels"] = {
        "pod-security.kubernetes.io/enforce": "restricted",
        "pod-security.kubernetes.io/enforce-version": "v1.32",
        "kolibri-rehearsal": record["owner"],
    }
    objects = [
        ns,
        obj(
            "ResourceQuota",
            "bounded",
            {
                "hard": {
                    "limits.cpu": "2",
                    "limits.memory": "2Gi",
                    "requests.memory": "1Gi",
                    "limits.ephemeral-storage": "4Gi",
                    "pods": "6",
                    "count/jobs.batch": "3",
                    "services": "1",
                    "persistentvolumeclaims": "0",
                    "count/secrets": "0",
                }
            },
        ),
    ]
    objects.append(
        obj(
            "NetworkPolicy",
            "default-deny",
            {"podSelector": {}, "policyTypes": ["Ingress", "Egress"], "ingress": [], "egress": []},
        )
    )
    dns = {
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
    for role, port in (("runner", 8080), ("watchdog", 8081)):
        egress = {
            "to": [{"podSelector": {"matchLabels": {"role": "provider"}}}],
            "ports": [{"port": port, "protocol": "TCP"}],
        }
        objects.append(
            obj(
                "NetworkPolicy",
                role + ("-fixture" if role == "runner" else "-provider"),
                {
                    "podSelector": {"matchLabels": {"role": role}},
                    "policyTypes": ["Egress"],
                    "egress": [egress, copy.deepcopy(dns)],
                },
            )
        )
    objects.append(
        obj(
            "NetworkPolicy",
            "provider-ingress",
            {
                "podSelector": {"matchLabels": {"role": "provider"}},
                "policyTypes": ["Ingress"],
                "ingress": [
                    {
                        "from": [{"podSelector": {"matchLabels": {"role": role}}}],
                        "ports": [{"port": port, "protocol": "TCP"}],
                    }
                    for role, port in (("runner", 8080), ("watchdog", 8081))
                ],
            },
        )
    )
    objects.append(
        obj(
            "NetworkPolicy",
            "install-public",
            {
                "podSelector": {"matchLabels": {"role": "runner"}},
                "policyTypes": ["Egress"],
                "egress": [
                    {
                        "to": [{"ipBlock": {"cidr": ip + "/32"}} for ip in public_ips],
                        "ports": [{"port": 443, "protocol": "TCP"}],
                    }
                ],
            },
        )
    )
    objects.append(
        obj(
            "Service",
            "fake-provider",
            {
                "selector": {"role": "provider"},
                "type": "ClusterIP",
                "ports": [
                    {"name": "fixture", "port": 8080, "targetPort": 8080},
                    {"name": "provider", "port": 8081, "targetPort": 8081},
                ],
            },
        )
    )
    env = {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "HOME": "/work",
        "TMPDIR": "/tmp",
        "PYTHONPATH": "/work/deps:/work/src:/bundle",
        "LOGFIRE_SEND_TO_LOGFIRE": "false",
        "EXECUTION_SANDBOX": "local",
        "AOC_SESSION_TOKEN": "SYNTHETIC_NOT_A_COOKIE",
    }

    def container(name, command, *, big=False):
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

    for role, command in (
        ("provider", ["python", "/bundle/cpu_fake_provider.py"]),
        ("runner", ["python", "/bundle/cpu_fixture.py"]),
        (
            "watchdog",
            ["python", "/bundle/cpu_watchdog.py", "/bundle/record.json", "--execute-fake"],
        ),
    ):
        pod = {
            "automountServiceAccountToken": False,
            "enableServiceLinks": False,
            "restartPolicy": "Never",
            "terminationGracePeriodSeconds": 5,
            "securityContext": copy.deepcopy(PSC),
            "containers": [container(role, command, big=role == "runner")],
            "volumes": [
                {"name": "bundle", "configMap": {"name": "cpu-bundle", "defaultMode": 292}},
                {"name": "work", "emptyDir": {"sizeLimit": "2Gi" if role == "runner" else "16Mi"}},
                {"name": "tmp", "emptyDir": {"sizeLimit": "128Mi"}},
            ],
        }
        if role in {"provider", "watchdog"}:
            pod["volumes"].append(
                {"name": "record", "configMap": {"name": "cpu-record", "defaultMode": 292}}
            )
            pod["containers"][0]["volumeMounts"].append(
                {"name": "record", "mountPath": "/record", "readOnly": True}
            )
        if role == "watchdog":
            pod["containers"][0]["command"][2] = "/record/record.json"
        if role == "runner":
            pod["containers"][0]["env"].append({"name": "CRASH_AFTER_FIXTURE", "value": "1"})
            install = "import tarfile,subprocess; tarfile.open('/bundle/source.tar.gz').extractall('/work/src',filter='data'); subprocess.run(['python','-m','pip','--isolated','install','--index-url','https://pypi.org/simple','--only-binary=:all:','--require-hashes','--no-cache-dir','--target','/work/deps','-r','/bundle/requirements.txt'],check=True)"
            pod["initContainers"] = [
                container("install-public-deps", ["python", "-c", install], big=True)
            ]
            for item in pod["initContainers"][0]["env"]:
                if item["name"] == "TMPDIR":
                    item["value"] = "/work"
        objects.append(
            obj(
                "Job",
                "cpu-" + role,
                {
                    "backoffLimit": 0,
                    "activeDeadlineSeconds": 600 if role in {"runner", "provider"} else 150,
                    "ttlSecondsAfterFinished": 900,
                    "template": {"metadata": {"labels": {"role": role}}, "spec": pod},
                },
            )
        )
    return objects

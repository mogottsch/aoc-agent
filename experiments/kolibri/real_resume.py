"""Attach an approved existing lease without a create call or TTL extension."""

import argparse
import json
import os
import re
import subprocess
import time
import traceback
from pathlib import Path

from diagnostics import save_failure
from real_controller import (
    Kube,
    KubeError,
    collect,
    deploy,
    finish_namespace,
    finish_provider_logs,
    owned_dead_runner,
    prepare_dead_runner,
    recover_checkpoint,
    require_complete_checkpoint,
    retain_failure,
    serving_port,
)
from real_lifecycle import STATE, Vast, locked, read, reconcile, store, watchdog
from real_transport import request


def derive_nonerror_checkpoint(source, destination):
    """Offline only: freeze raw evidence and derive a NEW fresh-rental resume seed.

    Existing destinations are never reused. Only explicit error rows are excluded;
    wrong answers stay unchanged. No lease, budget, namespace or provider is touched.
    """
    from checkpoint import filtered_checkpoint, validated_checkpoint

    from real_controller import BASE  # isort: skip
    from run import load_experiment

    source, destination = Path(source), Path(destination).absolute()
    if ".." in destination.parts or any(p.is_symlink() for p in destination.parents):
        raise ValueError("unsafe derived checkpoint destination")
    config = load_experiment(BASE / "config.yaml")
    pins = json.loads((BASE / "pins.json").read_text())
    filtered = filtered_checkpoint(source, config, pins)
    destination.mkdir(mode=0o700)  # Exclusive; never overwrite a prior seed.
    raw = destination / "raw"
    raw.mkdir(mode=0o700)
    for name, body in (
        (destination / "results.jsonl", filtered["results_bytes"]),
        (destination / "manifest.json", filtered["manifest_bytes"]),
        (raw / "results.jsonl", filtered["raw_results_bytes"]),
        (raw / "manifest.json", filtered["raw_manifest_bytes"]),
    ):
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
        with os.fdopen(fd, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
    checked = validated_checkpoint(destination, config, pins)
    if (
        checked["results_bytes"] != filtered["results_bytes"]
        or checked["manifest_bytes"] != filtered["manifest_bytes"]
        or checked["completed"] != filtered["completed"]
    ):
        raise ValueError("derived checkpoint verification failed")
    seed = json.loads(filtered["manifest_bytes"])["seed"]
    return {
        "directory": str(destination),
        "retained_rows": len(checked["completed"]),
        "filtered_errors": seed["filtered_errors"],
        "raw_provenance": seed,
        "provenance": checked["provenance"],
    }


def run_existing(path, *, rerun_failed=False, replace_dead_runner=False):
    path = Path(path)
    if path.parent != STATE or path.is_symlink():
        raise ValueError("exact active lease path required")
    with locked():
        record = read(path)
        if path.name != record["label"] + ".json" or record["instance"] is None:
            raise ValueError("bound existing lease required")
        if record["status"] not in {"launching", "running", "debug-retained"}:
            raise ValueError("existing lease is not resumable")
        retained = record["status"] == "debug-retained"
        if rerun_failed and replace_dead_runner:
            raise ValueError("choose replay or dead runner replacement")
        if retained != (rerun_failed or replace_dead_runner):
            raise ValueError(
                "retained failure requires explicit --rerun-failed or --replace-dead-runner"
            )
        provider = Vast()
        if reconcile(record, provider.call("list")) is None:
            raise ValueError("existing resource ownership not confirmed")
    original_binding = (record["instance"], record["start_date"], record["deadline"])
    frozen = {
        k: record[k]
        for k in (
            "label",
            "namespace",
            "created",
            "reserve",
            "hourly_ceiling",
            "download_ceiling",
            "offer",
        )
    }
    directory = STATE / record["label"]
    kube = Kube()
    # Reject foreign/running targets before entering cleanup-capable execution.
    owned = owned_dead_runner(kube, record, directory) if replace_dead_runner else None
    pod = owned["pod"] if owned else None
    config = {}
    result = 2
    benchmark_failed = replace_dead_runner
    try:
        if time.time() >= record["deadline"]:
            raise RuntimeError("existing lease expired")
        if directory.is_symlink() or directory.stat().st_mode & 0o077:
            raise ValueError("private existing artifact directory required")
        if (directory / "namespace-attempted").exists() and not retained:
            raise ValueError("resume only supported before namespace creation")
        checkpoint = recover_checkpoint(directory) if not retained else ()
        config_path = directory / "resume-transport.json"
        st = config_path.lstat()
        if (
            config_path.is_symlink()
            or st.st_uid != os.getuid()
            or st.st_mode & 0o077
            or st.st_size > 32768
        ):
            raise ValueError("unsafe recovered transport")
        config = json.loads(config_path.read_text())
        if (
            set(config) != {"api_key", "cert", "key"}
            or not isinstance(config["api_key"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", config["api_key"])
            or config["cert"] != (directory / "server.crt").read_text()
            or config["key"] != (directory / "server.key").read_text()
        ):
            raise ValueError("recovered transport does not match original launch")
        old_failure = directory / "controller-status.json"
        if old_failure.exists():
            old_failure.rename(directory / "initial-controller-failure.json")

        def active(*, billing=False):
            with locked():
                current = read(path)
                if current["status"] not in {"launching", "running", "debug-retained"}:
                    raise RuntimeError("watchdog ended existing lease")
                if (
                    current["instance"],
                    current["start_date"],
                    current["deadline"],
                ) != original_binding:
                    raise ValueError("existing binding or original deadline changed")
                if any(current[k] != value for k, value in frozen.items()):
                    raise ValueError("existing lease budget or namespace changed")
                if time.time() >= original_binding[2]:
                    raise RuntimeError("original lease expired")
                if (
                    billing
                    and watchdog(
                        current,
                        provider,
                        now=time.time(),
                        execute=True,
                        save=lambda r: store(path, r),
                    )
                    != "not-due"
                ):
                    raise RuntimeError("existing lease failed billing gates")
                return current

        while True:
            active()
            info = provider.call("status", record["instance"])
            if info["actual_status"] == "running":
                break
            if info["actual_status"] in {"exited", "offline"}:
                raise RuntimeError("existing serving instance failed")
            time.sleep(5)
        (directory / "serving-port-metadata.json").write_text(
            json.dumps({"instance": record["instance"], "ports": info.get("ports")})
        )
        config.update(host=info["public_ipaddr"], port=serving_port(info.get("ports")))
        event = {
            "instance": record["instance"],
            "status": "container-running-port-verified",
            "port": config["port"],
            "deadline": record["deadline"],
        }
        (directory / "resume-status.json").write_text(json.dumps(event))
        print(json.dumps(event), flush=True)
        while True:
            active()
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
        with locked():
            record = read(path)
            if (
                record["status"] not in {"launching", "running", "debug-retained"}
                or (record["instance"], record["start_date"], record["deadline"])
                != original_binding
                or time.time() >= original_binding[2]
            ):
                raise RuntimeError("watchdog ended lease before deployment")
            if (
                watchdog(
                    record, provider, now=time.time(), execute=True, save=lambda r: store(path, r)
                )
                != "not-due"
            ):
                raise RuntimeError("existing lease failed billing gates")
            record["status"] = "running"
            store(path, record)
        print(json.dumps({"instance": record["instance"], "status": "serving-ready"}), flush=True)
        config.pop("key")
        expected_attempt = None
        if replace_dead_runner:
            binding, checkpoint = prepare_dead_runner(
                kube, record, directory, config, check_active=lambda: active(billing=True)
            )
            pod = deploy(
                kube,
                record,
                config,
                directory,
                checkpoint=checkpoint,
                owned_replace=binding,
                check_active=lambda: active(billing=True),
            )
        elif retained:
            namespace = kube.get(None, "namespace", record["namespace"])
            if (
                namespace is None
                or namespace["metadata"].get("labels", {}).get("kolibri-real") != record["label"]
            ):
                raise ValueError("retained namespace ownership mismatch")
            items = json.loads(
                kube.call(
                    "-n", record["namespace"], "get", "pods", "-l", "role=runner", "-o", "json"
                )
            )["items"]
            hold = json.loads((directory / "debug-hold.json").read_text())
            if (
                len(items) != 1
                or items[0]["metadata"]["name"] != hold["pod"]
                or not any(
                    c["name"] == "runner" and "running" in c.get("state", {})
                    for c in items[0].get("status", {}).get("containerStatuses", [])
                )
            ):
                raise ValueError("original retained runner is not exec-able")
            pod = hold["pod"]
            active()
            expected_attempt = int(
                kube.call(
                    "-n",
                    record["namespace"],
                    "exec",
                    pod,
                    "-c",
                    "runner",
                    "--",
                    "python",
                    "-c",
                    "from pathlib import Path; from real_runner import request_replay; print(request_replay(Path('/work')))",
                ).strip()
            )
        else:
            pod = deploy(kube, record, config, directory, checkpoint=checkpoint)
        first = False
        export_retries = 0
        while True:
            active(billing=True)
            try:
                progress = collect(kube, record, pod, directory, secrets=(config["api_key"],))
            except (KubeError, ValueError, FileNotFoundError) as error:
                changing = (
                    (
                        isinstance(error, KubeError)
                        and "FileNotFoundError:" in error.body
                        and "'/work/" in error.body
                    )
                    or isinstance(error, FileNotFoundError)
                    or (
                        type(error) is ValueError
                        and str(error)
                        in {
                            "artifact changed during export; retry before cleanup",
                            "incomplete artifact segment",
                        }
                    )
                    or (
                        isinstance(error, KubeError) and "ValueError: artifact shrank" in error.body
                    )
                )
                if not changing or export_retries >= 3:
                    raise
                active(billing=True)
                runner = json.loads(
                    kube.call(
                        "-n",
                        record["namespace"],
                        "exec",
                        pod,
                        "-c",
                        "runner",
                        "--",
                        "python",
                        "-c",
                        "import json; from pathlib import Path; "
                        "p=Path('/work/runner-status.json'); "
                        "\ntry: status=json.loads(p.read_text())"
                        "\nexcept FileNotFoundError: status={}"
                        "\nprint(json.dumps(status))",
                    )
                )
                attempt = runner.get("attempt")
                transitioning = expected_attempt is not None and (
                    not runner
                    or (attempt == expected_attempt - 1 and runner.get("status") == "failed")
                )
                running = runner.get("status") == "running" and (
                    type(attempt) is int
                    and attempt >= 1
                    and (expected_attempt is None or attempt == expected_attempt)
                )
                if not (transitioning or running):
                    raise
                export_retries += 1
                time.sleep(1)
                continue
            if expected_attempt is not None and progress.get("attempt") != expected_attempt:
                time.sleep(1)
                continue
            export_retries = 0
            if progress["saved_rows"] and not first:
                event = {
                    "event": "first-result",
                    "label": record["label"],
                    "saved_rows": progress["saved_rows"],
                    "error_rows": progress.get("error_rows", 0),
                }
                (directory / "first-result.json").write_text(json.dumps(event))
                print(json.dumps(event), flush=True)
                first = True
            if progress["runner"] in {"complete", "failed"}:
                if progress["runner"] != "complete" or progress["saved_rows"] != 50:
                    benchmark_failed = True
                    raise RuntimeError("benchmark incomplete")
                if progress.get("completion_validated") is False:
                    raise ValueError("current exported checkpoint is not validated complete")
                require_complete_checkpoint(directory)
                print(json.dumps(progress), flush=True)
                result = 0
                benchmark_failed = False
                break
            time.sleep(10)
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        benchmark_failed = benchmark_failed or pod is not None
        status = {
            "status": "failed",
            "label": record["label"],
            "error_type": type(error).__name__,
            "frames": [
                {"function": f.name, "line": f.lineno}
                for f in traceback.extract_tb(error.__traceback__)
            ],
        }
        save_failure(
            directory, error, prefix="controller-failure", secrets=(config.get("api_key", ""),)
        )
        (directory / "controller-status.json").write_text(json.dumps(status))
        print(json.dumps(status), flush=True)
    finally:
        if benchmark_failed and retain_failure(
            path, record, kube, pod, directory, config, provider
        ):
            return 2
        cleanup_ok = finish_namespace(
            kube, record, pod, directory, secrets=(config.get("api_key", ""),)
        )
        logs_ok = finish_provider_logs(record, directory, config, provider)
        cleanup_ok = cleanup_ok and logs_ok
        with locked():
            record = read(path)
            outcome = watchdog(
                record,
                provider,
                now=time.time(),
                execute=True,
                finish=True,
                save=lambda r: store(path, r),
            )
            (directory / "provider-cleanup.json").write_text(json.dumps({"status": outcome}))
            cleanup_ok = cleanup_ok and outcome == "absent"
        (directory / "cleanup-summary.json").write_text(json.dumps({"verified": cleanup_ok}))
        if not cleanup_ok:
            result = 2
            print(
                json.dumps({"status": "cleanup-unresolved", "label": record["label"]}), flush=True
            )
    return result


def stop_existing(path):
    """Explicit operator stop: billing cleanup takes priority over artifact export."""
    path = Path(path)
    if path.parent != STATE or path.is_symlink():
        raise ValueError("exact active lease path required")
    with locked():
        record = read(path)
        if path.name != record["label"] + ".json":
            raise ValueError("lease filename mismatch")
        outcome = watchdog(
            record,
            Vast(),
            now=time.time(),
            execute=True,
            finish=True,
            save=lambda r: store(path, r),
        )
    directory = STATE / record["label"]
    namespace_ok = finish_namespace(Kube(), record, None, directory)
    print(json.dumps({"status": outcome, "namespace_absent": namespace_ok}), flush=True)
    return 0 if outcome == "absent" and namespace_ok else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--resume-approved", type=Path)
    mode.add_argument("--stop-approved", type=Path)
    replay = parser.add_mutually_exclusive_group()
    replay.add_argument("--rerun-failed", action="store_true")
    replay.add_argument("--replace-dead-runner", action="store_true")
    args = parser.parse_args()
    if args.stop_approved and (args.rerun_failed or args.replace_dead_runner):
        parser.error("stop does not rerun")
    raise SystemExit(
        stop_existing(args.stop_approved)
        if args.stop_approved
        else run_existing(
            args.resume_approved,
            rerun_failed=args.rerun_failed,
            replace_dead_runner=args.replace_dead_runner,
        )
    )

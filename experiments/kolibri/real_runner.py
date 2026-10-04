"""In-pod launcher: waits for trusted network-isolation release, retains artifacts."""

import codecs
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from diagnostics import RedactingStream, private_write, save_failure


def run_logged(args, cwd, env, directory):
    """Drain both streams locally, without truncation or forwarding to container logs."""
    from memory_telemetry import memory_sampler

    errors = []
    secrets = tuple(v for k, v in env.items() if re.search(r"TOKEN|SECRET|PASSWORD|API_KEY", k))
    handles = []
    try:
        for name in ("runner-stdout.log", "runner-stderr.log"):
            fd = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            handles.append(os.fdopen(fd, "w", encoding="utf-8"))
        with (
            memory_sampler(directory),
            subprocess.Popen(
                args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            ) as process,
        ):

            def drain(stream, file):
                try:
                    decoder = codecs.getincrementaldecoder("utf-8")("backslashreplace")
                    redactor = RedactingStream(secrets)
                    for chunk in iter(lambda: stream.read1(65536), b""):
                        file.write(redactor.feed(decoder.decode(chunk)))
                        file.flush()
                        os.fsync(file.fileno())
                    file.write(redactor.feed(decoder.decode(b"", final=True), final=True))
                    file.flush()
                    os.fsync(file.fileno())
                except BaseException as error:
                    errors.append(error)
                    process.terminate()
                finally:
                    stream.close()

            threads = [
                threading.Thread(target=drain, args=(s, f))
                for s, f in zip((process.stdout, process.stderr), handles, strict=True)
            ]
            for thread in threads:
                thread.start()
            code = process.wait()
            for thread in threads:
                thread.join()
            if errors:
                raise RuntimeError("runner log preservation failed") from errors[0]
            return code
    finally:
        for file in handles:
            file.close()


def command(release):
    if set(release) != {"action", "run_id"} or release["action"] not in {"preflight", "run"}:
        raise ValueError("invalid release")
    if not re.fullmatch(r"hermes-kolibri-[0-9a-f]{32}", release["run_id"]):
        raise ValueError("invalid run ID")
    args = [sys.executable, "/work/repo/experiments/kolibri/run.py", release["action"]]
    if release["action"] == "run":
        args += ["--execute", "--run-id", release["run_id"]]
        checkpoint = Path("/work/checkpoint")
        if checkpoint.exists() or checkpoint.is_symlink():
            args += ["--resume-from", str(checkpoint)]
    return args


def child_environment(source):
    """Forward only the launch allowlist; fail closed on unsupported execution knobs."""
    if any(
        k.startswith("EXECUTION_") and k not in {"EXECUTION_SANDBOX", "EXECUTION_MEMORY_MB"}
        for k in source
    ):
        raise ValueError("unsupported execution environment")
    backend = source.get("EXECUTION_SANDBOX", "local")
    if backend not in {"local", "cgroup", "rlimit"}:
        raise ValueError("invalid EXECUTION_SANDBOX")
    if backend == "rlimit":
        if (
            type(source.get("EXECUTION_MEMORY_MB")) is not str
            or source["EXECUTION_MEMORY_MB"] != "4096"
        ):
            raise ValueError("EXECUTION_SANDBOX=rlimit requires literal EXECUTION_MEMORY_MB=4096")
    elif "EXECUTION_MEMORY_MB" in source:
        raise ValueError("explicit memory forwarding requires EXECUTION_SANDBOX=rlimit")
    return {
        k: source[k]
        for k in (
            "PATH",
            "HOME",
            "TMPDIR",
            "PYTHONPATH",
            "PYTHONDONTWRITEBYTECODE",
            "PYTHONUNBUFFERED",
            "LOGFIRE_SEND_TO_LOGFIRE",
            "EXECUTION_SANDBOX",
            "EXECUTION_MEMORY_MB",
            "AOC_SESSION_TOKEN",
        )
        if k in source
    }


def main():
    end = time.monotonic() + 420
    gate = Path("/work/released.json")
    while not gate.exists():
        if time.monotonic() >= end:
            raise SystemExit("isolation gate timeout")
        time.sleep(1)
    release = json.loads(gate.read_text())
    command(release)
    env = child_environment(os.environ)
    env["KOLIBRI_API_KEY"] = json.loads(Path("/serving/transport.json").read_text())["api_key"]
    work = Path("/work")
    attempt = 1
    execute_attempt(release, work, env, attempt)
    # Keep the runner exec-able. Only an explicit trusted replay request runs again.
    while True:
        replay = work / "replay.json"
        if replay.exists():
            requested = json.loads(replay.read_text())
            if requested != {"attempt": attempt + 1}:
                raise ValueError("invalid replay sequence")
            replay.unlink()
            attempt += 1
            execute_attempt(release, work, env, attempt)
        time.sleep(1)


def request_replay(work):
    """Queue one same-container attempt; never accept shell commands or credentials."""
    status = json.loads((work / "runner-status.json").read_text())
    if status.get("status") != "failed":
        raise ValueError("replay requires failed idle runner")
    attempt = status.get("attempt")
    if type(attempt) is not int or not 1 <= attempt < 9999:
        raise ValueError("invalid attempt")
    target = work / "replay.json"
    if target.exists() or target.is_symlink():
        raise ValueError("replay already pending")
    fd, name = tempfile.mkstemp(prefix=".replay-", dir=work)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump({"attempt": attempt + 1}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)  # Atomic publication without overwriting another request.
        except FileExistsError:
            raise ValueError("replay already pending") from None
    finally:
        temporary.unlink(missing_ok=True)
    return attempt + 1


def select_checkpoint(work, archived, args):
    """Persist the latest validated archive; never regress to the initial seed."""
    pointer = work / "latest-checkpoint.json"
    if (
        archived is None
        and "--resume-from" not in args
        and not (pointer.exists() or pointer.is_symlink())
    ):
        return
    from checkpoint import validated_checkpoint

    base = work / "repo/experiments/kolibri"
    sys.path.insert(0, str(base))
    from run import load_experiment

    config = load_experiment(base / "config.yaml")
    pins = json.loads((base / "pins.json").read_text())
    previous = None
    source = None
    if pointer.exists() or pointer.is_symlink():
        if pointer.is_symlink():
            raise ValueError("unsafe latest checkpoint pointer")
        metadata = json.loads(pointer.read_text())
        relative = metadata.get("directory", "")
        if not isinstance(relative, str) or not re.fullmatch(
            r"attempts/[0-9]{4}/benchmark", relative
        ):
            raise ValueError("invalid latest checkpoint pointer")
        source = work / relative
        previous = validated_checkpoint(source, config, pins)
        if metadata != {"directory": relative, "provenance": previous["provenance"]}:
            raise ValueError("latest checkpoint hash or provenance mismatch")
    if archived is not None:
        candidate = validated_checkpoint(archived, config, pins)
        if previous is not None and not previous["completed"] <= candidate["completed"]:
            raise ValueError("replay checkpoint would regress validated progress")
        source = archived
        private_write(
            pointer,
            json.dumps(
                {
                    "directory": str(archived.relative_to(work)),
                    "provenance": candidate["provenance"],
                }
            ),
        )
    if source is None and "--resume-from" in args:
        source = Path(args[args.index("--resume-from") + 1])
        validated_checkpoint(source, config, pins)
    if source is not None:
        if "--resume-from" in args:
            index = args.index("--resume-from")
            del args[index : index + 2]
        args += ["--resume-from", str(source)]


def execute_attempt(release, work, env, attempt):
    """Archive previous attempt before reuse; preserve the current export paths."""
    args = command(release)
    archived = None
    if attempt > 1:
        archive = work / "attempts" / f"{attempt - 1:04d}"
        archive.mkdir(mode=0o700, parents=True)
        for name in (
            "runner-status.json",
            "runner-stdout.log",
            "runner-stderr.log",
            "memory-metrics.jsonl",
            "memory-metrics.metadata.json",
            "runner-failure.json",
            "runner-failure-traceback.txt",
        ):
            source = work / name
            if source.is_symlink():
                raise ValueError("unsafe attempt artifact")
            if source.exists():
                source.rename(archive / name)
        benchmark = work / "repo/experiments/kolibri/runs" / release["run_id"]
        if benchmark.is_symlink():
            raise ValueError("unsafe benchmark artifact")
        if benchmark.exists():
            archived = archive / "benchmark"
            benchmark.rename(archived)
    private_write(
        work / "runner-status.json", json.dumps({"status": "running", "attempt": attempt})
    )
    try:
        if release["action"] == "run":
            select_checkpoint(work, archived, args)
        code = run_logged(args, str(work / "repo"), env, work)
    except BaseException as error:
        save_failure(work, error, prefix="runner-failure")
        code = 1
    status = (
        "failed"
        if code
        else "preflight-complete"
        if release["action"] == "preflight"
        else "complete"
    )
    private_write(
        work / "runner-status.json",
        json.dumps({"status": status, "exit_code": code, "attempt": attempt}),
    )
    return status


if __name__ == "__main__":
    main()

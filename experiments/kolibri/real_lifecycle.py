"""Trusted, narrow Vast lifecycle. Never import this into the generated-code pod."""

import argparse
import fcntl
import json
import math
import os
import re
import subprocess
import time
from pathlib import Path

STATE = Path("/opt/data/kolibri-real-leases")
MAX_TTL_SECONDS = 10800
DEFAULT_TTL_SECONDS = 5400
FIELDS = {
    "version",
    "label",
    "created",
    "deadline",
    "reserve",
    "hourly_ceiling",
    "download_ceiling",
    "instance",
    "start_date",
    "status",
    "offer",
    "namespace",
}


def validate(record):
    extended = "extension" in record
    if set(record) != FIELDS | ({"extension"} if extended else set()) or record["version"] != 1:
        raise ValueError("invalid lease schema")
    if not re.fullmatch(r"hermes-kolibri-[0-9a-f]{32}", record["label"]):
        raise ValueError("invalid lease label")
    if not re.fullmatch(r"kolibri-real-[0-9a-f]{12}", record["namespace"]):
        raise ValueError("invalid namespace")
    for name in ("created", "deadline", "reserve", "hourly_ceiling", "download_ceiling"):
        if (
            type(record[name]) not in (int, float)
            or not math.isfinite(record[name])
            or record[name] < 0
        ):
            raise ValueError("invalid lease number")
    if not extended and not 0 < record["deadline"] - record["created"] <= MAX_TTL_SECONDS:
        raise ValueError("maximum 3 hour TTL required")
    if extended:
        from real_extend import validate_extension

        validate_extension(record)
    if not 0 < record["hourly_ceiling"] <= 4.7 or record["download_ceiling"] > 1:
        raise ValueError("budget outside approved bounds")
    for name in ("instance", "offer"):
        if record[name] is None and name == "instance":
            continue
        if type(record[name]) is not int or record[name] <= 0:
            raise ValueError("invalid provider ID")
    if record["start_date"] is not None:
        if type(record["start_date"]) not in (int, float) or not math.isfinite(
            record["start_date"]
        ):
            raise ValueError("invalid incarnation")
    if record["status"] not in {
        "prepared",
        "launching",
        "running",
        "debug-retained",
        "cleanup",
        "absent",
        "destroyed",
    }:
        raise ValueError("invalid state")
    if record["status"] in {"destroyed", "debug-retained"} and (
        record["instance"] is None or record["start_date"] is None
    ):
        raise ValueError("terminal or retained lease requires verified binding")


class Vast:
    def call(self, command, *args):
        if command not in {"balance", "list", "status", "search", "launch", "destroy"}:
            raise ValueError("unsupported operation")
        if command == "destroy":
            from vast_delete import destroy

            if len(args) != 1:
                raise ValueError("delete requires exactly one owned provider ID")
            return destroy(args[0])
        # Wrapper fetches Vault credential internally; no inherited keys or endpoint overrides.
        from vast_credentials import credential_env

        with credential_env() as env:
            p = subprocess.run(
                ["/usr/local/bin/vastctl", command, *map(str, args)],
                capture_output=True,
                text=True,
                env=env,
                stdin=subprocess.DEVNULL,
                timeout=90,
            )
        if p.returncode:
            raise RuntimeError("Vast operation failed (provider output suppressed)")
        result = json.loads(p.stdout)
        return result


def identity(provider):
    b = provider.call("balance")
    if (
        b.get("id") != 639482
        or b.get("username") != "moritz-hermes-bot"
        or b.get("is_team") is not True
    ):
        raise ValueError("unexpected provider identity")
    credit = b["credit"]
    if type(credit) not in (int, float) or not math.isfinite(credit):
        raise ValueError("invalid credit")
    return credit


def reconcile(record, rows):
    """Bind a lost create response once; never rent again after an ambiguous response."""
    matches = [r for r in rows if r.get("label") == record["label"]]
    if len(matches) > 1:
        raise ValueError("duplicate lease label; manual reconciliation required")
    if record["instance"] is not None:
        target = [r for r in rows if r.get("id") == record["instance"]]
        if not target:
            return None
        if (
            len(target) != 1
            or target[0].get("label") != record["label"]
            or target[0].get("start_date") != record["start_date"]
        ):
            raise ValueError("ownership mismatch")
        return target[0]
    if not matches:
        return None
    r = matches[0]
    if (
        type(r.get("id")) is not int
        or r["id"] <= 0
        or type(r.get("start_date")) not in (int, float)
    ):
        raise ValueError("invalid provider binding")
    if (
        not math.isfinite(r["start_date"])
        or not record["created"] - 120 <= r["start_date"] <= record["created"] + 300
    ):
        raise ValueError("incarnation outside launch window")
    record.update(instance=r["id"], start_date=r["start_date"])
    return r


def watchdog(record, provider, *, now, execute=False, finish=False, save=lambda r: None):
    validate(record)
    if not math.isfinite(now):
        raise ValueError("invalid clock")
    if not execute:
        return "dry-run"
    if record["status"] == "destroyed":
        return "absent"
    try:
        mandatory = finish or now >= record["deadline"] or record["status"] in {"cleanup", "absent"}
        if mandatory:
            # Persist cleanup intent even if inventory/credit services are unavailable.
            record["status"] = "cleanup"
            save(record)
        current = reconcile(record, provider.call("list"))
        save(record)  # binding must survive watchdog death before delete
        if current is None:
            # Neither TTL nor inventory omission resolves an ambiguous create.
            return "awaiting-reconciliation"
        rate = current.get("dph_total")
        bad_rate = type(rate) not in (int, float) or not math.isfinite(rate) or rate < 0
        mandatory = mandatory or bad_rate or rate > record["hourly_ceiling"]
        credit = None if mandatory else identity(provider)
        if not (
            mandatory or credit <= record["reserve"] or bad_rate or rate > record["hourly_ceiling"]
        ):
            return "not-due"
        record["status"] = "cleanup"
        save(record)
        # Recheck binding before deletion; Vast has no conditional delete API.
        current = reconcile(record, provider.call("list"))
        if current is None:
            return "awaiting-reconciliation"
        ack = provider.call("destroy", record["instance"])
        # Inventory can temporarily omit a billable resource even after a rejected delete.
        if not isinstance(ack, dict) or ack.get("success") is not True:
            return "retry"
        if reconcile(record, provider.call("list")) is not None:
            return "retry"
        record["status"] = "destroyed"
        save(record)
        return "absent"
    except ValueError:
        return "ownership-or-schema-error"
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return "retry"


def secure_dir(root=STATE):
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = root.lstat()
    if root.is_symlink() or not root.is_dir() or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise ValueError("state must be private trusted directory")
    return root


def store(path, record):
    validate(record)
    secure_dir(path.parent)
    if path.is_symlink():
        raise ValueError("lease symlink forbidden")
    if "extension" in record and not path.exists():
        raise ValueError("explicit extension transaction required")
    if path.exists():
        original = read(path)
        if record.get("extension") != original.get("extension"):
            raise ValueError("extension audit is frozen; explicit transaction required")
        immutable = FIELDS - {"status", "instance", "start_date"}
        if original["instance"] is not None:
            immutable |= {"instance", "start_date"}
        if any(record[name] != original[name] for name in immutable):
            raise ValueError("lease ownership, policy and original deadline are frozen")
    import tempfile

    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".new", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(record, f)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        d = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(d)
        finally:
            os.close(d)
    finally:
        tmp.unlink(missing_ok=True)


def read(path):
    secure_dir(path.parent)
    st = path.lstat()
    if path.is_symlink() or st.st_uid != os.getuid() or st.st_mode & 0o077 or st.st_size > 8192:
        raise ValueError("unsafe lease file")
    record = json.loads(path.read_text())
    validate(record)
    if "extension" in record:
        from real_extend import verify_receipt

        verify_receipt(path, record)
    return record


def locked(root=STATE, *, timeout=600):
    secure_dir(root)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout < 0:
        raise ValueError("invalid lock wait")
    fd = os.open(root / ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return os.fdopen(fd, "w")
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("lease lock busy") from None
                time.sleep(0.1)
    except BaseException:
        os.close(fd)
        raise


def pass_once(*, execute=False, root=STATE, provider=None, now=None, kube=None):
    if not root.exists():
        return {"leases": 0, "results": [], "execution": execute}
    with locked(root, timeout=0):
        paths = sorted(root.glob("hermes-kolibri-*.json"))
        records = [(path, read(path)) for path in paths]
        results = []
        namespace_work = []
        for path, r in records:
            if path.name != r["label"] + ".json":
                raise ValueError("lease filename mismatch")
            if r["status"] in {"prepared", "destroyed"}:
                status = "absent" if r["status"] == "destroyed" else "prepared"
            else:
                status = watchdog(
                    r,
                    provider or Vast(),
                    now=time.time() if now is None else now,
                    execute=execute,
                    save=lambda r: store(path, r),
                )
            results.append({"label": r["label"], "instance": r["instance"], "status": status})
            directory = root / r["label"]
            if (
                execute
                and r["status"] in {"cleanup", "absent", "destroyed"}
                and (directory / "namespace-attempted").exists()
            ):
                namespace_work.append((r, directory, results[-1]))
        unresolved = sum(r["status"] not in {"prepared", "destroyed"} for _, r in records)
    # Complete every billing pass before slow evidence export. Never force-delete on export failure.
    for record, directory, result in namespace_work:
        from real_controller import Kube, finish_namespace

        if directory.is_symlink() or directory.stat().st_mode & 0o077:
            result["namespace_absent"] = False
            continue
        cleanup = directory / "namespace-cleanup.json"
        if (
            cleanup.exists()
            and not cleanup.is_symlink()
            and json.loads(cleanup.read_text()).get("absent") is True
        ):
            result["namespace_absent"] = True
            continue
        result["namespace_absent"] = finish_namespace(kube or Kube(), record, None, directory)
    # The admission/diagnostic guard must never suppress existing cleanup obligations.
    if unresolved > 4:
        raise ValueError("too many leases; manual reconciliation required")
    return {"leases": len(paths), "results": results, "execution": execute}


def launch_command(record, secrets):
    """Secret-bearing argv is used only in captured trusted subprocess, never printed."""
    import base64
    import shlex

    validate(record)
    pins = json.loads(Path(__file__).with_name("pins.json").read_text())
    from verify_pins import validate_pins

    validate_pins(pins)
    payload = base64.b64encode(json.dumps(secrets).encode()).decode()
    setup = (
        "import base64,json,os; os.umask(0o077); "
        f"s=json.loads(base64.b64decode('{payload}')); "
        "open('/tmp/kolibri.crt','w').write(s['cert']); "
        "open('/tmp/kolibri.key','w').write(s['key']); "
        "open('/tmp/kolibri.token','w').write(s['api_key'])"
    )
    args = [
        "vllm",
        "serve",
        pins["model"],
        "--revision",
        pins["model_revision"],
        "--tokenizer-revision",
        pins["model_revision"],
        "--served-model-name",
        pins["model"],
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
        "--tensor-parallel-size",
        "1",
        "--max-model-len",
        "131072",
        "--max-num-seqs",
        "1",
        "--gpu-memory-utilization",
        "0.90",
        "--kv-cache-dtype",
        "fp8",
        "--reasoning-parser",
        "kolibri1",
        "--tool-call-parser",
        "kolibri1",
        "--enable-auto-tool-choice",
        "--generation-config",
        "vllm",
        "--ssl-certfile",
        "/tmp/kolibri.crt",
        "--ssl-keyfile",
        "/tmp/kolibri.key",
    ]
    script = (
        "set -eu; umask 077; python3 -c "
        + shlex.quote(setup)
        + '; export VLLM_API_KEY="$(< /tmp/kolibri.token)" VLLM_NO_USAGE_STATS=1; '
        + "exec "
        + shlex.join(args)
    )
    return [
        "launch",
        str(record["offer"]),
        "--image",
        pins["image_repository"] + "@" + pins["image_digest"],
        "--disk",
        "200",
        "--label",
        record["label"],
        "--entrypoint",
        "bash",
        "--cancel-unavail",
        "--env",
        "-p 8000:8000",
        "--args",
        "-lc",
        script,
    ]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--execute-watchdog", action="store_true")
    args = p.parse_args()
    try:
        print(json.dumps(pass_once(execute=args.execute_watchdog)))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        print(json.dumps({"status": "watchdog-failed", "action": "operator-review-required"}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

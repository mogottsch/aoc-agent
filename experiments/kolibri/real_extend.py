"""Explicit, prepaid-only one-time lease extension; never rents or touches Kubernetes.

The operator must verify the independent scheduler horizon covers the new deadline
BEFORE invoking this CLI. A fresh local watchdog receipt attests that verification;
this module cannot inspect or extend the scheduler. Patch/replace any old CPU Job
only AFTER this command reports a committed deadline.

Trust boundary: the private local state owner is the operator. Receipts are not
cryptographically signed and are never accepted from the generated-code pod.
"""

import argparse
import copy
import json
import math
import os
import stat
import subprocess
import tempfile
import time
from decimal import Decimal
from pathlib import Path

from real_lifecycle import STATE, Vast, identity, locked, read, reconcile, secure_dir, validate

MAX_ADDITIONAL_SECONDS = 7200
MAX_EXTENDED_TTL_SECONDS = 18000
ACTIVE = {"launching", "running", "debug-retained"}
AUDIT_FIELDS = {
    "version",
    "action",
    "original",
    "additional_seconds",
    "new_deadline",
    "approved_at",
    "credit",
    "rate",
    "quoted_remaining_cost",
    "watchdog",
}


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def future_cost(deadline, now, rate):
    return (Decimal(str(deadline)) - Decimal(str(now))) * Decimal(str(rate)) / Decimal(3600)


def validate_watchdog(receipt, now):
    if (
        type(receipt) is not dict
        or set(receipt) != {"job_id", "schedule_seconds", "verified_at"}
        or type(receipt["job_id"]) is not str
        or not receipt["job_id"].strip()
        or len(receipt["job_id"]) > 256
        or not number(receipt["schedule_seconds"])
        or not 0 < receipt["schedule_seconds"] <= 60
        or not number(receipt["verified_at"])
        or not 0 <= now - receipt["verified_at"] <= 300
    ):
        raise ValueError("fresh watchdog attestation required")


def validate_extension(record):
    audit = record["extension"]
    if type(audit) is not dict or set(audit) != AUDIT_FIELDS:
        raise ValueError("invalid extension schema")
    if (
        type(audit["version"]) is not int
        or audit["version"] != 1
        or audit["action"] != "extend-approved"
    ):
        raise ValueError("explicit extension approval required")
    original = audit["original"]
    if type(original) is not dict or "extension" in original:
        raise ValueError("only one extension permitted")
    validate(original)
    if (
        original["status"] not in ACTIVE
        or original["instance"] is None
        or original["start_date"] is None
    ):
        raise ValueError("extension requires owned active original lease")
    seconds = audit["additional_seconds"]
    if type(seconds) is not int or not 1 <= seconds <= MAX_ADDITIONAL_SECONDS:
        raise ValueError("extension maximum 7200 seconds")
    if (
        not number(audit["approved_at"])
        or not original["created"] <= audit["approved_at"] < original["deadline"]
        or not number(audit["new_deadline"])
        or audit["new_deadline"] != original["deadline"] + seconds
        or record["deadline"] != audit["new_deadline"]
        or record["deadline"] - record["created"] > MAX_EXTENDED_TTL_SECONDS
    ):
        raise ValueError("extension deadline binding or maximum 5 hour TTL")
    if any(record[k] != original[k] for k in original if k not in {"deadline", "status"}):
        raise ValueError("extension original binding or policy mismatch")
    validate_watchdog(audit["watchdog"], audit["approved_at"])
    if (
        not number(audit["rate"])
        or not 0 < audit["rate"] <= original["hourly_ceiling"]
        or not number(audit["credit"])
        or audit["credit"] < 0
        or not number(audit["quoted_remaining_cost"])
    ):
        raise ValueError("invalid extension credit or rate")
    cost = future_cost(audit["new_deadline"], audit["approved_at"], audit["rate"]) + Decimal(
        str(original["download_ceiling"])
    )
    if audit["quoted_remaining_cost"] != float(cost) or cost + Decimal(
        str(original["reserve"])
    ) > Decimal(str(audit["credit"])):
        raise ValueError("extension unaffordable or quote mismatch")


def private_json(path, *, immutable=False):
    secure_dir(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "r") as stream:
        st = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(st.st_mode)
            or st.st_uid != os.getuid()
            or st.st_mode & 0o077
            or st.st_size > 8192
            or (immutable and st.st_mode & 0o222)
        ):
            raise ValueError("unsafe private receipt")
        return json.loads(stream.read(8193))


def receipt_path(path, record):
    if path.name != record["label"] + ".json":
        raise ValueError("lease filename mismatch")
    return path.parent / record["label"] / "extension-receipt.json"


def verify_receipt(path, record):
    if private_json(receipt_path(path, record), immutable=True) != record["extension"]:
        raise ValueError("extension immutable receipt mismatch")


def fsync_dir(directory):
    fd = os.open(directory, os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def persist_receipt(path, audit):
    """Publish only complete read-only bytes; never replace an existing receipt."""
    secure_dir(path.parent)
    fd, name = tempfile.mkstemp(prefix=".extension-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(audit, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fchmod(stream.fileno(), 0o400)
            os.fsync(stream.fileno())
        os.link(temporary, path, follow_symlinks=False)
        fsync_dir(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def commit(path, original, updated):
    """Narrow explicit transaction; the generic store's freeze guards stay in force."""
    validate(updated)
    verify_receipt(path, updated)
    if read(path) != original:
        raise ValueError("original lease changed before extension commit")
    if updated["extension"]["original"] != original:
        raise ValueError("extension receipt does not match exact original lease")
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".new", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(updated, stream)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fsync_dir(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def extend_approved(
    path, *, additional_seconds, watchdog_receipt, root=STATE, provider=None, now=None
):
    path, root = Path(path), Path(root)
    if path.parent != root or path.is_symlink():
        raise ValueError("exact active lease path required")
    if type(additional_seconds) is not int or not 1 <= additional_seconds <= MAX_ADDITIONAL_SECONDS:
        raise ValueError("extension maximum 7200 seconds")
    with locked(root):
        original = read(path)
        target = receipt_path(path, original)
        if "extension" in original:
            raise ValueError("lease already extended; only one extension permitted")
        clock = time.time() if now is None else now
        if (
            not number(clock)
            or not original["created"] <= clock < original["deadline"]
            or original["status"] not in ACTIVE
            or original["instance"] is None
            or original["start_date"] is None
        ):
            raise ValueError("owned active unexpired lease required")
        new_deadline = original["deadline"] + additional_seconds
        if new_deadline - original["created"] > MAX_EXTENDED_TTL_SECONDS:
            raise ValueError("maximum 5 hour total TTL")
        watchdog = private_json(Path(watchdog_receipt))
        validate_watchdog(watchdog, clock)
        provider = Vast() if provider is None else provider
        credit = identity(provider)
        rows = provider.call("list")
        current = reconcile(copy.deepcopy(original), rows)
        if current is None or len(rows) != 1:
            raise ValueError("exact singleton owned inventory required; no extra GPU")
        rate = current.get("dph_total")
        if not number(rate) or not 0 < rate <= original["hourly_ceiling"]:
            raise ValueError("current rate outside original ceiling")
        fresh_clock = time.time() if now is None else now
        if not number(fresh_clock) or not clock <= fresh_clock < original["deadline"]:
            raise ValueError("original lease expired during fresh provider checks")
        validate_watchdog(watchdog, fresh_clock)
        cost = future_cost(new_deadline, clock, rate) + Decimal(str(original["download_ceiling"]))
        if cost + Decimal(str(original["reserve"])) > Decimal(str(credit)):
            raise ValueError("fresh prepaid credit cannot afford full remaining lifetime")
        audit = {
            "version": 1,
            "action": "extend-approved",
            "original": original,
            "additional_seconds": additional_seconds,
            "new_deadline": new_deadline,
            "approved_at": clock,
            "credit": credit,
            "rate": rate,
            "quoted_remaining_cost": float(cost),
            "watchdog": watchdog,
        }
        if target.exists() or target.is_symlink():
            # Receipt-before-store interruption: use the SAME authorization and deadline,
            # never refresh/replace its credit or approval timestamp.
            audit = private_json(target, immutable=True)
            if (
                type(audit) is not dict
                or set(audit) != AUDIT_FIELDS
                or audit.get("original") != original
                or audit.get("additional_seconds") != additional_seconds
                or audit.get("new_deadline") != new_deadline
                or audit.get("rate") != rate
            ):
                raise ValueError("interrupted extension receipt binding mismatch")
        else:
            secure_dir(target.parent)
            fsync_dir(root)
            persist_receipt(target, audit)
        updated = {**original, "deadline": new_deadline, "extension": audit}
        validate(updated)
        commit(path, original, updated)
        committed = read(path)
        if committed != updated:
            raise ValueError("extension commit readback mismatch")
        return {
            "status": "extension-committed",
            "label": original["label"],
            "instance": original["instance"],
            "old_deadline": original["deadline"],
            "new_deadline": committed["deadline"],
            "receipt": str(target),
            "kubernetes_action": "operator-only-after-commit",
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extend-approved", type=Path, required=True)
    parser.add_argument("--additional-seconds", type=int, required=True)
    parser.add_argument("--watchdog-receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = extend_approved(
            args.extend_approved,
            additional_seconds=args.additional_seconds,
            watchdog_receipt=args.watchdog_receipt,
        )
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "extension-refused", "error_type": type(error).__name__}))
        return 2
    print(json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

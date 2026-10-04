"""Private best-effort cgroup-v2/process memory sampling (standard library only)."""

from __future__ import annotations

import json
import math
import os
import stat
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

MAX_ERRORS = 16
MAX_READ_BYTES = 65536
MAX_PROCESSES = 128


MAX_RECORDS = 2161
MAX_SAMPLES = MAX_RECORDS - 3
MAX_BYTES = 16 * 1024 * 1024
MAX_DURATION = 3 * 60 * 60
METADATA_RESERVE = 4096
JOIN_TIMEOUT = 2.0


class _RecordLimitError(Exception):
    """No record capacity remains."""


class _ByteLimitError(Exception):
    """No space remains for this record."""


def _directory_fd(path: Path, *, create: bool = False) -> int:
    """Pin each component without following aliases, before changing permissions."""
    parts = path.absolute().parts
    if ".." in parts:
        raise OSError("parent traversal is not allowed")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open(parts[0], flags)
    try:
        for part in parts[1:]:
            try:
                child = os.open(part, flags, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                with suppress(FileExistsError):
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
    except Exception:
        os.close(fd)
        raise
    return fd


def _read(path: Path, *, dir_fd: int | None = None) -> str:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise OSError("telemetry input must be an unshared regular file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            text = stream.read(MAX_READ_BYTES + 1)
        if len(text) > MAX_READ_BYTES:
            raise ValueError("oversize telemetry field")
        return text.decode("utf-8", errors="replace")
    finally:
        os.close(fd)


def _sample(cgroup_root: Path, proc_root: Path) -> dict:  # noqa: C901, PLR0912, PLR0915
    errors = []
    errors_truncated = False
    processes_truncated = False

    def error(field: str, exc: Exception, *, source: str, phase: str) -> None:
        nonlocal errors_truncated
        if len(errors) < MAX_ERRORS:
            errors.append(
                {
                    "field": field[:80],
                    "error": type(exc).__name__[:80],
                    "source": source[:80],
                    "phase": phase[:80],
                    "status": "unavailable",
                    "errno": exc.errno if isinstance(exc, OSError) else None,
                }
            )
        else:
            errors_truncated = True

    cgroup = {}
    cgroup_fd = None
    try:
        cgroup_fd = _directory_fd(cgroup_root)
    except OSError as exc:
        error("cgroup", exc, source="cgroup", phase="directory_open")
    for name in ("memory.current", "memory.peak", "pids.current", "memory.events", "memory.stat"):
        phase = "read"
        try:
            if cgroup_fd is None:
                cgroup[name] = None
                continue
            phase = "read"
            text = _read(Path(name), dir_fd=cgroup_fd)
            phase = "parse"
            if name not in {"memory.events", "memory.stat"}:
                cgroup[name] = int(text)
                continue
            values = {}
            for line in text.splitlines():
                key, value = line.split()
                if name == "memory.stat" and key not in {"anon", "file", "shmem"}:
                    continue
                values[key[:80]] = int(value)
            cgroup[name] = values
        except (OSError, ValueError) as exc:
            cgroup[name] = None
            error(name, exc, source="cgroup", phase=phase)
    if cgroup_fd is not None:
        os.close(cgroup_fd)
    processes = []
    proc_fd = None
    try:
        proc_fd = _directory_fd(proc_root)
        with os.scandir(proc_fd) as entries:
            for attempt, entry in enumerate(entries, 1):
                if attempt == MAX_PROCESSES:
                    processes_truncated = True
                if not entry.name.isdecimal():
                    if processes_truncated:
                        break
                    continue
                pid_fd = None
                process_field = "directory"
                try:
                    pid_fd = os.open(
                        entry.name,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=proc_fd,
                    )
                    process_field = "stat"
                    fields = _read(Path("stat"), dir_fd=pid_fd).rsplit(")", 1)[1].split()
                    process_field = "comm"
                    processes.append(
                        {
                            "pid": int(entry.name),
                            "ppid": int(fields[1]),
                            "rss_bytes": int(fields[21]) * os.sysconf("SC_PAGE_SIZE"),
                            "name": _read(Path("comm"), dir_fd=pid_fd).rstrip("\n")[:256],
                        }
                    )
                except (OSError, ValueError, IndexError) as exc:
                    error(process_field, exc, source="proc", phase="read")
                finally:
                    if pid_fd is not None:
                        os.close(pid_fd)
                if processes_truncated:
                    break
    except OSError as exc:
        error("proc", exc, source="proc", phase="directory_scan")
    finally:
        if proc_fd is not None:
            os.close(proc_fd)
    return {
        "type": "sample",
        "timestamp": time.time(),
        "cgroup": cgroup,
        "processes": processes,
        "errors": errors,
        "processes_truncated": processes_truncated,
        "errors_truncated": errors_truncated,
    }


def _private_fd(path: Path, *, append: bool, dir_fd: int | None = None) -> int:
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open(path, flags | (os.O_APPEND if append else 0), 0o600, dir_fd=dir_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise OSError("telemetry output must be an unshared regular file")  # noqa: TRY301
        os.fchmod(fd, 0o600)
    except Exception:
        os.close(fd)
        raise
    return fd


def _metadata(
    directory: int,
    exc: Exception,
    record: dict | None = None,
    *,
    phase: str = "output.write",
) -> None:
    """Last-resort private error receipt; never include exception messages."""
    receipt: dict[str, object] = {
        "type": "error",
        "error": type(exc).__name__[:80],
        "end": bool(record and record["type"] == "end"),
        "phase": phase[:80],
        "source": "output",
        "status": "unavailable",
        "errno": exc.errno if isinstance(exc, OSError) else None,
    }
    if isinstance(exc, _ByteLimitError):
        receipt.update({"type": "limit", "reason": "bytes"})
    if isinstance(exc, _RecordLimitError):
        receipt.update({"type": "limit", "reason": "records"})
    try:
        fd = _private_fd(Path("memory-metrics.metadata.json"), append=False, dir_fd=directory)
        try:
            os.ftruncate(fd, 0)
            os.write(fd, json.dumps(receipt).encode())
            os.fsync(fd)
        finally:
            os.close(fd)
    except Exception:  # noqa: BLE001, S110
        pass  # An unwritable directory cannot persist a receipt.


@contextmanager
def memory_sampler(  # noqa: C901, PLR0915
    directory: Path,
    *,
    interval: float = 5,
    cgroup_root: Path = Path("/sys/fs/cgroup"),
    proc_root: Path = Path("/proc"),
) -> Iterator[threading.Thread | None]:
    """Append private metrics without changing benchmark success/failure.

    Yield a daemon Thread (or None if setup failed), signaled on exit and joined
    for at most two seconds. Setup waits are also bounded. The worker owns all
    descriptors and best-effort metadata I/O; stalled I/O cannot block benchmark
    exit or prevent process exit, but its final receipt may not be persisted.
    Sample immediately and then every ``interval`` seconds for at most three
    hours/2158 samples. The append-only JSONL is capped at 2161 total records
    (including existing rows, start, limit/error and end) and 16 MiB, reserving
    two record slots and byte capacity for final metadata. A private bounded
    metadata sidecar records output failures and full-file limit/exit receipts.

    Only cgroup counters and process stat/comm are read: never arguments,
    environment, or credentials. Owned output directories are tightened to 0700;
    foreign-owned writable mount roots are left unchanged, with all leaf outputs
    still pinned, unshared regular 0600 files. Process scan attempts (including malformed and
    nonnumeric entries) and rows are capped at 128 and errors at
    16, with explicit truncation flags. Unwritable output fails closed/silent;
    no persistence is possible when both output files are unwritable.
    """
    directory = Path(directory)
    fd = None
    directory_fd = None
    thread = None
    stop = threading.Event()
    record_count = 0

    def write(record: dict) -> None:
        nonlocal record_count
        if fd is None:
            raise OSError("telemetry output unavailable")
        reserve = 2 if record["type"] in {"sample", "start"} else 0
        if record_count >= MAX_RECORDS - reserve:
            raise _RecordLimitError
        data = (json.dumps(record, separators=(",", ":")) + "\n").encode()
        ceiling = MAX_BYTES - METADATA_RESERVE if record["type"] == "sample" else MAX_BYTES
        if os.fstat(fd).st_size + len(data) > ceiling:
            raise _ByteLimitError
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short telemetry write")
            view = view[written:]
        record_count += 1
        os.fsync(fd)

    def safe_write(record: dict) -> None:
        try:
            write(record)
        except Exception as exc:  # noqa: BLE001
            if directory_fd is not None:
                _metadata(directory_fd, exc, record)

    ready = threading.Event()
    setup_failed = False

    def run() -> None:  # noqa: C901, PLR0912, PLR0915
        nonlocal fd, directory_fd, setup_failed, record_count
        started = time.monotonic()
        count = 0
        initialized = False
        phase = "output.directory_open"
        try:
            directory_fd = _directory_fd(directory, create=True)
            # A Kubernetes emptyDir mount root belongs to root; fsGroup grants
            # write access, not chmod ownership. Only tighten owned directories.
            # Leaf files still require pinned, unshared regular 0600 descriptors.
            if os.fstat(directory_fd).st_uid == os.geteuid():
                phase = "output.directory_permissions"
                os.fchmod(directory_fd, 0o700)
            phase = "configuration.interval"
            if not math.isfinite(interval) or interval <= 0:
                raise ValueError("interval must be finite and positive")  # noqa: TRY301
            phase = "output.file_open"
            fd = _private_fd(Path("memory-metrics.jsonl"), append=True, dir_fd=directory_fd)
            phase = "output.existing_records"
            size = os.fstat(fd).st_size
            if size >= MAX_BYTES:
                raise _ByteLimitError  # noqa: TRY301
            offset = 0
            last = b""
            while offset < size:
                chunk = os.pread(fd, min(MAX_READ_BYTES, size - offset), offset)
                if not chunk:
                    break
                record_count += chunk.count(b"\n")
                offset += len(chunk)
                last = chunk[-1:]
            record_count += bool(last and last != b"\n")
            phase = "output.start"
            write(
                {
                    "type": "start",
                    "interval": interval,
                    "max_samples": MAX_SAMPLES,
                    "max_records": MAX_RECORDS,
                    "max_bytes": MAX_BYTES,
                    "max_duration": MAX_DURATION,
                }
            )
            initialized = True
            ready.set()
            while not stop.is_set():
                if record_count >= MAX_RECORDS - 2:
                    safe_write({"type": "limit", "reason": "records", "samples": count})
                    break
                if count >= MAX_SAMPLES:
                    safe_write({"type": "limit", "reason": "samples", "samples": count})
                    break
                if time.monotonic() - started >= MAX_DURATION:
                    safe_write({"type": "limit", "reason": "duration", "samples": count})
                    break
                try:
                    write(_sample(cgroup_root, proc_root))
                except (_ByteLimitError, _RecordLimitError) as exc:
                    reason = "bytes" if isinstance(exc, _ByteLimitError) else "records"
                    safe_write({"type": "limit", "reason": reason, "samples": count})
                    break
                count += 1
                remaining = MAX_DURATION - (time.monotonic() - started)
                if stop.wait(max(0, min(interval, remaining))):
                    break
        except Exception as exc:  # noqa: BLE001
            if initialized:
                safe_write({"type": "error", "error": type(exc).__name__[:80]})
            else:
                setup_failed = True
                if directory_fd is not None:
                    _metadata(directory_fd, exc, phase=phase)
        finally:
            # This daemon exclusively owns both descriptors, even after a timed-out join.
            if fd is not None:
                safe_write({"type": "end"})
                with suppress(OSError):
                    os.close(fd)
            if directory_fd is not None:
                with suppress(OSError):
                    os.close(directory_fd)
            ready.set()

    try:
        thread = threading.Thread(target=run, name="memory-sampler", daemon=True)
        thread.start()
    except Exception:  # noqa: BLE001
        thread = None
    if thread is not None:
        ready.wait(JOIN_TIMEOUT)
    try:
        yield None if setup_failed else thread
    finally:
        stop.set()
        if thread is not None:
            with suppress(RuntimeError):
                thread.join(timeout=JOIN_TIMEOUT)

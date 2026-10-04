"""Fixture-only coverage for private, bounded memory telemetry."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from functools import partial
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Never, Self

import pytest

ROOT = Path(__file__).resolve().parents[1]


def telemetry() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "memory_telemetry", ROOT / "experiments/kolibri/memory_telemetry.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def roots(tmp_path: Path) -> tuple[Path, Path]:
    cgroup = tmp_path / "cgroup"
    proc = tmp_path / "proc"
    cgroup.mkdir()
    proc.mkdir()
    for name, value in {
        "memory.current": "1234\n",
        "memory.peak": "4567\n",
        "memory.events": "low 0\nhigh 2\noom 3\noom_kill 1\n",
        "memory.stat": "anon 100\nfile 200\nshmem 30\nother 999\n",
        "pids.current": "1\n",
    }.items():
        (cgroup / name).write_text(value)
    pid = proc / "123"
    pid.mkdir()
    # stat fields after comm: state, ppid, ... rss (field 24).
    fields = ["S", "42"] + ["0"] * 19 + ["7"]
    (pid / "stat").write_text("123 (name with ) paren) " + " ".join(fields))
    (pid / "comm").write_text("worker\n")
    return cgroup, proc


def records(directory: Path) -> list[dict]:
    return [
        json.loads(line) for line in (directory / "memory-metrics.jsonl").read_text().splitlines()
    ]


def await_samples(directory: Path, count: int = 1) -> None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if len([row for row in records(directory) if row["type"] == "sample"]) >= count:
            return
        time.sleep(0.005)
    pytest.fail("sampler did not produce fixture samples")


def test_samples_fixture_data_and_joins_on_complete_exit(
    tmp_path: Path, roots: tuple[Path, Path]
) -> None:
    module = telemetry()
    directory = tmp_path / "output"
    with module.memory_sampler(
        directory, interval=0.01, cgroup_root=roots[0], proc_root=roots[1]
    ) as thread:
        await_samples(directory, 2)
        assert thread.is_alive()
    assert not thread.is_alive()
    rows = records(directory)
    assert rows[0]["type"] == "start"
    assert rows[-1]["type"] == "end"
    sample = next(row for row in rows if row["type"] == "sample")
    assert sample["cgroup"]["memory.current"] == 1234
    assert sample["cgroup"]["memory.peak"] == 4567
    assert sample["cgroup"]["memory.events"]["oom_kill"] == 1
    assert sample["cgroup"]["memory.stat"] == {"anon": 100, "file": 200, "shmem": 30}
    assert sample["cgroup"]["pids.current"] == 1
    assert sample["processes"] == [
        {"pid": 123, "ppid": 42, "rss_bytes": 7 * os.sysconf("SC_PAGE_SIZE"), "name": "worker"}
    ]
    assert (directory / "memory-metrics.jsonl").stat().st_mode & 0o777 == 0o600
    assert directory.stat().st_mode & 0o777 == 0o700


def test_failed_benchmark_stops_thread_and_missing_fields_are_bounded(
    tmp_path: Path, roots: tuple[Path, Path]
) -> None:
    module = telemetry()
    (roots[0] / "memory.peak").unlink()
    (roots[1] / "123/stat").write_text("broken")
    directory = tmp_path / "output"
    with (  # noqa: PT012
        pytest.raises(RuntimeError, match="benchmark failure"),
        module.memory_sampler(
            directory, interval=60, cgroup_root=roots[0], proc_root=roots[1]
        ) as thread,
    ):
        await_samples(directory)
        raise RuntimeError("benchmark failure")
    assert not thread.is_alive()
    rows = records(directory)
    sample = next(row for row in rows if row["type"] == "sample")
    assert sample["cgroup"]["memory.peak"] is None
    assert sample["cgroup"]["memory.current"] == 1234
    assert sample["processes"] == []
    assert sample["errors"]
    assert len(json.dumps(sample["errors"])) < 4096
    assert rows[-1]["type"] == "end"


def test_sample_failure_is_private_and_does_not_replace_benchmark_error(
    tmp_path: Path,
    roots: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = telemetry()

    def fail(*_args: object) -> Never:
        raise RuntimeError("DO_NOT_PERSIST_ARGUMENT_OR_SECRET")

    monkeypatch.setattr(module, "_sample", fail)
    directory = tmp_path / "output"
    with (  # noqa: PT012
        pytest.raises(ValueError, match="benchmark"),
        module.memory_sampler(
            directory, interval=0.01, cgroup_root=roots[0], proc_root=roots[1]
        ) as thread,
    ):
        thread.join(timeout=1)
        raise ValueError("benchmark")
    assert not thread.is_alive()
    rows = records(directory)
    assert any(row["type"] == "error" and row["error"] == "RuntimeError" for row in rows)
    assert rows[-1]["type"] == "end"
    assert "DO_NOT_PERSIST" not in (directory / "memory-metrics.jsonl").read_text()
    assert capsys.readouterr() == ("", "")


def test_output_failure_gets_private_metadata_and_benchmark_continues(
    tmp_path: Path, roots: tuple[Path, Path]
) -> None:
    module = telemetry()
    directory = tmp_path / "output"
    directory.mkdir()
    (directory / "memory-metrics.jsonl").mkdir()
    with module.memory_sampler(directory, cgroup_root=roots[0], proc_root=roots[1]) as thread:
        assert thread is None
    metadata = directory / "memory-metrics.metadata.json"
    assert json.loads(metadata.read_text())["error"] == "IsADirectoryError"
    assert metadata.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("bound", ["samples", "bytes", "duration"])
def test_limits_are_marked_and_end_metadata_is_not_dropped(
    tmp_path: Path, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, bound: str
) -> None:
    module = telemetry()
    if bound == "samples":
        monkeypatch.setattr(module, "MAX_SAMPLES", 2, raising=False)
    elif bound == "bytes":
        monkeypatch.setattr(module, "MAX_BYTES", 1800, raising=False)
        monkeypatch.setattr(module, "METADATA_RESERVE", 512, raising=False)
    else:
        monkeypatch.setattr(module, "MAX_DURATION", 0.02, raising=False)
    directory = tmp_path / "output"
    with module.memory_sampler(
        directory, interval=0.01, cgroup_root=roots[0], proc_root=roots[1]
    ) as thread:
        thread.join(timeout=2)
        assert not thread.is_alive()
    rows = records(directory)
    assert any(row["type"] == "limit" and row["reason"] == bound for row in rows)
    assert rows[-1]["type"] == "end"
    if bound == "samples":
        assert len([row for row in rows if row["type"] == "sample"]) == 2
    if bound == "bytes":
        assert (directory / "memory-metrics.jsonl").stat().st_size <= 1800
    assert rows[0]["max_samples"] <= 2161
    assert rows[0]["max_bytes"] <= 16 * 1024 * 1024


def test_process_and_error_collections_are_bounded_with_explicit_truncation(
    roots: tuple[Path, Path],
) -> None:
    module = telemetry()
    template = (roots[1] / "123/stat").read_text()
    for pid in range(200, 400):
        directory = roots[1] / str(pid)
        directory.mkdir()
        (directory / "stat").write_text(template)
        (directory / "comm").write_text("x" * 500)
    sample = module._sample(*roots)  # noqa: SLF001
    assert len(sample["processes"]) <= 128
    assert sample["processes_truncated"] is True
    assert all(len(row["name"]) <= 256 for row in sample["processes"])
    for directory in roots[1].iterdir():
        (directory / "stat").write_text("broken")
    sample = module._sample(*roots)  # noqa: SLF001
    assert len(sample["errors"]) <= 16
    assert sample["errors_truncated"] is True


@pytest.mark.parametrize("numeric", [True, False])
def test_process_scan_caps_attempts_even_when_entries_are_malformed(
    roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, numeric: bool
) -> None:
    module = telemetry()
    (roots[1] / "123/stat").unlink()
    (roots[1] / "123/comm").unlink()
    (roots[1] / "123").rmdir()
    for number in range(300):
        (roots[1] / (str(number) if numeric else f"junk-{number}")).mkdir()
    original_scandir = os.scandir
    attempted = []

    class Entries:
        def __enter__(self) -> Self:
            self.stream = original_scandir(roots[1])
            return self

        def __exit__(self, *_args: object) -> None:
            self.stream.close()

        def __iter__(self) -> Iterator[os.DirEntry]:
            for entry in self.stream:
                attempted.append(entry.name)
                yield entry

    monkeypatch.setattr(module.os, "scandir", lambda _path: Entries())
    sample = module._sample(*roots)  # noqa: SLF001
    assert len(attempted) == 128
    assert sample["processes_truncated"] is True
    assert sample["processes"] == []


def test_private_append_refuses_symlink_and_does_not_modify_target(
    tmp_path: Path, roots: tuple[Path, Path]
) -> None:
    module = telemetry()
    target = tmp_path / "target"
    target.write_text("untouched")
    directory = tmp_path / "output"
    directory.mkdir()
    (directory / "memory-metrics.jsonl").symlink_to(target)
    with module.memory_sampler(directory, cgroup_root=roots[0], proc_root=roots[1]) as thread:
        assert thread is None
    assert target.read_text() == "untouched"
    assert (directory / "memory-metrics.metadata.json").stat().st_mode & 0o777 == 0o600


def test_existing_file_is_private_append_and_fsync_is_used(
    tmp_path: Path, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    module = telemetry()
    directory = tmp_path / "output"
    directory.mkdir(mode=0o755)
    metrics = directory / "memory-metrics.jsonl"
    metrics.write_text('{"type":"existing"}\n')
    metrics.chmod(0o644)
    synced = []
    original_fsync = os.fsync

    def fsync(fd: int) -> None:
        synced.append(fd)
        original_fsync(fd)

    monkeypatch.setattr(module.os, "fsync", fsync)
    with module.memory_sampler(directory, cgroup_root=roots[0], proc_root=roots[1]):
        await_samples(directory)
    assert records(directory)[0] == {"type": "existing"}
    assert metrics.stat().st_mode & 0o777 == 0o600
    assert directory.stat().st_mode & 0o777 == 0o700
    assert len(synced) >= 3


def test_full_file_preserves_limit_and_exit_receipt_in_bounded_sidecar(
    tmp_path: Path, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    module = telemetry()
    monkeypatch.setattr(module, "MAX_BYTES", 256, raising=False)
    directory = tmp_path / "output"
    directory.mkdir()
    metrics = directory / "memory-metrics.jsonl"
    metrics.write_bytes(b" " * 256)
    with module.memory_sampler(directory, cgroup_root=roots[0], proc_root=roots[1]) as thread:
        assert thread is None
    metadata = directory / "memory-metrics.metadata.json"
    receipt = json.loads(metadata.read_text())
    assert receipt["type"] == "limit"
    assert receipt["reason"] == "bytes"
    assert receipt["end"] is True
    assert metadata.stat().st_size < 4096
    assert metrics.stat().st_size == 256


@pytest.mark.parametrize("interval", [0, -1, float("inf"), float("nan")])
def test_invalid_interval_is_a_bounded_error_not_a_benchmark_failure(
    tmp_path: Path, roots: tuple[Path, Path], interval: float
) -> None:
    module = telemetry()
    directory = tmp_path / "output"
    with module.memory_sampler(
        directory, interval=interval, cgroup_root=roots[0], proc_root=roots[1]
    ) as thread:
        assert thread is None
    assert (
        json.loads((directory / "memory-metrics.metadata.json").read_text())["error"]
        == "ValueError"
    )


def test_process_reads_refuse_links_to_argument_files(
    roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    module = telemetry()
    pid = roots[1] / "123"
    (pid / "cmdline").write_text("SECRET_ARGUMENT")
    (pid / "environ").write_text("SECRET_ENVIRONMENT")
    (pid / "stat").unlink()
    (pid / "stat").symlink_to(pid / "cmdline")
    opened = []
    original_open = os.open

    def checked_open(
        path: str | Path, flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        path = Path(path)
        assert path.name not in {"cmdline", "environ"}
        if not flags & os.O_DIRECTORY:
            opened.append(path.name)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", checked_open)
    sample = module._sample(*roots)  # noqa: SLF001
    assert sample["processes"] == []
    assert any(error["error"] == "OSError" for error in sample["errors"])
    assert "SECRET" not in json.dumps(sample)
    assert set(opened) <= {
        "memory.current",
        "memory.peak",
        "memory.events",
        "memory.stat",
        "pids.current",
        "stat",
        "comm",
    }


@pytest.mark.parametrize("name", ["memory-metrics.jsonl", "memory-metrics.metadata.json"])
def test_output_hardlinks_never_modify_the_linked_target(
    tmp_path: Path, roots: tuple[Path, Path], name: str
) -> None:
    module = telemetry()
    directory = tmp_path / "output"
    directory.mkdir()
    target = tmp_path / "target"
    target.write_text("untouched")
    os.link(target, directory / name)
    if name.endswith("metadata.json"):
        (directory / "memory-metrics.jsonl").mkdir()
    with module.memory_sampler(directory, cgroup_root=roots[0], proc_root=roots[1]):
        pass
    assert target.read_text() == "untouched"


@pytest.mark.parametrize("ancestor", [False, True])
def test_output_directory_alias_is_rejected_without_mutating_target(
    tmp_path: Path, roots: tuple[Path, Path], ancestor: bool
) -> None:
    module = telemetry()
    target = tmp_path / "target-directory"
    target.mkdir(mode=0o755)
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    directory = alias / "child" if ancestor else alias
    before = target.stat().st_mode
    with module.memory_sampler(directory, cgroup_root=roots[0], proc_root=roots[1]) as thread:
        assert thread is None
    assert target.stat().st_mode == before
    assert list(target.iterdir()) == []


@pytest.mark.parametrize("alias", ["pid", "comm", "proc_ancestor", "cgroup_ancestor"])
def test_fixture_aliases_never_persist_secret_tokens(
    tmp_path: Path, roots: tuple[Path, Path], alias: str
) -> None:
    module = telemetry()
    cgroup, proc = roots
    if alias == "pid":
        pid = proc / "123"
        destination = tmp_path / "private-pid"
        pid.rename(destination)
        (destination / "comm").write_text("NEVER_PERSIST_TOKEN")
        pid.symlink_to(destination, target_is_directory=True)
    elif alias == "comm":
        secret = tmp_path / "private-arguments"
        secret.write_text("NEVER_PERSIST_TOKEN")
        (proc / "123/comm").unlink()
        (proc / "123/comm").symlink_to(secret)
    else:
        real = tmp_path / "real"
        real.mkdir()
        root = cgroup if alias == "cgroup_ancestor" else proc
        destination = real / root.name
        root.rename(destination)
        parent_alias = tmp_path / "parent-alias"
        parent_alias.symlink_to(real, target_is_directory=True)
        if alias == "cgroup_ancestor":
            (destination / "memory.events").write_text("NEVER_PERSIST_TOKEN 1\n")
            cgroup = parent_alias / destination.name
        else:
            (destination / "123/comm").write_text("NEVER_PERSIST_TOKEN")
            proc = parent_alias / destination.name
    directory = tmp_path / "output"
    with module.memory_sampler(directory, interval=0.01, cgroup_root=cgroup, proc_root=proc):
        await_samples(directory)
    assert "NEVER_PERSIST_TOKEN" not in (directory / "memory-metrics.jsonl").read_text()


@pytest.mark.parametrize("leaf", ["comm", "memory.events"])
def test_hardlinked_fixture_leaves_never_persist_tokens(
    tmp_path: Path, roots: tuple[Path, Path], leaf: str
) -> None:
    module = telemetry()
    target = tmp_path / "private-data"
    target.write_text("NEVER_PERSIST_TOKEN 1\n")
    path = roots[1] / "123/comm" if leaf == "comm" else roots[0] / leaf
    path.unlink()
    os.link(target, path)
    sample = module._sample(*roots)  # noqa: SLF001
    assert "NEVER_PERSIST_TOKEN" not in json.dumps(sample)


def test_output_fd_is_pinned_when_directory_is_renamed(
    tmp_path: Path, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    module = telemetry()
    directory = tmp_path / "output"
    relocated = tmp_path / "relocated"
    target = tmp_path / "untouched"
    target.mkdir(mode=0o755)
    original_open = os.open
    swapped = False

    def swapping_open(
        path: str | Path, flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        nonlocal swapped
        if Path(path).name == "memory-metrics.jsonl" and not swapped:
            swapped = True
            directory.rename(relocated)
            directory.symlink_to(target, target_is_directory=True)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swapping_open)
    with module.memory_sampler(directory, cgroup_root=roots[0], proc_root=roots[1]) as thread:
        thread.join(timeout=0.05)
    assert list(target.iterdir()) == []
    assert records(relocated)[-1]["type"] == "end"
    assert target.stat().st_mode & 0o777 == 0o755


def test_oversize_error_type_is_bounded(
    tmp_path: Path, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    module = telemetry()
    exception = type("X" * 10000, (Exception,), {})

    def fail(*_args: object) -> Never:
        raise exception

    monkeypatch.setattr(module, "_sample", fail)
    directory = tmp_path / "output"
    with module.memory_sampler(directory, cgroup_root=roots[0], proc_root=roots[1]) as thread:
        thread.join(timeout=1)
    error = next(row for row in records(directory) if row["type"] == "error")
    assert len(error["error"]) <= 80


@pytest.mark.parametrize("stalled", ["sample", "sample_fsync", "end_fsync", "metadata_fsync"])
def test_stalled_worker_io_does_not_block_exit_or_close_worker_fd(
    tmp_path: Path, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, stalled: str
) -> None:
    module = telemetry()
    monkeypatch.setattr(module, "JOIN_TIMEOUT", 0.03, raising=False)
    entered = threading.Event()
    release = threading.Event()
    original_sample = module._sample  # noqa: SLF001
    original_fsync = os.fsync
    held_fd = []
    directory = tmp_path / "output"

    def sample(*args: Path) -> dict:
        if stalled == "sample":
            entered.set()
            release.wait(0.5)
        return original_sample(*args)

    def fsync(fd: int) -> None:
        data = Path(f"/proc/self/fd/{fd}").read_bytes()
        if stalled == "metadata_fsync" and b'"type":"sample"' in data:
            raise OSError("NEVER_PERSIST_TOKEN")
        block = (
            (stalled == "sample_fsync" and b'"type":"sample"' in data)
            or (stalled == "end_fsync" and b'"type":"end"' in data)
            or (stalled == "metadata_fsync" and b'"type": "error"' in data)
        )
        if block:
            held_fd.append(fd)
            entered.set()
            release.wait(0.5)
        original_fsync(fd)

    monkeypatch.setattr(module, "_sample", sample)
    monkeypatch.setattr(module.os, "fsync", fsync)
    thread = None
    try:
        with module.memory_sampler(
            directory, interval=60, cgroup_root=roots[0], proc_root=roots[1]
        ) as thread:
            assert thread.daemon
            if stalled == "end_fsync":
                await_samples(directory)
            else:
                assert entered.wait(1)
            start = time.monotonic()
        assert time.monotonic() - start < 0.2
        assert thread.is_alive()
        for fd in held_fd:
            os.fstat(fd)  # The caller must not close an in-use worker descriptor.
    finally:
        release.set()
        if thread is not None:
            thread.join(timeout=1)
    assert thread is not None
    assert not thread.is_alive()
    assert "NEVER_PERSIST_TOKEN" not in (directory / "memory-metrics.jsonl").read_text()


@pytest.mark.parametrize("existing", [0, 2])
def test_record_limit_includes_start_limit_end_and_existing_rows(
    tmp_path: Path, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, existing: int
) -> None:
    module = telemetry()
    monkeypatch.setattr(module, "MAX_RECORDS", 6, raising=False)
    directory = tmp_path / "output"
    directory.mkdir()
    (directory / "memory-metrics.jsonl").write_text('{"type":"existing"}\n' * existing)
    with module.memory_sampler(
        directory, interval=0.001, cgroup_root=roots[0], proc_root=roots[1]
    ) as thread:
        thread.join(timeout=0.3)
    rows = records(directory)
    assert len(rows) == 6
    assert rows[-2]["type"] == "limit"
    assert rows[-2]["reason"] == "records"
    assert rows[-1]["type"] == "end"
    assert rows[existing]["max_records"] == 6
    assert module.MAX_SAMPLES == 2158


def test_default_record_cap_is_exactly_2161_including_metadata(
    tmp_path: Path, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    module = telemetry()
    monkeypatch.setattr(module, "_sample", lambda *_args: {"type": "sample"})
    directory = tmp_path / "output"
    with module.memory_sampler(
        directory, interval=0.000001, cgroup_root=roots[0], proc_root=roots[1]
    ) as thread:
        thread.join(timeout=5)
        assert not thread.is_alive()
    rows = records(directory)
    assert len(rows) == 2161
    assert sum(row["type"] == "sample" for row in rows) == 2158
    assert [rows[0]["type"], rows[-2]["type"], rows[-1]["type"]] == ["start", "limit", "end"]


def test_daemon_with_permanently_stuck_sample_cannot_prevent_process_exit(
    tmp_path: Path, roots: tuple[Path, Path]
) -> None:
    script = """
import importlib.util, pathlib, sys, threading
spec = importlib.util.spec_from_file_location('fixture_telemetry', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.JOIN_TIMEOUT = 0.03
entered = threading.Event()
never = threading.Event()
def stuck(*args):
    entered.set()
    never.wait()
module._sample = stuck
with module.memory_sampler(
    pathlib.Path(sys.argv[2]), cgroup_root=pathlib.Path(sys.argv[3]),
    proc_root=pathlib.Path(sys.argv[4]),
) as worker:
    assert worker.daemon
    assert entered.wait(1)
print('bounded-exit')
"""
    result = subprocess.run(  # noqa: S603 - trusted local fixture script and interpreter
        [
            sys.executable,
            "-c",
            script,
            str(ROOT / "experiments/kolibri/memory_telemetry.py"),
            str(tmp_path / "output"),
            str(roots[0]),
            str(roots[1]),
        ],
        capture_output=True,
        text=True,
        timeout=2,
        check=True,
    )
    assert result.stdout == "bounded-exit\n"
    assert result.stderr == ""


@pytest.mark.parametrize("exit_code", [0, 7])
def test_safe_logged_subprocess_integration_uses_only_fixture_metrics(
    tmp_path: Path, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, exit_code: int
) -> None:
    module = telemetry()
    monkeypatch.syspath_prepend(str(ROOT / "experiments/kolibri"))
    monkeypatch.setitem(
        sys.modules,
        "memory_telemetry",
        SimpleNamespace(
            memory_sampler=partial(
                module.memory_sampler, interval=0.01, cgroup_root=roots[0], proc_root=roots[1]
            )
        ),
    )
    spec = importlib.util.spec_from_file_location(
        "fixture_real_runner", ROOT / "experiments/kolibri/real_runner.py"
    )
    assert spec is not None
    assert spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    code = runner.run_logged(
        [
            sys.executable,
            "-c",
            f"import sys,time; print('OFFLINE_FIXTURE'); time.sleep(0.05); sys.exit({exit_code})",
        ],
        str(tmp_path),
        {"PATH": "/usr/bin:/bin"},
        tmp_path,
    )
    assert code == exit_code
    assert (tmp_path / "runner-stdout.log").read_text() == "OFFLINE_FIXTURE\n"
    rows = records(tmp_path)
    assert rows[0]["interval"] == 0.01
    assert rows[-1]["type"] == "end"
    samples = [row for row in rows if row["type"] == "sample"]
    assert samples
    assert all(row["cgroup"]["memory.current"] == 1234 for row in samples)
    assert all(row["processes"][0]["pid"] == 123 for row in samples)


def test_foreign_owned_writable_output_directory_keeps_private_metrics(
    tmp_path: Path, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    module = telemetry()
    directory = tmp_path / "volume-root"
    directory.mkdir(mode=0o770)
    original_fchmod = os.fchmod

    def foreign_directory_chmod(fd: int, mode: int) -> None:
        if os.fstat(fd).st_ino == directory.stat().st_ino:
            raise PermissionError(1, "DO_NOT_PERSIST_VOLUME_PATH")
        original_fchmod(fd, mode)

    # Kubernetes emptyDir root is owned by root, writable through fsGroup.
    monkeypatch.setattr(module.os, "geteuid", lambda: -1)
    monkeypatch.setattr(module.os, "fchmod", foreign_directory_chmod)
    with module.memory_sampler(directory, cgroup_root=roots[0], proc_root=roots[1]) as thread:
        assert thread is not None
        await_samples(directory)
    rows = records(directory)
    assert rows[-1]["type"] == "end"
    assert next(row for row in rows if row["type"] == "sample")["cgroup"]["memory.current"] == 1234
    assert (directory / "memory-metrics.jsonl").stat().st_mode & 0o777 == 0o600


def test_owned_directory_chmod_failure_reports_bounded_setup_phase(
    tmp_path: Path, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    module = telemetry()
    directory = tmp_path / "output"
    directory.mkdir()
    original_fchmod = os.fchmod

    def denied(fd: int, mode: int) -> None:
        if os.fstat(fd).st_ino == directory.stat().st_ino:
            raise PermissionError(1, "NEVER_PERSIST_PATH_OR_SECRET")
        original_fchmod(fd, mode)

    monkeypatch.setattr(module.os, "fchmod", denied)
    with module.memory_sampler(directory, cgroup_root=roots[0], proc_root=roots[1]) as thread:
        assert thread is None
    receipt = json.loads((directory / "memory-metrics.metadata.json").read_text())
    assert receipt["phase"] == "output.directory_permissions"
    assert receipt["source"] == "output"
    assert receipt["status"] == "unavailable"
    assert receipt["errno"] == 1
    assert receipt["end"] is False
    assert "NEVER_PERSIST" not in json.dumps(receipt)


def test_denied_cgroup_metric_preserves_other_metrics_and_private_diagnostics(
    roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    module = telemetry()
    original_read = module._read  # noqa: SLF001

    def denied(path: Path, *, dir_fd: int | None = None) -> str:
        if path.name == "memory.current":
            raise PermissionError(13, "NEVER_PERSIST_SECRET_PATH")
        return original_read(path, dir_fd=dir_fd)

    monkeypatch.setattr(module, "_read", denied)
    sample = module._sample(*roots)  # noqa: SLF001
    assert sample["cgroup"]["memory.current"] is None
    assert sample["cgroup"]["memory.peak"] == 4567
    assert sample["processes"][0]["rss_bytes"] > 0
    diagnostic = next(error for error in sample["errors"] if error["field"] == "memory.current")
    assert diagnostic["errno"] == 13
    assert diagnostic["source"] == "cgroup"
    assert diagnostic["phase"] == "read"
    assert diagnostic["status"] == "unavailable"
    assert "NEVER_PERSIST" not in json.dumps(sample)


def test_inaccessible_cgroup_root_still_collects_process_metrics(
    roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    module = telemetry()
    original_directory_fd = module._directory_fd  # noqa: SLF001

    def denied(path: Path, *, create: bool = False) -> int:
        if path == roots[0]:
            raise PermissionError(13, "NEVER_PERSIST_MOUNT_PATH")
        return original_directory_fd(path, create=create)

    monkeypatch.setattr(module, "_directory_fd", denied)
    sample = module._sample(*roots)  # noqa: SLF001
    assert all(value is None for value in sample["cgroup"].values())
    assert sample["processes"][0]["pid"] == 123
    assert sample["errors"] == [
        {
            "field": "cgroup",
            "error": "PermissionError",
            "source": "cgroup",
            "phase": "directory_open",
            "status": "unavailable",
            "errno": 13,
        }
    ]
    assert "NEVER_PERSIST" not in json.dumps(sample)


def test_fsync_failure_preserves_private_exit_receipt(
    tmp_path: Path, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    module = telemetry()
    directory = tmp_path / "output"
    with module.memory_sampler(
        directory, interval=60, cgroup_root=roots[0], proc_root=roots[1]
    ) as thread:
        await_samples(directory)
        metrics_inode = (directory / "memory-metrics.jsonl").stat().st_ino
        original_fsync = os.fsync

        def fail_metrics_sync(fd: int) -> None:
            if os.fstat(fd).st_ino == metrics_inode:
                raise OSError("do not persist this text")
            original_fsync(fd)

        monkeypatch.setattr(os, "fsync", fail_metrics_sync)
    assert not thread.is_alive()
    metadata = directory / "memory-metrics.metadata.json"
    receipt = json.loads(metadata.read_text())
    assert receipt["error"] == "OSError"
    assert receipt["end"] is True
    assert metadata.stat().st_mode & 0o777 == 0o600
    assert "do not persist" not in metadata.read_text()

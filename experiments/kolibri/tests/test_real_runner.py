"""Offline same-container retry exercises real subprocess and preserved logs."""

import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_same_runner_attempt_preserves_failed_output_before_success(monkeypatch, tmp_path):
    runner = importlib.import_module("real_runner")
    release = {"action": "preflight", "run_id": "hermes-kolibri-" + "a" * 32}
    repo = tmp_path / "repo"
    repo.mkdir()
    runs = repo / "experiments/kolibri/runs"
    runs.mkdir(parents=True)
    target = runs / release["run_id"]
    script = (
        "import pathlib,sys; p=pathlib.Path(sys.argv[1]); p.mkdir(); "
        "(p/'results.jsonl').write_text(sys.argv[2]); print(sys.argv[2]); "
        "sys.exit(int(sys.argv[3]))"
    )
    commands = iter(
        [
            [sys.executable, "-c", script, str(target), "first failure", "1"],
            [sys.executable, "-c", script, str(target), "second success", "0"],
        ]
    )
    monkeypatch.setattr(runner, "command", lambda release: next(commands))
    env = {"PATH": "/usr/bin:/bin"}
    assert runner.execute_attempt(release, tmp_path, env, 1) == "failed"
    assert runner.execute_attempt(release, tmp_path, env, 2) == "preflight-complete"
    old = tmp_path / "attempts/0001"
    assert (old / "runner-stdout.log").read_text() == "first failure\n"
    assert (old / "benchmark/results.jsonl").read_text() == "first failure"
    assert json.loads((old / "runner-status.json").read_text())["status"] == "failed"
    assert (tmp_path / "runner-stdout.log").read_text() == "second success\n"
    assert json.loads((tmp_path / "runner-status.json").read_text())["attempt"] == 2


def test_replay_request_requires_failed_idle_runner_and_next_attempt(tmp_path):
    runner = importlib.import_module("real_runner")
    status = tmp_path / "runner-status.json"
    status.write_text(json.dumps({"status": "running", "attempt": 1}))
    with pytest.raises(ValueError, match="failed"):
        runner.request_replay(tmp_path)
    status.write_text(json.dumps({"status": "failed", "attempt": 1}))
    assert runner.request_replay(tmp_path) == 2
    assert json.loads((tmp_path / "replay.json").read_text()) == {"attempt": 2}
    with pytest.raises(ValueError, match="pending"):
        runner.request_replay(tmp_path)


def test_replay_request_is_not_visible_until_complete(monkeypatch, tmp_path):
    runner = importlib.import_module("real_runner")
    (tmp_path / "runner-status.json").write_text('{"status":"failed","attempt":1}')
    dump = runner.json.dump

    def paused_dump(value, stream):
        assert not (tmp_path / "replay.json").exists(), "runner could read an incomplete request"
        dump(value, stream)

    monkeypatch.setattr(runner.json, "dump", paused_dump)
    assert runner.request_replay(tmp_path) == 2
    assert json.loads((tmp_path / "replay.json").read_text()) == {"attempt": 2}


def test_runner_main_remains_alive_after_failure_and_consumes_explicit_replay(
    monkeypatch, tmp_path
):
    runner = importlib.import_module("real_runner")
    (tmp_path / "repo").mkdir()
    (tmp_path / "released.json").write_text(
        json.dumps({"action": "run", "run_id": "hermes-kolibri-" + "a" * 32})
    )
    transport = tmp_path / "transport.json"
    transport.write_text('{"api_key":"DISPOSABLE_OFFLINE"}')
    path_type = Path

    def paths(value):
        if value == "/work":
            return tmp_path
        if value == "/work/released.json":
            return tmp_path / "released.json"
        if value == "/serving/transport.json":
            return transport
        return path_type(value)

    monkeypatch.setattr(runner, "Path", paths)
    marker = tmp_path / "child-count"
    script = "import pathlib,sys; p=pathlib.Path(sys.argv[1]); n=int(p.read_text())+1 if p.exists() else 1; p.write_text(str(n)); print(n); sys.exit(1 if n==1 else 0)"
    monkeypatch.setattr(
        runner, "command", lambda release: [sys.executable, "-c", script, str(marker)]
    )

    class EndProbe(Exception):
        pass

    def pause(seconds):
        status = json.loads((tmp_path / "runner-status.json").read_text())
        if status["attempt"] == 1:
            assert status["status"] == "failed"
            runner.request_replay(tmp_path)
        else:
            assert status["status"] == "complete"
            raise EndProbe

    monkeypatch.setattr(runner.time, "sleep", pause)
    with pytest.raises(EndProbe):
        runner.main()
    assert marker.read_text() == "2"
    assert (tmp_path / "attempts/0001/runner-stdout.log").read_text() == "1\n"
    assert (tmp_path / "runner-stdout.log").read_text() == "2\n"


def test_command_adds_staged_checkpoint_only_for_execution(monkeypatch, tmp_path):
    runner = importlib.import_module("real_runner")
    directory = tmp_path / "checkpoint"
    real_path = Path
    monkeypatch.setattr(
        runner, "Path", lambda value: directory if value == "/work/checkpoint" else real_path(value)
    )
    release = {"action": "run", "run_id": "hermes-kolibri-" + "a" * 32}
    assert "--resume-from" not in runner.command(release)
    directory.mkdir()
    assert runner.command(release)[-2:] == ["--resume-from", str(directory)]
    assert "--resume-from" not in runner.command({**release, "action": "preflight"})


def test_replay_uses_dynamic_archived_checkpoint_and_preserves_failure_and_metrics(
    monkeypatch, tmp_path
):
    from test_checkpoint import row, seed

    runner = importlib.import_module("real_runner")
    release = {"action": "run", "run_id": "hermes-kolibri-" + "b" * 32}
    benchmark = tmp_path / "repo/experiments/kolibri/runs" / release["run_id"]
    benchmark.parent.mkdir(parents=True)
    seed(benchmark, [row(day=d) for d in range(1, 14)])
    for name in ("config.yaml", "pins.json"):
        (benchmark.parents[1] / name).write_bytes(
            (Path(__file__).resolve().parents[1] / name).read_bytes()
        )
    frozen = (benchmark / "results.jsonl").read_bytes()
    (benchmark / "failure.json").write_text('{"old_failure":"preserved"}')
    (tmp_path / "runner-status.json").write_text('{"status":"failed","attempt":3}')
    (tmp_path / "memory-metrics.jsonl").write_text('{"attempt":3}\n')
    (tmp_path / "memory-metrics.metadata.json").write_text('{"limit":16777216}')
    observed = []
    monkeypatch.setattr(
        runner, "command", lambda release: ["offline-fake", "--resume-from", "/work/checkpoint"]
    )

    def execute(args, cwd, env, directory):
        observed.append(args)
        archived = tmp_path / "attempts/0003/benchmark"
        assert not benchmark.exists()
        assert args == ["offline-fake", "--resume-from", str(archived)]
        assert (archived / "results.jsonl").read_bytes() == frozen
        return 0

    monkeypatch.setattr(runner, "run_logged", execute)
    assert runner.execute_attempt(release, tmp_path, {}, 4) == "complete"
    assert observed
    assert (
        tmp_path / "attempts/0003/benchmark/failure.json"
    ).read_text() == '{"old_failure":"preserved"}'
    assert (tmp_path / "attempts/0003/memory-metrics.jsonl").read_text() == '{"attempt":3}\n'
    assert (
        tmp_path / "attempts/0003/memory-metrics.metadata.json"
    ).read_text() == '{"limit":16777216}'


def test_replay_checkpoint_survives_failure_before_next_benchmark_directory(monkeypatch, tmp_path):
    from test_checkpoint import row, seed

    runner = importlib.import_module("real_runner")
    release = {"action": "run", "run_id": "hermes-kolibri-" + "c" * 32}
    benchmark = tmp_path / "repo/experiments/kolibri/runs" / release["run_id"]
    benchmark.parent.mkdir(parents=True)
    seed(tmp_path / "checkpoint", [row(day=d) for d in range(1, 14)])
    seed(benchmark, [row(day=d) for d in range(1, 15)])
    for name in ("config.yaml", "pins.json"):
        (benchmark.parents[1] / name).write_bytes(
            (Path(__file__).resolve().parents[1] / name).read_bytes()
        )
    frozen = (benchmark / "results.jsonl").read_bytes()
    observed = []
    monkeypatch.setattr(
        runner, "command", lambda _: ["offline", "--resume-from", str(tmp_path / "checkpoint")]
    )
    monkeypatch.setattr(runner, "run_logged", lambda args, *rest: observed.append(args) or 1)
    assert runner.execute_attempt(release, tmp_path, {}, 2) == "failed"
    assert runner.execute_attempt(release, tmp_path, {}, 3) == "failed"
    archived = tmp_path / "attempts/0001/benchmark"
    assert [args[-1] for args in observed] == [str(archived), str(archived)]
    assert (archived / "results.jsonl").read_bytes() == frozen
    assert len((archived / "results.jsonl").read_text().splitlines()) == 14


@pytest.mark.parametrize(
    "fault", ["error", "duplicate", "pins", "config", "hash", "pointer", "regression"]
)
def test_replay_validates_latest_checkpoint_before_use_and_never_falls_back(
    monkeypatch, tmp_path, fault
):
    from test_checkpoint import row, seed

    runner = importlib.import_module("real_runner")
    release = {"action": "run", "run_id": "hermes-kolibri-" + "d" * 32}
    benchmark = tmp_path / "repo/experiments/kolibri/runs" / release["run_id"]
    benchmark.parent.mkdir(parents=True)
    seed(tmp_path / "checkpoint", [row(day=d) for d in range(1, 14)])
    seed(benchmark, [row(day=d) for d in range(1, 15)])
    for name in ("config.yaml", "pins.json"):
        (benchmark.parents[1] / name).write_bytes(
            (Path(__file__).resolve().parents[1] / name).read_bytes()
        )
    observed = []
    monkeypatch.setattr(
        runner, "command", lambda _: ["offline", "--resume-from", str(tmp_path / "checkpoint")]
    )
    monkeypatch.setattr(runner, "run_logged", lambda args, *rest: observed.append(args) or 1)
    assert runner.execute_attempt(release, tmp_path, {}, 2) == "failed"
    archive = tmp_path / "attempts/0001/benchmark"
    pointer = tmp_path / "latest-checkpoint.json"
    frozen_pointer = pointer.read_bytes()
    if fault == "error":
        results = [row(day=d, error="failure" if d == 14 else None) for d in range(1, 15)]
        (archive / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in results))
    elif fault == "duplicate":
        with (archive / "results.jsonl").open("a") as stream:
            stream.write(json.dumps(row()) + "\n")
    elif fault in {"pins", "config"}:
        target = archive / "manifest.json"
        manifest = json.loads(target.read_text())
        if fault == "pins":
            manifest["pins"]["plugin_commit"] = "0" * 40
        else:
            manifest["config"]["benchmark"]["models"][0]["disable_tool_choice"] = True
        target.write_text(json.dumps(manifest))
    elif fault == "hash":
        with (archive / "manifest.json").open("a") as stream:
            stream.write("\n")
    elif fault == "pointer":
        pointer.write_text(json.dumps({"directory": "../checkpoint", "provenance": {}}))
        frozen_pointer = pointer.read_bytes()
    else:
        seed(benchmark, [row(day=d) for d in range(1, 14)])
    assert runner.execute_attempt(release, tmp_path, {}, 3) == "failed"
    assert len(observed) == 1, "invalid latest progress must not run with the original 13-row seed"
    assert pointer.read_bytes() == frozen_pointer
    assert (tmp_path / "runner-failure.json").exists()
    assert (tmp_path / "runner-status.json").exists()


def test_logged_subprocess_is_covered_by_memory_sampler(monkeypatch, tmp_path):
    import types
    from contextlib import contextmanager

    runner = importlib.import_module("real_runner")
    boundaries = []

    @contextmanager
    def sample(directory):
        boundaries.append(("start", directory))
        yield
        boundaries.append(("stop", directory))

    monkeypatch.setitem(
        sys.modules, "memory_telemetry", types.SimpleNamespace(memory_sampler=sample)
    )
    code = runner.run_logged(
        [sys.executable, "-c", "print('OFFLINE_FIXTURE')"],
        str(tmp_path),
        {"PATH": "/usr/bin:/bin"},
        tmp_path,
    )
    assert code == 0
    assert boundaries == [("start", tmp_path), ("stop", tmp_path)]

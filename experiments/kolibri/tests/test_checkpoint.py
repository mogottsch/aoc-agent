"""Bounded offline checkpoint contract and real-core resume tests."""

import hashlib
import importlib
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run as preparation
from aoc_agent.benchmark.results import BenchmarkResult

EXPERIMENT = Path(__file__).resolve().parents[1]


def settings():
    return preparation.load_experiment(EXPERIMENT / "config.yaml")


def pins():
    return json.loads((EXPERIMENT / "pins.json").read_text())


def row(**overrides):
    data = BenchmarkResult(
        model=preparation.MODEL,
        year=2022,
        day=1,
        part1_correct=False,
        part2_correct=None,
        duration_seconds=0,
        error=None,
        trace_id="OFFLINE_FIXTURE",
        timestamp=datetime.now(UTC),
    ).model_dump(mode="json")
    data.update(overrides)
    return data


def seed(directory, rows, **overrides):
    directory.mkdir()
    manifest = {"status": "failed", "config": settings().model_dump(mode="json"), "pins": pins()}
    manifest.update(overrides)
    (directory / "manifest.json").write_text(json.dumps(manifest))
    (directory / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return directory


def helper():
    assert importlib.util.find_spec("checkpoint") is not None, "checkpoint validator is missing"
    return importlib.import_module("checkpoint").validated_checkpoint


def test_checkpoint_preserves_bytes_and_correctness_accepts_only_port_change(tmp_path):
    directory = seed(tmp_path / "seed", [row(day=d) for d in range(1, 14)])
    original = {
        name: (directory / name).read_bytes() for name in ("manifest.json", "results.jsonl")
    }
    config = settings()
    config.benchmark.providers["kolibri"].base_url = "http://127.0.0.1:8001/v1"
    imported = helper()(directory, config, pins())
    assert imported["completed"] == {(2022, d) for d in range(1, 14)}
    assert imported["results_bytes"] == original["results.jsonl"]
    assert imported["manifest_bytes"] == original["manifest.json"]
    assert (
        imported["provenance"]["results_sha256"]
        == hashlib.sha256(original["results.jsonl"]).hexdigest()
    )
    assert (
        imported["provenance"]["manifest_sha256"]
        == hashlib.sha256(original["manifest.json"]).hexdigest()
    )
    assert imported["provenance"]["saved_rows"] == 13
    assert imported["provenance"]["correctness"] == "preserved; nonerror does not imply correct"
    assert helper()(directory, config.model_dump(mode="json"), pins()) == imported
    assert {name: (directory / name).read_bytes() for name in original} == original


@pytest.mark.parametrize(
    "change",
    [
        {"day": 26},
        {"day": 0},
        {"year": 2024},
        {"model": "foreign"},
        {"error": "failed"},
        {"output_mode": "text"},
        {"disable_tool_choice": True},
        {"part1_correct": "false"},
        {"year": "2022"},
        {"duration_seconds": -1},
        {"duration_seconds": float("nan")},
        {"input_tokens": -1},
        {"unexpected": 1},
    ],
)
def test_rejects_invalid_or_foreign_result_rows(tmp_path, change):
    directory = seed(tmp_path / "seed", [row(**change)])
    with pytest.raises(
        ValueError, match=r"checkpoint|validation error|Expecting|incomplete isolated|immutable"
    ):
        helper()(directory, settings(), pins())


@pytest.mark.parametrize(
    "kind", ["duplicate", "blank", "truncated", "duplicate-field", "missing-field"]
)
def test_rejects_ambiguous_jsonl(tmp_path, kind):
    directory = seed(tmp_path / "seed", [row()])
    target = directory / "results.jsonl"
    body = target.read_text()
    target.write_text(
        {
            "duplicate": body + body,
            "blank": body + "\n",
            "truncated": body + '{"year":',
            "duplicate-field": body.replace('"day": 1', '"day": 1, "day": 2'),
            "missing-field": json.dumps({k: v for k, v in row().items() if k != "output_mode"})
            + "\n",
        }[kind]
    )
    with pytest.raises(
        ValueError, match=r"checkpoint|validation error|Expecting|incomplete isolated|immutable"
    ):
        helper()(directory, settings(), pins())


@pytest.mark.parametrize(
    "kind",
    ["pins", "revision", "settings", "years", "hostname", "unknown-config", "status", "seed"],
)
def test_rejects_incompatible_manifest_provenance(tmp_path, kind):
    directory = seed(tmp_path / "seed", [row()])
    target = directory / "manifest.json"
    manifest = json.loads(target.read_text())
    if kind == "pins":
        manifest["pins"]["image_digest"] = "sha256:" + "0" * 64
    elif kind == "revision":
        manifest["pins"]["model_revision"] = "main"
    elif kind == "settings":
        manifest["config"]["model_settings"]["temperature"] = 0.5
    elif kind == "years":
        manifest["config"]["benchmark"]["years"] = [2022]
    elif kind == "hostname":
        manifest["config"]["benchmark"]["providers"]["kolibri"]["base_url"] = "http://[::1]:8000/v1"
    elif kind == "unknown-config":
        manifest["config"]["benchmark"]["days"] = [1]
    elif kind == "status":
        manifest["status"] = "invented"
    else:
        manifest["seed"] = {"results_sha256": "forged", "saved_rows": 51}
    target.write_text(json.dumps(manifest))
    with pytest.raises(
        ValueError, match=r"checkpoint|validation error|Expecting|incomplete isolated|immutable"
    ):
        helper()(directory, settings(), pins())


@pytest.mark.parametrize(
    "kind",
    [
        "directory-link",
        "file-link",
        "ancestor-link",
        "traversal",
        "results-limit",
        "manifest-limit",
        "fifo",
    ],
)
def test_rejects_unsafe_checkpoint_files(tmp_path, kind):
    directory = seed(tmp_path / "seed", [row()])
    if kind == "directory-link":
        alias = tmp_path / "alias"
        alias.symlink_to(directory, target_is_directory=True)
        directory = alias
    elif kind == "ancestor-link":
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path, target_is_directory=True)
        directory = alias / "seed"
    elif kind == "file-link":
        target = directory / "results.jsonl"
        target.rename(tmp_path / "real.jsonl")
        target.symlink_to(tmp_path / "real.jsonl")
    elif kind == "traversal":
        directory = directory / ".." / "seed"
    elif kind in {"results-limit", "manifest-limit"}:
        import checkpoint

        name, limit = (
            ("results.jsonl", checkpoint.MAX_RESULTS_BYTES)
            if kind == "results-limit"
            else ("manifest.json", checkpoint.MAX_MANIFEST_BYTES)
        )
        (directory / name).write_bytes(b" " * (limit + 1))
    else:
        import os

        (directory / "results.jsonl").unlink()
        os.mkfifo(directory / "results.jsonl")
    with pytest.raises(
        ValueError, match=r"checkpoint|validation error|Expecting|incomplete isolated|immutable"
    ):
        helper()(directory, settings(), pins())


@pytest.mark.asyncio
async def test_real_core_failure_after_thirteen_resumes_only_remaining_thirty_seven(  # noqa: PLR0915 - complete real-core recovery proof
    tmp_path, monkeypatch
):
    import pydantic_ai.models
    from pydantic_ai.models.test import TestModel

    from aoc_agent.adapters.aoc.service import get_aoc_data_service
    from aoc_agent.adapters.storage.data_store import get_data_store
    from aoc_agent.core.settings import get_settings

    monkeypatch.setattr(preparation, "EXPERIMENT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EXECUTION_SANDBOX", "local")
    monkeypatch.setenv("AOC_SESSION_TOKEN", "OFFLINE_FIXTURE")
    for variable in ("EXECUTION_MEMORY_MB", "EXECUTION_CPU_QUOTA_PERCENT", "EXECUTION_TASKS_MAX"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(pydantic_ai.models, "ALLOW_MODEL_REQUESTS", False)
    for clear in (get_settings, get_data_store, get_aoc_data_service):
        clear.cache_clear()
    article = (
        '<article class="day-desc">OFFLINE_FIXTURE</article>'
        "<p>Your puzzle answer was <code>1</code></p>"
    )
    for year in (2022, 2023):
        folder = tmp_path / "cache" / str(year)
        folder.mkdir(parents=True)
        for day in range(1, 26):
            for suffix, body in {
                "unsolved.html": article,
                "input.txt": "fixture\n",
                "part1_solved.html": article,
                "part2_solved.html": article * 2,
            }.items():
                (folder / f"day_{day}.{suffix}").write_text(body)
    requests = []
    closed = []

    class Client:
        async def close(self):
            closed.append(True)

    class AsyncFakeModel(TestModel):
        async def request(self, messages, model_settings, model_request_parameters):
            requests.append(True)
            if len(requests) == 14:
                raise RuntimeError("deliberate offline partial failure")
            return await super().request(messages, model_settings, model_request_parameters)

    def model(_):
        fake = AsyncFakeModel(call_tools=[], custom_output_args={"part1": 999, "part2": 999})
        fake.client = Client()
        return fake

    monkeypatch.setattr(preparation, "build_model", model)
    config = settings()
    try:
        with pytest.raises(RuntimeError, match="deliberate"):
            await preparation.run_experiment(config, "first", pins=pins())
        original = tmp_path / "runs/first"
        files = {file.name: file.read_bytes() for file in original.iterdir()}
        assert len(helper()(original, config, pins())["completed"]) == 13
        before = len(requests)
        await preparation.run_experiment(config, "resumed", pins=pins(), resume_from=original)
        assert len(requests) - before == 37
        resumed = tmp_path / "runs/resumed"
        imported = helper()(resumed, config, pins())
        assert len(imported["completed"]) == 50
        output = [json.loads(line) for line in imported["results_bytes"].splitlines()]
        assert len(output) == len({(r["year"], r["day"]) for r in output}) == 50
        assert all(r["error"] is None for r in output)
        assert all(r["part1_correct"] is False for r in output)
        assert imported["results_bytes"].startswith(files["results.jsonl"])
        manifest = json.loads(imported["manifest_bytes"])
        assert (
            manifest["seed"]["results_sha256"] == hashlib.sha256(files["results.jsonl"]).hexdigest()
        )
        assert (resumed / "seed-manifest.json").read_bytes() == files["manifest.json"]
        assert {file.name: file.read_bytes() for file in original.iterdir()} == files
        # A complete checkpoint is an idempotent copy, with no model/client opened.
        monkeypatch.setattr(
            preparation, "build_model", lambda _: pytest.fail("completed seed opened model")
        )
        await preparation.run_experiment(config, "idempotent", pins=pins(), resume_from=resumed)
        assert (tmp_path / "runs/idempotent/results.jsonl").read_bytes() == imported[
            "results_bytes"
        ]
        assert closed == [True, True]
    finally:
        for clear in (get_settings, get_data_store, get_aoc_data_service):
            clear.cache_clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["duplicate", "error", "missing"])
async def test_completion_requires_fifty_unique_zero_error_physical_rows(
    tmp_path, monkeypatch, kind
):
    from aoc_agent.benchmark.results import append_result

    monkeypatch.setattr(preparation, "EXPERIMENT", tmp_path)

    class Client:
        async def close(self):
            pass

    class Fake:
        client = Client()

    monkeypatch.setattr(preparation, "build_model", lambda _: Fake())

    async def emit(model, year, day, path):
        if kind == "missing" and (year, day) == (2023, 25):
            return
        value = BenchmarkResult.model_validate(
            row(year=year, day=day, error="fixture error" if kind == "error" and day == 1 else None)
        )
        append_result(path, value)
        if kind == "duplicate" and day == 1:
            append_result(path, value)

    monkeypatch.setattr(preparation, "run_day", emit)
    with pytest.raises(
        ValueError, match=r"checkpoint|validation error|Expecting|incomplete isolated|immutable"
    ):
        await preparation.run_experiment(settings(), "invalid", pins=pins())
    assert json.loads((tmp_path / "runs/invalid/manifest.json").read_text())["status"] == "failed"


@pytest.mark.asyncio
async def test_bad_checkpoint_rejected_before_model_or_directory_creation(tmp_path, monkeypatch):
    directory = seed(tmp_path / "seed", [row(error="failure")])
    monkeypatch.setattr(preparation, "EXPERIMENT", tmp_path)
    monkeypatch.setattr(
        preparation, "build_model", lambda _: pytest.fail("invalid checkpoint opened model")
    )
    with pytest.raises(
        ValueError, match=r"checkpoint|validation error|Expecting|incomplete isolated|immutable"
    ):
        await preparation.run_experiment(settings(), "invalid", pins=pins(), resume_from=directory)
    assert not (tmp_path / "runs").exists()


def test_cli_resume_directory_is_relative_to_callers_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KOLIBRI_API_KEY", "OFFLINE_FIXTURE")
    monkeypatch.setattr(sys, "argv", ["run.py", "run", "--execute", "--resume-from", "seed"])
    monkeypatch.setattr(preparation, "preflight", lambda _: {"ready": True})

    async def capture(config, run_id, *, pins, resume_from):
        assert resume_from == tmp_path / "seed"

    monkeypatch.setattr(preparation, "run_experiment", capture)
    assert preparation.main() == 0

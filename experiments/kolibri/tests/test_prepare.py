"""Offline contract tests; never contact a model or a marketplace."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run as preparation

ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT = ROOT / "experiments" / "kolibri"


def test_default_is_read_only_preflight():
    script = EXPERIMENT / "run.py"
    assert script.is_file(), "a safe-default experiment entrypoint is missing"
    before = (ROOT / "results" / "results.jsonl").read_bytes()
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "KOLIBRI_API_KEY": "must-not-be-printed"},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert '"action": "preflight"' in result.stdout
    assert '"inference": false' in result.stdout
    assert "must-not-be-printed" not in result.stdout + result.stderr
    assert not (EXPERIMENT / "runs").exists()
    assert (ROOT / "results" / "results.jsonl").read_bytes() == before


def test_loads_strict_kolibri_config(tmp_path):
    config = preparation.load_experiment(EXPERIMENT / "config.yaml")
    assert config.benchmark.years == [2022, 2023]
    assert [m.model for m in config.benchmark.models] == ["Aleph-Alpha/Kolibri-1"]
    assert config.benchmark.global_parallelism == 1
    assert config.model_settings["temperature"] == 1.0
    assert config.model_settings["top_p"] == 0.97
    assert config.model_settings["extra_body"]["top_k"] == 128
    assert config.model_settings["extra_body"]["chat_template_kwargs"] == {
        "reasoning_effort": "high",
        "enable_thinking": True,
    }
    raw = yaml.safe_load((EXPERIMENT / "config.yaml").read_text())
    raw["benchmark"]["days"] = [1]
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError, match="unknown benchmark"):
        preparation.load_experiment(bad)


@pytest.mark.parametrize(
    "url",
    [
        "https://openrouter.ai/api/v1",
        "http://host.example/v1",
        "http://user:password@127.0.0.1:8000/v1",
        "http://127.0.0.1:8000/v1?key=x",
        "http://127.0.0.1:8000/v1#fragment",
        "file:///v1",
        "http://127.0.0.1:8000/",
    ],
)
def test_rejects_unsafe_endpoint(url):
    with pytest.raises(ValueError, match="loopback"):
        preparation.validate_endpoint(url)


@pytest.mark.parametrize("url", ["http://127.0.0.1:8000/v1", "http://[::1]:8000/v1"])
def test_accepts_literal_loopback_tunnel(url):
    assert preparation.validate_endpoint(url) == url


def test_cache_preflight_requires_all_inputs_prompts_and_answers(tmp_path):
    config = preparation.load_experiment(EXPERIMENT / "config.yaml")
    report = preparation.preflight(config, cache_dir=tmp_path)
    assert report["ready"] is False
    assert report["tasks"] == 50
    assert len(report["cache_errors"]) == 50
    assert list(tmp_path.iterdir()) == []  # no mkdir-on-read store API
    article = (
        '<article class="day-desc">fixture</article><p>Your puzzle answer was <code>1</code></p>'
    )
    for year in config.benchmark.years:
        folder = tmp_path / str(year)
        folder.mkdir()
        for day in range(1, 26):
            for suffix, text in {
                "unsolved.html": article,
                "input.txt": "fixture\n",
                "part1_solved.html": article,
                "part2_solved.html": article * 2,
            }.items():
                (folder / f"day_{day}.{suffix}").write_text(text)
    report = preparation.preflight(config, cache_dir=tmp_path)
    assert report["ready"] is True
    assert report["cache_errors"] == []
    (tmp_path / "2022/day_1.part2_solved.html").write_text("malformed")
    assert preparation.preflight(config, cache_dir=tmp_path)["ready"] is False


def test_serving_plan_is_pinned_authenticated_and_conservative():
    script = EXPERIMENT / "serve.py"
    assert script.is_file(), "missing safe serving planner"
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    plan = __import__("json").loads(result.stdout)
    assert plan["execution"] is False
    command = plan["command"]
    pins = __import__("json").loads((EXPERIMENT / "pins.json").read_text())
    assert pins["image_repository"] + "@" + pins["image_digest"] in command
    assert command[command.index("--revision") + 1] == pins["model_revision"]
    assert command[command.index("--tokenizer-revision") + 1] == pins["model_revision"]
    assert "127.0.0.1:8000:8000" in command
    assert "VLLM_API_KEY" in command
    assert command[command.index("--max-model-len") + 1] == "32768"
    assert command[command.index("--max-num-seqs") + 1] == "1"
    assert command[command.index("--kv-cache-dtype") + 1] == "fp8"
    assert command[command.index("--reasoning-parser") + 1] == "kolibri1"
    assert command[command.index("--tool-call-parser") + 1] == "kolibri1"
    assert "--enable-auto-tool-choice" in command


def test_dry_run_plans_fifty_tasks_without_creating_results():
    result = subprocess.run(
        [sys.executable, str(EXPERIMENT / "run.py"), "dry-run", "--run-id", "test-safe"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = __import__("json").loads(result.stdout)
    assert report["action"] == "dry-run"
    assert report["inference"] is False
    assert report["results_path"] == str(EXPERIMENT / "runs/test-safe/results.jsonl")
    assert len(report["schedule"]) == 50
    assert report["schedule"][0] == {"year": 2022, "day": 1}
    assert report["schedule"][-1] == {"year": 2023, "day": 25}
    assert not (EXPERIMENT / "runs").exists()


@pytest.mark.parametrize("run_id", ["../results", "/tmp/escape", ".", "..", "nested/name"])
def test_result_path_rejects_escape(run_id):
    with pytest.raises(ValueError, match=r"run-id|results"):
        preparation.result_directory(run_id)


def test_result_path_rejects_symlink_and_existing_run(tmp_path, monkeypatch):
    monkeypatch.setattr(preparation, "EXPERIMENT", tmp_path)
    (tmp_path / "runs").symlink_to(ROOT / "results", target_is_directory=True)
    with pytest.raises(ValueError, match=r"run-id|results"):
        preparation.result_directory("safe")
    (tmp_path / "runs").unlink()
    (tmp_path / "runs/safe").mkdir(parents=True)
    with pytest.raises(ValueError, match=r"run-id|results"):
        preparation.result_directory("safe")


def test_run_requires_explicit_execute_before_any_writes():
    result = subprocess.run(
        [sys.executable, str(EXPERIMENT / "run.py"), "run", "--run-id", "unsafe"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 2
    assert "requires --execute" in result.stderr
    assert not (EXPERIMENT / "runs").exists()


def test_model_receives_explicit_settings_without_resolving_other_credentials(monkeypatch):
    monkeypatch.setenv("KOLIBRI_API_KEY", "local-test-only")
    config = preparation.load_experiment(EXPERIMENT / "config.yaml")
    model = preparation.build_model(config)
    assert model.settings == config.model_settings
    assert model.model_name == "Aleph-Alpha/Kolibri-1"
    assert str(model.client.base_url) == "http://127.0.0.1:8000/v1/"


def test_execution_requires_dedicated_key(monkeypatch):
    monkeypatch.delenv("KOLIBRI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="KOLIBRI_API_KEY"):
        preparation.build_model(preparation.load_experiment(EXPERIMENT / "config.yaml"))


@pytest.mark.asyncio
async def test_local_labeled_fixture_exercises_agent_and_isolated_result(tmp_path, monkeypatch):
    import pydantic_ai.models
    from pydantic_ai.models.test import TestModel

    from aoc_agent.adapters.aoc.service import get_aoc_data_service
    from aoc_agent.adapters.storage.data_store import get_data_store
    from aoc_agent.benchmark.results import load_results
    from aoc_agent.core.settings import get_settings

    # Core sandbox tests can leave a cgroup Settings object in the process-wide LRU.
    # This local fixture must own and clear all its cache/environment dependencies.
    monkeypatch.setenv("EXECUTION_SANDBOX", "local")
    for variable in ("EXECUTION_MEMORY_MB", "EXECUTION_CPU_QUOTA_PERCENT", "EXECUTION_TASKS_MAX"):
        monkeypatch.delenv(variable, raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr(pydantic_ai.models, "ALLOW_MODEL_REQUESTS", False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AOC_SESSION_TOKEN", "local-fixture-not-a-cookie")
    get_data_store.cache_clear()
    get_aoc_data_service.cache_clear()
    folder = tmp_path / "cache/2022"
    folder.mkdir(parents=True)
    article = (
        '<article class="day-desc">local fixture</article>'
        "<p>Your puzzle answer was <code>1</code></p>"
    )
    (folder / "day_1.unsolved.html").write_text(article)
    (folder / "day_1.input.txt").write_text("fixture\n")
    (folder / "day_1.part1_solved.html").write_text(article)
    (folder / "day_1.part2_solved.html").write_text(article + article.replace("<code>1", "<code>2"))
    path = tmp_path / "fixture-output/results.jsonl"
    try:
        await preparation.run_day(
            TestModel(call_tools=[], custom_output_args={"part1": 1, "part2": 2}),
            2022,
            1,
            path,
            model_id="LOCAL_FIXTURE_NOT_KOLIBRI",
        )
        rows = list(load_results(path).values())
        assert len(rows) == 1
        assert rows[0].model == "LOCAL_FIXTURE_NOT_KOLIBRI"
        assert rows[0].part1_correct is True
        assert rows[0].part2_correct is True
        assert rows[0].error is None
        assert not (tmp_path / "results").exists()
    finally:
        get_settings.cache_clear()
        get_data_store.cache_clear()
        get_aoc_data_service.cache_clear()


@pytest.mark.asyncio
async def test_experiment_runs_full_schedule_and_saves_provenance(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from aoc_agent.benchmark.results import BenchmarkResult, append_result

    monkeypatch.setattr(preparation, "EXPERIMENT", tmp_path)
    config = preparation.load_experiment(EXPERIMENT / "config.yaml")
    calls = []

    class LocalFixtureClient:
        async def close(self):
            calls.append("closed")

    class LocalFixtureModel:
        client = LocalFixtureClient()

    monkeypatch.setattr(preparation, "build_model", lambda _: LocalFixtureModel())

    async def labeled_fixture(model, year, day, path):
        calls.append((year, day))
        append_result(
            path,
            BenchmarkResult(
                model=preparation.MODEL,
                year=year,
                day=day,
                part1_correct=False,
                part2_correct=False,
                duration_seconds=0,
                error=None,
                trace_id="fixture",
                timestamp=datetime.now(UTC),
            ),
        )

    monkeypatch.setattr(preparation, "run_day", labeled_fixture)
    await preparation.run_experiment(config, "local-fixture", pins={"fixture": True})
    assert calls[:-1] == [(y, d) for y in [2022, 2023] for d in range(1, 26)]
    assert calls[-1] == "closed"
    manifest = __import__("json").loads((tmp_path / "runs/local-fixture/manifest.json").read_text())
    assert manifest["status"] == "complete"
    assert manifest["saved_rows"] == 50
    assert manifest["pins"] == {"fixture": True}
    assert manifest["config"]["model_settings"] == config.model_settings
    assert not (tmp_path / "results").exists()


def test_public_metadata_verifier_exists_and_rejects_unpinned_inputs():
    script = EXPERIMENT / "verify_pins.py"
    assert script.is_file(), "missing repeatable read-only metadata verification"
    import verify_pins

    pins = __import__("json").loads((EXPERIMENT / "pins.json").read_text())
    verify_pins.validate_pins(pins)
    pins["model_revision"] = "main"
    with pytest.raises(ValueError, match="revision"):
        verify_pins.validate_pins(pins)


def test_public_verification_checks_hashes_and_never_requests_weights():
    import hashlib
    import json

    import verify_pins

    pins = json.loads((EXPERIMENT / "pins.json").read_text())

    def encoded(data):
        return json.dumps(data).encode()

    def digest(body):
        return "sha256:" + hashlib.sha256(body).hexdigest()

    image_config = encoded(
        {
            "config": {
                "Entrypoint": ["vllm", "serve"],
                "Env": ["CUDA_VERSION=13.0.2"],
                "Labels": {"org.opencontainers.image.version": "1.0.0-vllm0.29.0"},
            }
        }
    )
    child = encoded({"config": {"digest": digest(image_config)}})
    index = encoded(
        {
            "manifests": [
                {"platform": {"os": "linux", "architecture": "amd64"}, "digest": digest(child)}
            ]
        }
    )
    model_config = encoded(
        {"architectures": ["Kolibri1ForCausalLM"], "quantization_config": {"quant_method": "fp8"}}
    )
    generation = encoded({"temperature": 1.0, "top_p": 0.97, "top_k": 128})
    pins.update(
        image_digest=digest(index),
        linux_amd64_digest=digest(child),
        image_config_digest=digest(image_config),
        model_config_sha256=digest(model_config)[7:],
        generation_config_sha256=digest(generation)[7:],
    )
    requests = []

    def fixture_fetch(url, headers=None):
        requests.append(url)
        if "/token?" in url:
            return encoded({"token": "public-anonymous-fixture"})
        if url.endswith(("/manifests/" + pins["image_digest"], "/manifests/" + pins["image_tag"])):
            return index
        if url.endswith("/manifests/" + pins["linux_amd64_digest"]):
            return child
        if url.endswith("/blobs/" + pins["image_config_digest"]):
            return image_config
        if "/git/ref/" in url:
            return encoded({"object": {"sha": pins["plugin_commit"]}})
        if "/api/models/" in url:
            return encoded({"sha": pins["model_revision"], "gated": False})
        if url.endswith("/generation_config.json"):
            return generation
        if url.endswith("/config.json"):
            return model_config
        raise AssertionError("unexpected metadata URL: " + url)

    report = verify_pins.verify_public(pins, fetch=fixture_fetch)
    assert report["verified"] is True
    assert all("safetensors" not in url for url in requests)
    pins["image_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="digest"):
        verify_pins.verify_public(pins, fetch=fixture_fetch)


def test_execute_without_key_fails_before_any_result_writes():
    env = {k: v for k, v in os.environ.items() if k != "KOLIBRI_API_KEY"}
    result = subprocess.run(
        [sys.executable, str(EXPERIMENT / "run.py"), "run", "--execute", "--run-id", "no-key"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
        check=False,
    )
    assert result.returncode == 2
    assert "dedicated KOLIBRI_API_KEY" in result.stderr
    assert not (EXPERIMENT / "runs").exists()


def test_serve_execute_requires_key_without_launching_container():
    env = {k: v for k, v in os.environ.items() if k != "VLLM_API_KEY"}
    result = subprocess.run(
        [sys.executable, str(EXPERIMENT / "serve.py"), "--execute"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 2
    assert "VLLM_API_KEY" in result.stderr


def test_shell_helpers_are_safe_by_default_from_any_cwd(tmp_path):
    for name in ("run.sh", "serve.sh"):
        script = EXPERIMENT / name
        assert script.is_file(), "missing executable shell helper"
        result = subprocess.run(
            ["/usr/bin/bash", str(script)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert '"inference": false' in result.stdout or '"execution": false' in result.stdout
    assert not (EXPERIMENT / "runs").exists()


@pytest.mark.asyncio
async def test_failure_records_sanitized_manifest_and_closes_client(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr(preparation, "EXPERIMENT", tmp_path)
    config = preparation.load_experiment(EXPERIMENT / "config.yaml")
    closed = []

    class FixtureClient:
        async def close(self):
            closed.append(True)

    class FixtureModel:
        client = FixtureClient()

    monkeypatch.setattr(preparation, "build_model", lambda _: FixtureModel())

    async def fail(*args):
        raise RuntimeError("sensitive-provider-body-must-not-be-written")

    monkeypatch.setattr(preparation, "run_day", fail)
    with pytest.raises(RuntimeError, match="sensitive-provider"):
        await preparation.run_experiment(config, "failed-fixture", pins={"fixture": True})
    text = (tmp_path / "runs/failed-fixture/manifest.json").read_text()
    assert json.loads(text)["status"] == "failed"
    assert "sensitive-provider-body" not in text
    assert closed == [True]


@pytest.mark.asyncio
async def test_local_transport_fixture_serializes_sampling_and_reasoning(monkeypatch):
    import json

    import httpx
    from pydantic_ai import Agent

    seen = []

    def response(request):
        seen.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer local-test-only"
        return httpx.Response(
            200,
            json={
                "id": "LOCAL_FIXTURE",
                "object": "chat.completion",
                "created": 0,
                "model": preparation.MODEL,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "LOCAL_FIXTURE_NOT_INFERENCE"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    class FixtureHTTPClient(httpx.AsyncClient):
        def __init__(self, **kwargs):
            kwargs["transport"] = httpx.MockTransport(response)
            super().__init__(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FixtureHTTPClient)
    monkeypatch.setenv("KOLIBRI_API_KEY", "local-test-only")
    config = preparation.load_experiment(EXPERIMENT / "config.yaml")
    model = preparation.build_model(config)
    try:
        result = await Agent(model).run("LOCAL_WIRING_FIXTURE_ONLY")
        assert result.output == "LOCAL_FIXTURE_NOT_INFERENCE"
        assert len(seen) == 1
        assert seen[0]["temperature"] == 1.0
        assert seen[0]["top_p"] == 0.97
        assert seen[0]["top_k"] == 128
        assert seen[0]["max_completion_tokens"] == 8192
        assert seen[0]["chat_template_kwargs"] == {
            "reasoning_effort": "high",
            "enable_thinking": True,
        }
    finally:
        await model.client.close()

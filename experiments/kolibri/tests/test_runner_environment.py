"""Offline launcher boundary regressions; never invoke a model or provider."""

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_runner_forwards_literal_rlimit_memory_only():
    runner = importlib.import_module("real_runner")
    env = runner.child_environment(
        {
            "PATH": "/usr/bin:/bin",
            "EXECUTION_SANDBOX": "rlimit",
            "EXECUTION_MEMORY_MB": "4096",
            "API_KEY": "must-not-leak",
            "HTTPS_PROXY": "must-not-leak",
        }
    )
    assert env == {
        "PATH": "/usr/bin:/bin",
        "EXECUTION_SANDBOX": "rlimit",
        "EXECUTION_MEMORY_MB": "4096",
    }


@pytest.mark.parametrize("memory", [None, "512", "4096.0", "04096", " 4096", "4096 ", 4096, True])
def test_runner_rejects_invalid_rlimit_memory(memory):
    runner = importlib.import_module("real_runner")
    env = {"EXECUTION_SANDBOX": "rlimit"}
    if memory is not None:
        env["EXECUTION_MEMORY_MB"] = memory
    with pytest.raises(ValueError, match="literal EXECUTION_MEMORY_MB=4096"):
        runner.child_environment(env)


@pytest.mark.parametrize(
    "env",
    [
        {"EXECUTION_SANDBOX": "unknown"},
        {"EXECUTION_MEMORY_MB": "4096"},
        {"EXECUTION_SANDBOX": "local", "EXECUTION_MEMORY_MB": "4096"},
        {"EXECUTION_SANDBOX": "cgroup", "EXECUTION_MEMORY_MB": "4096"},
        {"EXECUTION_CPU_QUOTA_PERCENT": "200"},
        {"EXECUTION_TASKS_MAX": "128"},
        {"EXECUTION_FUTURE_SETTING": "anything"},
    ],
)
def test_runner_rejects_unsupported_execution_environment(env):
    with pytest.raises(ValueError):
        importlib.import_module("real_runner").child_environment(env)


def test_runner_main_passes_validated_memory_to_attempt(monkeypatch, tmp_path):
    import os

    runner = importlib.import_module("real_runner")
    release = {"action": "preflight", "run_id": "hermes-kolibri-" + "a" * 32}
    import json

    (tmp_path / "released.json").write_text(json.dumps(release))
    (tmp_path / "transport.json").write_text(json.dumps({"api_key": "offline-fixture"}))
    original_path = Path
    monkeypatch.setattr(
        runner,
        "Path",
        lambda value: tmp_path / original_path(value).name
        if str(value).startswith(("/work", "/serving"))
        else original_path(value),
    )
    monkeypatch.setattr(
        os, "environ", {"EXECUTION_SANDBOX": "rlimit", "EXECUTION_MEMORY_MB": "4096"}
    )
    seen = []

    class StopFixture(Exception):
        pass

    def execute(release, work, env, attempt):
        seen.append(env)
        raise StopFixture()

    monkeypatch.setattr(runner, "execute_attempt", execute)
    with pytest.raises(StopFixture):
        runner.main()
    assert seen == [
        {
            "EXECUTION_SANDBOX": "rlimit",
            "EXECUTION_MEMORY_MB": "4096",
            "KOLIBRI_API_KEY": "offline-fixture",
        }
    ]


def test_runner_environment_reaches_run_day_real_kernel_numpy(tmp_path):
    import os

    numpy_path = os.environ.get("AOC_TEST_NUMPY_PATH")
    if not numpy_path:
        pytest.skip("Supply existing compatible AOC_TEST_NUMPY_PATH; never install NumPy")
    runner = importlib.import_module("real_runner")
    root = Path(__file__).resolve().parents[3]
    env = runner.child_environment(
        {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(tmp_path),
            "TMPDIR": str(tmp_path),
            "PYTHONPATH": os.pathsep.join(
                [str(root / "src"), str(root / "experiments/kolibri"), numpy_path]
            ),
            "AOC_SESSION_TOKEN": "OFFLINE_NOT_A_COOKIE",
            "LOGFIRE_SEND_TO_LOGFIRE": "false",
            "EXECUTION_SANDBOX": "rlimit",
            "EXECUTION_MEMORY_MB": "4096",
        }
    )
    script = """
import asyncio, json
from pathlib import Path
from types import SimpleNamespace
import run
import aoc_agent.agent.runner as agent
import aoc_agent.adapters.aoc.service as service
from aoc_agent.adapters.execution.jupyter import jupyter_context
from aoc_agent.tools.execute import execute_python
from aoc_agent.core.settings import get_settings

class OfflineStop(Exception): pass
service.get_aoc_data_service = lambda **kw: SimpleNamespace(
    get=lambda *args: SimpleNamespace(input_content="2\\n3"),
    get_answers=lambda *args: SimpleNamespace(part1=None, part2=None))
async def offline_agent(model, context, **kwargs):
    settings = get_settings()
    assert str(settings.execution_sandbox) == 'rlimit'
    assert settings.execution_memory_mb == 4096
    async with jupyter_context(context) as deps:
        ctx = SimpleNamespace(deps=deps)
        limit = await execute_python(ctx, "import resource; print(resource.getrlimit(resource.RLIMIT_AS))")
        assert limit.error == '' and limit.output == '(4294967296, 4294967296)\\n', limit
        normal = await execute_python(ctx, "import numpy as np; print(np.arange(5).sum())")
        assert normal.error == '' and normal.output == '10\\n', normal
        for code in ['bytearray(5 * 1024**3)', 'np.ones(5 * 1024**3, dtype=np.uint8)']:
            over = await execute_python(ctx, code)
            assert 'MemoryError' in over.error, over
            recovered = await execute_python(ctx, 'print(np.arange(5).sum())')
            assert recovered.error == '' and recovered.output == '10\\n', recovered
        Path('kernel-proof.json').write_text(json.dumps({
            'settings_memory_mb': settings.execution_memory_mb,
            'hard_limit_bytes': 4294967296, 'numpy_sum': 10,
            'oversized_allocations': 'MemoryError', 'recovery': True,
            'route': 'real_runner.child_environment -> run.run_day -> jupyter_context -> Settings',
            'model_called': False}))
    raise OfflineStop()
agent.run_agent = offline_agent
async def main():
    try: await run.run_day(object(), 2022, 1, Path('never-results.jsonl'))
    except OfflineStop: pass
    else: raise AssertionError('offline sentinel was not reached')
asyncio.run(main())
print(Path('kernel-proof.json').read_text())
"""
    assert runner.run_logged([sys.executable, "-c", script], str(tmp_path), env, tmp_path) == 0, (
        tmp_path / "runner-stderr.log"
    ).read_text()
    import json

    proof = json.loads((tmp_path / "kernel-proof.json").read_text())
    assert proof["hard_limit_bytes"] == 4294967296
    assert proof["recovery"] is True and proof["model_called"] is False
    assert not (tmp_path / "never-results.jsonl").exists()

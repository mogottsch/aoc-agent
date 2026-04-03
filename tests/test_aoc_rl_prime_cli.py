import os
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from aoc_agent.cli import app


runner = CliRunner()


def test_prime_eval_command_uses_offline_dataset_and_writes_results(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class FakeEnv:
        def evaluate_sync(self, *, client, model, num_examples, rollouts_per_example, results_path, max_concurrent, sampling_args, save_results):
            captured["client"] = client
            captured["model"] = model
            captured["num_examples"] = num_examples
            captured["rollouts_per_example"] = rollouts_per_example
            captured["results_path"] = results_path
            captured["max_concurrent"] = max_concurrent
            captured["sampling_args"] = sampling_args
            captured["save_results"] = save_results
            Path(results_path).write_text('{"ok": true}\n')
            return [{"reward": 1.0}]

    def fake_load_prime_environment(cache_dir, results_path, year=None):
        captured["year"] = year
        return FakeEnv()

    monkeypatch.setattr(
        "aoc_agent.cli.load_prime_environment",
        fake_load_prime_environment,
    )
    monkeypatch.setattr(
        "aoc_agent.cli.get_settings",
        lambda: SimpleNamespace(prime_api_key="from-dotenv", aoc_offline_only=True),
    )
    monkeypatch.delenv("PRIME_API_KEY", raising=False)

    result = runner.invoke(
        app,
        [
            "prime-eval",
            "--model",
            "Qwen/Qwen3-4B-Instruct-2507",
            "--cache-dir",
            str(tmp_path / "cache"),
            "--results-path",
            str(tmp_path / "seed-results.jsonl"),
            "--output",
            str(tmp_path / "eval.jsonl"),
            "--year",
            "2022",
            "--num-examples",
            "5",
            "--rollouts-per-example",
            "2",
            "--max-concurrent",
            "3",
            "--max-tokens",
            "256",
        ],
    )

    assert result.exit_code == 0
    assert "Prime eval complete" in result.stdout
    assert captured["model"] == "Qwen/Qwen3-4B-Instruct-2507"
    assert captured["year"] == 2022
    assert captured["num_examples"] == 5
    assert captured["rollouts_per_example"] == 2
    assert captured["max_concurrent"] == 3
    assert captured["save_results"] is True
    assert captured["sampling_args"] == {"max_tokens": 256}
    assert os.environ["PRIME_API_KEY"] == "from-dotenv"
    assert Path(captured["results_path"]).read_text() == '{"ok": true}\n'


def test_prime_rollout_command_uses_generate_sync(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class FakeEnv:
        dataset = [{"prompt": [{"role": "user", "content": "solve it"}]}]

        def generate_sync(self, inputs, *, client, model, max_concurrent, sampling_args, results_path, save_results):
            captured["inputs"] = inputs
            captured["client"] = client
            captured["model"] = model
            captured["max_concurrent"] = max_concurrent
            captured["sampling_args"] = sampling_args
            captured["results_path"] = results_path
            captured["save_results"] = save_results
            Path(results_path).write_text('{"ok": true}\n')
            return [{"reward": 1.0}]

    def fake_load_prime_environment(cache_dir, results_path, year=None):
        captured["year"] = year
        return FakeEnv()

    monkeypatch.setattr(
        "aoc_agent.cli.load_prime_environment",
        fake_load_prime_environment,
    )
    monkeypatch.setattr(
        "aoc_agent.cli.get_settings",
        lambda: SimpleNamespace(prime_api_key="from-dotenv", aoc_offline_only=True),
    )

    result = runner.invoke(
        app,
        [
            "prime-rollout",
            "--model",
            "Qwen/Qwen3.5-4B",
            "--output",
            str(tmp_path / "rollout.jsonl"),
            "--year",
            "2022",
            "--max-concurrent",
            "4",
            "--max-tokens",
            "384",
        ],
    )

    assert result.exit_code == 0
    assert "Prime rollout complete" in result.stdout
    assert captured["model"] == "Qwen/Qwen3.5-4B"
    assert captured["year"] == 2022
    assert captured["max_concurrent"] == 4
    assert captured["sampling_args"] == {"max_tokens": 384}
    assert captured["save_results"] is True
    assert len(captured["inputs"]) == 1
    assert Path(captured["results_path"]).read_text() == '{"ok": true}\n'

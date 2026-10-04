"""An offline test receipt is not an independent review or launch approval."""

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_publisher_completes_all_scoped_checks_before_receipt(monkeypatch, tmp_path):
    controller = importlib.import_module("real_controller")
    calls = []

    def execute(command, **kwargs):
        calls.append(command)
        assert kwargs["env"]["AOC_SESSION_TOKEN"] == "OFFLINE_NOT_A_COOKIE"  # noqa: S105 - sentinel
        return subprocess.CompletedProcess(command, 0, stdout="fixture scoped check\n", stderr="")

    monkeypatch.setattr(controller.subprocess, "run", execute)
    output = tmp_path / "receipt"
    receipt = controller.publish_offline_receipt(output)
    assert len(calls) == 3
    assert receipt["all_scoped_checks_passed"] is True
    assert receipt["independent_review"] is False
    assert receipt["launch_approved"] is False
    assert receipt["benchmark_complete"] is False
    assert len(receipt["checks"]) == 3
    assert json.loads((output / "test-completion.json").read_text()) == receipt
    assert receipt["source_sha256"]["experiments/kolibri/real_runner.py"]


def test_failed_scoped_check_never_publishes_completion(monkeypatch, tmp_path):
    controller = importlib.import_module("real_controller")
    monkeypatch.setattr(
        controller.subprocess,
        "run",
        lambda command, **kw: subprocess.CompletedProcess(command, 1, stdout="failed\n", stderr=""),
    )
    output = tmp_path / "failed"
    with pytest.raises(RuntimeError, match="offline scoped check failed"):
        controller.publish_offline_receipt(output)
    assert not (output / "test-completion.json").exists()

"""Offline fresh-rental checkpoint derivation contract."""

import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_checkpoint import pins, row, seed, settings


def test_derive_checkpoint_freezes_raw_42_retains_wrong_answers_and_stages_fresh_rental(
    monkeypatch, tmp_path
):
    controller = importlib.import_module("real_controller")
    resume = importlib.import_module("real_resume")
    base = tmp_path / "base"
    base.mkdir()
    (base / "pins.json").write_text(json.dumps(pins()))
    monkeypatch.setattr(controller, "BASE", base)
    config = settings()
    monkeypatch.setattr(importlib.import_module("run"), "load_experiment", lambda path: config)
    errors = {(2022, 2), (2023, 3), (2023, 7)}
    rows = [
        row(year=y, day=d, error="OOM" if (y, d) in errors else None)
        for y in (2022, 2023)
        for d in range(1, 26)
        if y == 2022 or d <= 17
    ]
    source = seed(tmp_path / "source", rows, saved_rows=42, error_rows=3, status="running")
    raw = (source / "results.jsonl").read_bytes()
    manifest = (source / "manifest.json").read_bytes()
    destination = tmp_path / "resume39"
    result = resume.derive_nonerror_checkpoint(source, destination)
    assert result["retained_rows"] == 39
    assert result["filtered_errors"] == [[2022, 2], [2023, 3], [2023, 7]]
    provenance = json.loads((destination / "manifest.json").read_text())["seed"]
    assert provenance["raw_results_sha256"] == hashlib.sha256(raw).hexdigest()
    assert provenance["raw_manifest_sha256"] == hashlib.sha256(manifest).hexdigest()
    assert (destination / "raw/results.jsonl").read_bytes() == raw
    assert (destination / "raw/manifest.json").read_bytes() == manifest
    assert (source / "results.jsonl").read_bytes() == raw
    assert (source / "manifest.json").read_bytes() == manifest
    retained = [
        json.loads(line) for line in (destination / "results.jsonl").read_bytes().splitlines()
    ]
    assert len(retained) == 39 and all(r["part1_correct"] is False for r in retained)
    assert (destination / "results.jsonl").stat().st_mode & 0o777 == 0o400
    new_lease_directory = tmp_path / "fresh-lease"
    new_lease_directory.mkdir(mode=0o700)
    payload = controller.prepare_checkpoint(destination, new_lease_directory)
    assert controller.recover_checkpoint(new_lease_directory) == payload
    with pytest.raises(FileExistsError):
        resume.derive_nonerror_checkpoint(source, destination)

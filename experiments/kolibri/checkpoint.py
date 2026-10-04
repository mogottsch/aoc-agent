"""Bounded, read-only successful-day validation shared by controller and runner."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from run import ExperimentConfig

MAX_RESULTS_BYTES = 1_048_576
MAX_MANIFEST_BYTES = 262_144
MAX_ROW_BYTES = 65_536
MAX_ROWS = 50
MAX_PATH_BYTES = 4096
DAY_COUNT = 25
DAY_KEY_LENGTH = 2
CORRECTNESS = "preserved; nonerror does not imply correct"
SEED_FIELDS = {
    "schema_version",
    "source_directory",
    "source_status",
    "results_sha256",
    "manifest_sha256",
    "saved_rows",
    "completed",
    "correctness",
}


def _unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate checkpoint JSON field")
        result[key] = value
    return result


def _invalid_constant(_value: str) -> None:
    raise ValueError("nonfinite checkpoint JSON number")


def _json(body: bytes) -> dict:
    try:
        value = json.loads(
            body.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_invalid_constant
        )
        if not isinstance(value, dict):
            raise ValueError("checkpoint JSON must be an object")  # noqa: TRY004 - public validator contract
    except (UnicodeError, RecursionError) as error:
        raise ValueError("malformed checkpoint JSON") from error
    return value


def _read_files(directory: Path) -> tuple[bytes, bytes]:
    """Walk directory descriptors without following symlinks, including ancestors."""
    directory = Path(directory)
    if ".." in directory.parts or len(str(directory)) > MAX_PATH_BYTES:
        raise ValueError("unsafe checkpoint directory")
    absolute = directory.absolute()
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in absolute.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        bodies = []
        for name, limit in (
            ("results.jsonl", MAX_RESULTS_BYTES),
            ("manifest.json", MAX_MANIFEST_BYTES),
        ):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
            with os.fdopen(fd, "rb") as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                    raise ValueError("checkpoint requires bounded regular files")
                body = stream.read(limit + 1)
                after = os.fstat(stream.fileno())
                if (
                    len(body) > limit
                    or len(body) != before.st_size
                    or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                ):
                    raise ValueError("checkpoint file changed or exceeded limit")
                bodies.append(body)
        return bodies[0], bodies[1]
    except OSError as error:
        raise ValueError("unsafe or missing checkpoint files") from error
    finally:
        os.close(descriptor)


def validated_results(body: bytes, config: ExperimentConfig | dict) -> set[tuple[int, int]]:
    """Validate physical JSONL rows (no loader deduplication), never infer correctness."""
    from aoc_agent.benchmark.results import BenchmarkResult

    expected = config if isinstance(config, dict) else config.model_dump(mode="json")
    years = expected["benchmark"]["years"]
    model = expected["benchmark"]["models"][0]
    lines = body.splitlines()
    if len(body) > MAX_RESULTS_BYTES or len(lines) > MAX_ROWS:
        raise ValueError("checkpoint results exceeded limit")
    completed = set()
    for line in lines:
        if not line.strip() or len(line) > MAX_ROW_BYTES:
            raise ValueError("malformed or overlimit checkpoint row")
        raw = _json(line)
        if set(raw) != set(BenchmarkResult.model_fields):
            raise ValueError("checkpoint row fields must be explicit and known")
        row = BenchmarkResult.model_validate_json(json.dumps(raw), strict=True)
        key = (row.year, row.day)
        if (
            row.model != model["model"]
            or row.year not in years
            or not 1 <= row.day <= DAY_COUNT
            or row.output_mode.value != model["output_mode"]
            or row.disable_tool_choice != model["disable_tool_choice"]
            or row.error is not None
            or key in completed
        ):
            raise ValueError("duplicate, foreign or error checkpoint row")
        for field in (
            "duration_seconds",
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_cost",
        ):
            number = getattr(row, field)
            if number is not None and (not math.isfinite(number) or number < 0):
                raise ValueError("invalid checkpoint result metric")
        completed.add(key)
    return completed


def _validate_seed(seed: dict, completed: set[tuple[int, int]]) -> None:
    extra = {"raw_results_sha256", "raw_manifest_sha256", "source_rows", "filtered_errors"}
    version = seed.get("schema_version") if isinstance(seed, dict) else None
    if not isinstance(seed, dict) or set(seed) != (
        SEED_FIELDS | extra if version == 2 else SEED_FIELDS
    ):
        raise ValueError("incompatible checkpoint seed provenance")
    if version == 2:
        excluded = seed["filtered_errors"]
        if (
            not isinstance(excluded, list)
            or type(seed["source_rows"]) is not int
            or not 0 <= seed["source_rows"] <= MAX_ROWS
            or seed["source_rows"] != seed["saved_rows"] + len(excluded)
        ):
            raise ValueError("invalid filtered checkpoint totals")
        keys = set()
        for item in excluded:
            if (
                not isinstance(item, list)
                or len(item) != 2
                or any(type(n) is not int for n in item)
                or item[0] not in {2022, 2023}
                or not 1 <= item[1] <= DAY_COUNT
                or tuple(item) in keys
                or tuple(item) in set(map(tuple, seed["completed"]))
            ):
                raise ValueError("invalid filtered checkpoint errors")
            keys.add(tuple(item))
        for name in ("raw_results_sha256", "raw_manifest_sha256"):
            if not isinstance(seed[name], str) or re.fullmatch(r"[0-9a-f]{64}", seed[name]) is None:
                raise ValueError("invalid filtered checkpoint hash")
    days = seed["completed"]
    if (
        type(seed["schema_version"]) is not int
        or seed["schema_version"] not in {1, 2}
        or type(seed["saved_rows"]) is not int
        or not 0 <= seed["saved_rows"] <= MAX_ROWS
        or seed["source_status"] not in {"failed", "running", "complete"}
        or seed["correctness"] != CORRECTNESS
        or not isinstance(seed["source_directory"], str)
        or len(seed["source_directory"]) > MAX_PATH_BYTES
        or not isinstance(days, list)
        or len(days) != seed["saved_rows"]
    ):
        raise ValueError("incompatible checkpoint seed provenance")
    seen = set()
    for item in days:
        if (
            not isinstance(item, list)
            or len(item) != DAY_KEY_LENGTH
            or any(type(value) is not int for value in item)
            or tuple(item) not in completed
            or tuple(item) in seen
        ):
            raise ValueError("incompatible checkpoint seed days")
        seen.add(tuple(item))
    for name in ("results_sha256", "manifest_sha256"):
        if not isinstance(seed[name], str) or re.fullmatch(r"[0-9a-f]{64}", seed[name]) is None:
            raise ValueError("invalid checkpoint seed hash")


def filtered_checkpoint(directory: Path, config, pins) -> dict:
    """Validate every raw row; exclude only explicit errors, preserving wrong answers.

    Return raw immutable bytes as well as the derived seed. No filesystem writes.
    """
    raw_results, raw_manifest = _read_files(directory)
    manifest = _json(raw_manifest)
    lines = raw_results.splitlines(keepends=True)
    rows = [_json(line) for line in lines]
    normalized = []
    excluded = []
    retained = []
    for line, row in zip(lines, rows, strict=True):
        if row.get("error") is not None:
            # Validate the original error's type before neutralizing it for shared row checks.
            if not isinstance(row["error"], str):
                raise ValueError("invalid checkpoint error")
            excluded.append([row.get("year"), row.get("day")])
        else:
            retained.append(line)
        normalized.append(json.dumps(dict(row, error=None)).encode() + b"\n")
    all_completed = validated_results(b"".join(normalized), config)
    for field, count in (("saved_rows", len(rows)), ("error_rows", len(excluded))):
        if field in manifest and (type(manifest[field]) is not int or manifest[field] != count):
            raise ValueError("raw checkpoint totals disagree")
    # Validate full config, pins, seed and status before deriving anything.
    checking = dict(manifest)
    checking.update(saved_rows=len(rows), error_rows=0)
    _validated_bytes(directory, config, pins, b"".join(normalized), json.dumps(checking).encode())
    results = b"".join(retained)
    completed = all_completed - set(map(tuple, excluded))
    provenance = {
        "schema_version": 2,
        "source_directory": str(Path(directory).absolute()),
        "source_status": manifest["status"],
        "results_sha256": hashlib.sha256(results).hexdigest(),
        "manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(),
        "saved_rows": len(completed),
        "completed": [list(key) for key in sorted(completed)],
        "correctness": CORRECTNESS,
        "raw_results_sha256": hashlib.sha256(raw_results).hexdigest(),
        "raw_manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(),
        "source_rows": len(rows),
        "filtered_errors": sorted(excluded),
    }
    derived = dict(manifest)
    derived.update(status="failed", saved_rows=len(completed), error_rows=0, seed=provenance)
    validated = _validated_bytes(directory, config, pins, results, json.dumps(derived).encode())
    validated.update(raw_results_bytes=raw_results, raw_manifest_bytes=raw_manifest)
    return validated


def validated_checkpoint(directory: Path, config: ExperimentConfig | dict, pins: dict) -> dict:
    """Return exact results_bytes/manifest_bytes, provenance, completed year/day set.

    No writes/network. Read only two fixed files; 1 MiB JSONL, 256 KiB manifest,
    64 KiB/row, <=50 physical rows. All path components reject symlinks/traversal.
    Config and full immutable pins match exactly except literal loopback URL port.
    Running/failed checkpoints may be empty; every included row must be nonerror.
    """

    results_bytes, manifest_bytes = _read_files(directory)
    return _validated_bytes(directory, config, pins, results_bytes, manifest_bytes)


def _validated_bytes(directory, config, pins, results_bytes, manifest_bytes):
    from verify_pins import validate_pins

    from run import ExperimentConfig, validate_endpoint

    expected = config if isinstance(config, dict) else config.model_dump(mode="json")
    expected = json.loads(json.dumps(expected, allow_nan=False))
    ExperimentConfig.model_validate(expected)
    manifest = _json(manifest_bytes)
    try:
        source = manifest["config"]
        validate_pins(pins)
        validate_pins(manifest["pins"])
        if manifest["status"] not in {"running", "failed", "complete"}:
            raise ValueError("invalid checkpoint status")
        old_url = source["benchmark"]["providers"]["kolibri"]["base_url"]
        new_url = expected["benchmark"]["providers"]["kolibri"]["base_url"]
        validate_endpoint(old_url)
        validate_endpoint(new_url)
        old, new = urlsplit(old_url), urlsplit(new_url)
        if old.netloc.rsplit(":", 1)[0] != new.netloc.rsplit(":", 1)[0]:
            raise ValueError("checkpoint endpoint differences must be port-only")
        source["benchmark"]["providers"]["kolibri"]["base_url"] = new_url
        if json.dumps(source, sort_keys=True) != json.dumps(expected, sort_keys=True) or json.dumps(
            manifest["pins"], sort_keys=True
        ) != json.dumps(pins, sort_keys=True):
            raise ValueError("incompatible checkpoint config or pins provenance")
        completed = validated_results(results_bytes, expected)
        if "seed" in manifest:
            _validate_seed(manifest["seed"], completed)
        if manifest["status"] == "complete" and len(completed) != MAX_ROWS:
            raise ValueError("incomplete checkpoint claims completion")
        for field, value in (("saved_rows", len(completed)), ("error_rows", 0)):
            if field in manifest and (type(manifest[field]) is not int or manifest[field] != value):
                raise ValueError("checkpoint manifest row totals disagree")
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("malformed checkpoint provenance") from error
    return {
        "results_bytes": results_bytes,
        "manifest_bytes": manifest_bytes,
        "completed": completed,
        "provenance": {
            "schema_version": 1,
            "source_directory": str(Path(directory).absolute()),
            "source_status": manifest["status"],
            "results_sha256": hashlib.sha256(results_bytes).hexdigest(),
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "saved_rows": len(completed),
            "completed": [list(key) for key in sorted(completed)],
            "correctness": CORRECTNESS,
        },
    }

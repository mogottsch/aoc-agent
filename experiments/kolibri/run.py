"""Kolibri experiment: read-only by default; execution is always explicit."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from aoc_agent.adapters.aoc.parser import extract_answer_from_html
from aoc_agent.benchmark.config import BenchmarkConfig, ModelConfig, ProviderConfig

if TYPE_CHECKING:
    from pydantic_ai.models import Model
    from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings

DAY_COUNT = 25
EXPERIMENT = Path(__file__).resolve().parent
ROOT = EXPERIMENT.parents[1]
MODEL = "Aleph-Alpha/Kolibri-1"
SETTINGS = {
    "temperature": 1.0,
    "top_p": 0.97,
    "max_tokens": 8192,
    "timeout": 1800,
    "extra_body": {
        "top_k": 128,
        "chat_template_kwargs": {"reasoning_effort": "high", "enable_thinking": True},
    },
}


class ExperimentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    benchmark: BenchmarkConfig
    model_settings: dict

    @model_validator(mode="after")
    def kolibri_only(self) -> ExperimentConfig:
        b = self.benchmark
        expected = ModelConfig(model=MODEL, provider="kolibri", parallelism=1)
        if b.models != [expected] or set(b.providers) != {"kolibri"}:
            raise ValueError("only the Kolibri tool-mode model/provider is permitted")
        p = b.providers["kolibri"]
        if p.type != "openai" or p.api_key_env != "KOLIBRI_API_KEY":
            raise ValueError("Kolibri requires its dedicated OpenAI-compatible key environment")
        if b.years != [2022, 2023]:
            raise ValueError("full years 2022, 2023 are required; no day subset")
        if b.per_model_parallelism != 1 or b.global_parallelism != 1:
            raise ValueError("conservative parallelism must be one")
        if self.model_settings != SETTINGS:
            raise ValueError("explicit Kolibri sampling/reasoning settings are required")
        return self


def reject_unknown(data: dict, schema: type[BaseModel], label: str) -> None:
    if set(data) - set(schema.model_fields):
        message = f"unknown {label} fields"
        raise ValueError(message)


def load_experiment(path: Path) -> ExperimentConfig:
    raw = yaml.safe_load(path.read_text())
    b = raw["benchmark"]
    reject_unknown(b, BenchmarkConfig, "benchmark")
    for provider in b["providers"].values():
        reject_unknown(provider, ProviderConfig, "provider")
    for model in b["models"]:
        reject_unknown(model, ModelConfig, "model")
    return ExperimentConfig.model_validate(raw)


def validate_endpoint(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or parsed.port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/v1"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("endpoint must be a literal loopback HTTP tunnel with port and /v1")
    return url


def preflight(config: ExperimentConfig, cache_dir: Path = ROOT / "cache") -> dict:
    validate_endpoint(config.benchmark.providers["kolibri"].base_url)
    errors = []
    for year in config.benchmark.years:
        for day in range(1, 26):
            prefix = cache_dir / str(year) / f"day_{day}"
            issues = []
            for suffix in ("unsolved.html", "input.txt"):
                path = Path(f"{prefix}.{suffix}")
                if not path.is_file() or not path.stat().st_size:
                    issues.append(f"missing/empty {suffix}")
            for part in (1, 2) if day != DAY_COUNT else (1,):
                path = Path(f"{prefix}.part{part}_solved.html")
                if not path.is_file() or extract_answer_from_html(path.read_text(), part) is None:
                    issues.append(f"missing/unparseable part{part} answer")
            if issues:
                errors.append({"year": year, "day": day, "issues": issues})
    return {
        "action": "preflight",
        "inference": False,
        "ready": not errors,
        "tasks": len(config.benchmark.years) * 25,
        "cache_errors": errors,
        "endpoint": config.benchmark.providers["kolibri"].base_url,
        "model_settings": config.model_settings,
    }


def result_directory(run_id: str) -> Path:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", run_id) is None:
        raise ValueError("run-id must be a simple alphanumeric label (up to 64 characters)")
    runs = EXPERIMENT / "runs"
    target = runs / run_id
    if runs.is_symlink() or target.is_symlink() or target.exists():
        raise ValueError("results require a fresh isolated run directory without symlinks")
    if target.resolve().parent != runs.absolute() or runs.parent.resolve() != EXPERIMENT:
        raise ValueError("results path escapes experiment")
    return target


def build_model(config: ExperimentConfig) -> OpenAIChatModel:
    import httpx
    from openai import AsyncOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    endpoint = validate_endpoint(config.benchmark.providers["kolibri"].base_url)
    key = os.environ.get("KOLIBRI_API_KEY")
    if not key or key == "EMPTY":
        raise ValueError("a dedicated KOLIBRI_API_KEY is required")
    client = AsyncOpenAI(
        base_url=endpoint,
        api_key=key,
        max_retries=0,
        http_client=httpx.AsyncClient(trust_env=False, follow_redirects=False),
    )
    return OpenAIChatModel(
        MODEL,
        provider=OpenAIProvider(openai_client=client),
        settings=cast("OpenAIChatModelSettings", config.model_settings),
    )


async def run_day(
    model: Model, year: int, day: int, results_path: Path, *, model_id: str = MODEL
) -> None:
    import time

    from pydantic_ai.usage import RunUsage

    from aoc_agent.adapters.aoc.service import get_aoc_data_service
    from aoc_agent.agent.runner import run_agent
    from aoc_agent.benchmark.execution import create_benchmark_result
    from aoc_agent.benchmark.results import append_result
    from aoc_agent.core.models import SolveStatus
    from aoc_agent.tools.context import ToolContext

    service = get_aoc_data_service(offline=True)
    data = service.get(year, day)
    known = service.get_answers(year, day)
    context = ToolContext(
        year=year,
        day=day,
        input_content=data.input_content,
        solve_status=SolveStatus(),
        offline=True,
    )
    start = time.perf_counter()
    usage = RunUsage()
    result = await run_agent(
        model, context, model_name=model_id, allow_sleep=False, run_usage=usage
    )
    row = create_benchmark_result(
        model_id, year, day, known.part1, known.part2, result, time.perf_counter() - start
    )
    row.input_tokens = usage.input_tokens
    row.output_tokens = usage.output_tokens
    append_result(results_path, row)


async def run_experiment(  # noqa: C901, PLR0912, PLR0915 - owns seed, failure and client lifetimes
    config: ExperimentConfig, run_id: str, *, pins: dict, resume_from: Path | None = None
) -> None:
    from checkpoint import MAX_RESULTS_BYTES, validated_checkpoint, validated_results
    from diagnostics import private_write, save_failure  # isort: skip

    checkpoint = (
        validated_checkpoint(resume_from, config, pins) if resume_from is not None else None
    )
    completed = checkpoint["completed"] if checkpoint is not None else set()
    directory = result_directory(run_id)
    model = None
    year = day = None
    manifest_path: Path | None = None
    manifest = {"status": "running", "config": config.model_dump(mode="json"), "pins": pins}
    if checkpoint is not None:
        manifest["seed"] = checkpoint["provenance"]
    try:
        directory.parent.mkdir(exist_ok=True)
        directory.mkdir(mode=0o700)  # atomic; resumed results also require a NEW directory
        manifest_path = directory / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        path = directory / "results.jsonl"
        if checkpoint is not None:
            body = checkpoint["results_bytes"]
            path.write_bytes(body + (b"\n" if body and not body.endswith(b"\n") else b""))
            (directory / "seed-manifest.json").write_bytes(checkpoint["manifest_bytes"])
        else:
            path.touch(mode=0o600)
        expected = {(y, d) for y in config.benchmark.years for d in range(1, 26)}
        if completed != expected:
            model = build_model(config)
        for year in config.benchmark.years:
            for day in range(1, 26):
                if (year, day) not in completed:
                    await run_day(cast("Model", model), year, day, path)
        with path.open("rb") as stream:
            actual = validated_results(stream.read(MAX_RESULTS_BYTES + 1), config)
        if actual != expected:
            raise ValueError("incomplete isolated benchmark output")  # noqa: TRY301 - local completeness check
        manifest.update(
            status="complete",
            saved_rows=len(actual),
            error_rows=0,
        )
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    except BaseException as error:
        # Full sanitized evidence stays private, never sent to telemetry/CLI output.
        if manifest_path is not None:
            save_failure(directory, error, year=year, day=day)
            manifest["status"] = "failed"
            manifest.update(current_year=year, current_day=day, diagnostics="failure.json")
            private_write(manifest_path, json.dumps(manifest, indent=2) + "\n")
        raise
    finally:
        if model is not None:
            primary_error = sys.exception()
            try:
                await model.client.close()
            except BaseException as error:
                save_failure(directory, error, year=year, day=day, prefix="client-close-failure")
                if primary_error is None:
                    manifest["status"] = "failed"
                    private_write(
                        directory / "manifest.json", json.dumps(manifest, indent=2) + "\n"
                    )
                    raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", nargs="?", choices=["preflight", "dry-run", "run"], default="preflight"
    )
    parser.add_argument(
        "--execute", action="store_true", help="explicitly permit inference for action run"
    )
    parser.add_argument("--config", type=Path, default=EXPERIMENT / "config.yaml")
    parser.add_argument("--run-id", default="kolibri-preparation")
    parser.add_argument(
        "--resume-from", type=Path, help="validated successful-day checkpoint directory"
    )
    args = parser.parse_args()
    if args.action == "run" and not args.execute:
        parser.error("run requires --execute; this permits real model inference")
    if args.execute and args.action != "run":
        parser.error("--execute is only valid with run")
    if args.resume_from is not None and args.action != "run":
        parser.error("--resume-from is only valid with run")
    try:
        config = load_experiment(args.config)
        report = preflight(config)
        from verify_pins import validate_pins

        pins = json.loads((EXPERIMENT / "pins.json").read_text())
        validate_pins(pins)
        report.update(pins=pins, pins_check="format; use verify_pins.py for live public metadata")
        if args.action == "run":
            if not report["ready"]:
                parser.error("cache preflight failed; no execution performed")
            if not os.environ.get("KOLIBRI_API_KEY") or os.environ["KOLIBRI_API_KEY"] == "EMPTY":
                parser.error("a dedicated KOLIBRI_API_KEY is required; no execution performed")
            import logfire

            logfire.configure(send_to_logfire=False, console=False)
            resume_from = args.resume_from.absolute() if args.resume_from is not None else None
            os.chdir(ROOT)  # core offline store/agent APIs use cwd/cache
            try:
                asyncio.run(run_experiment(config, args.run_id, pins=pins, resume_from=resume_from))
            except Exception:  # noqa: BLE001 - redact untrusted provider exceptions at CLI boundary
                parser.exit(
                    1,
                    "Benchmark failed; partial isolated results may exist. "
                    "Sanitized failure details retained in private run artifacts.\n",
                )
            print(
                json.dumps(
                    {
                        "status": "complete",
                        "results_path": str(EXPERIMENT / "runs" / args.run_id / "results.jsonl"),
                    }
                )
            )
            return 0
        if args.action == "dry-run":
            report.update(
                {
                    "action": "dry-run",
                    "results_path": str(result_directory(args.run_id) / "results.jsonl"),
                    "schedule": [
                        {"year": y, "day": d} for y in config.benchmark.years for d in range(1, 26)
                    ],
                }
            )
        print(json.dumps(report, indent=2))
        return 0 if report["ready"] else 1
    except (ValueError, KeyError, TypeError, OSError):
        parser.exit(
            2, "Invalid configuration, cache or isolated run path; no execution performed.\n"
        )


if __name__ == "__main__":
    raise SystemExit(main())

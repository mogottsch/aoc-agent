from collections import defaultdict
from pathlib import Path

import httpx
from pydantic import BaseModel
from tabulate import tabulate

from aoc_agent.benchmark.logfire_usage import TraceUsage, fetch_trace_usage
from aoc_agent.benchmark.results import BenchmarkResult, load_all_results


class ModelPricing(BaseModel):
    prompt: float
    completion: float


def fetch_pricing() -> dict[str, ModelPricing]:
    response = httpx.get("https://openrouter.ai/api/v1/models")
    response.raise_for_status()
    data = response.json()["data"]
    return {
        m["id"]: ModelPricing(
            prompt=float(m["pricing"]["prompt"]),
            completion=float(m["pricing"]["completion"]),
        )
        for m in data
    }


class ModelStats(BaseModel):
    model: str
    days_run: int
    part1_correct: int
    part2_correct: int
    avg_score: float
    avg_tokens: int
    avg_cost: float | None
    avg_duration: float
    total_cost: float | None = None


def _usage_map(trace_usage: list[TraceUsage]) -> dict[str, TraceUsage]:
    return {usage.trace_id: usage for usage in trace_usage}


def _legacy_usage(result: BenchmarkResult) -> TraceUsage | None:
    if result.input_tokens is None or result.output_tokens is None:
        return None
    reasoning_tokens = result.reasoning_tokens or 0
    return TraceUsage(
        trace_id=result.trace_id,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        reasoning_tokens=reasoning_tokens,
    )


def _compute_stats(
    model: str,
    results: list[BenchmarkResult],
    pricing: ModelPricing | None,
    usage_by_trace: dict[str, TraceUsage],
) -> ModelStats:
    days_run = len(results)
    part1_correct = sum(1 for r in results if r.part1_correct is True)
    part2_correct = sum(1 for r in results if r.part2_correct is True)
    total_correct = part1_correct + part2_correct
    avg_score = (total_correct / (days_run * 2)) * 100 if days_run > 0 else 0.0
    total_tokens = 0
    total_cost = 0.0
    for result in results:
        usage = usage_by_trace[result.trace_id]
        total_tokens += usage.input_tokens + usage.output_tokens + usage.reasoning_tokens
        if pricing is not None:
            total_cost += (
                usage.input_tokens * pricing.prompt + usage.output_tokens * pricing.completion
            )
    avg_tokens = total_tokens // days_run if days_run > 0 else 0
    total_duration = sum(r.duration_seconds for r in results)
    avg_duration = total_duration / days_run if days_run > 0 else 0.0
    if pricing is not None and days_run > 0:
        avg_cost = total_cost / days_run
    else:
        total_cost = None
        avg_cost = None
    return ModelStats(
        model=model,
        days_run=days_run,
        part1_correct=part1_correct,
        part2_correct=part2_correct,
        avg_score=avg_score,
        avg_tokens=avg_tokens,
        avg_cost=avg_cost,
        avg_duration=avg_duration,
        total_cost=total_cost,
    )


def aggregate_by_model(
    results: list[BenchmarkResult],
    pricing: dict[str, ModelPricing],
    usage_by_trace: dict[str, TraceUsage],
) -> list[ModelStats]:
    by_model: dict[str, list[BenchmarkResult]] = defaultdict(list)
    for r in results:
        by_model[r.model].append(r)
    stats = [
        _compute_stats(model, model_results, pricing.get(model), usage_by_trace)
        for model, model_results in by_model.items()
    ]
    return sorted(stats, key=lambda s: (-s.avg_score, s.model))


def aggregate_by_model_year(
    results: list[BenchmarkResult],
    pricing: dict[str, ModelPricing],
    usage_by_trace: dict[str, TraceUsage],
) -> dict[int, list[ModelStats]]:
    by_year_model: dict[int, dict[str, list[BenchmarkResult]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for r in results:
        by_year_model[r.year][r.model].append(r)
    out: dict[int, list[ModelStats]] = {}
    for year, by_model in sorted(by_year_model.items()):
        stats = [
            _compute_stats(model, model_results, pricing.get(model), usage_by_trace)
            for model, model_results in by_model.items()
        ]
        out[year] = sorted(stats, key=lambda s: (-s.avg_score, s.model))
    return out


def _format_cost(cost: float | None) -> str:
    if cost is None:
        return "N/A"
    return f"${cost:.4f}"


def _render_cost_summary_table(stats: list[ModelStats]) -> str:
    sorted_stats = sorted(stats, key=lambda s: s.total_cost or 0, reverse=True)
    rows = [[s.model, str(s.days_run), _format_cost(s.total_cost)] for s in sorted_stats]

    total_cost_all = sum(s.total_cost for s in stats if s.total_cost is not None)
    total_days = sum(s.days_run for s in stats)
    rows.append(["**Total**", f"**{total_days}**", f"**{_format_cost(total_cost_all)}**"])
    return tabulate(rows, headers=["Model", "Days", "Total Cost"], tablefmt="github")


def _render_table(stats: list[ModelStats], include_days: bool) -> str:
    rank = 1
    rows: list[list[str]] = []
    for i, s in enumerate(stats):
        # Dense ranking: same score = same rank, next rank increments by 1
        if i > 0 and s.avg_score != stats[i - 1].avg_score:
            rank += 1
        parts = [str(rank), s.model]
        if include_days:
            parts.append(str(s.days_run))
        parts.extend(
            [
                f"{s.part1_correct}/{s.days_run}",
                f"{s.part2_correct}/{s.days_run}",
                f"{s.avg_score:.1f}%",
                f"{s.avg_tokens:,}",
                _format_cost(s.avg_cost),
                f"{s.avg_duration:.1f}s",
            ]
        )
        rows.append(parts)
    headers = (
        [
            "Rank",
            "Model",
            "Days",
            "Part 1",
            "Part 2",
            "Score",
            "Avg Tokens",
            "Avg Cost",
            "Avg Duration",
        ]
        if include_days
        else [
            "Rank",
            "Model",
            "Part 1",
            "Part 2",
            "Score",
            "Avg Tokens",
            "Avg Cost",
            "Avg Duration",
        ]
    )
    return tabulate(rows, headers=headers, tablefmt="github")


def render_markdown(overall: list[ModelStats], by_year: dict[int, list[ModelStats]]) -> str:
    sections = ["# Benchmark Results", "", "## Overall", ""]
    sections.append("Models ranked by average score across all attempted days.")
    sections.append("")
    sections.append(_render_table(overall, include_days=True))
    sections.append("")
    sections.append("")
    sections.append("## Cost Summary")
    sections.append("")
    sections.append("Total cost per model and overall cost across all models.")
    sections.append("")
    sections.append(_render_cost_summary_table(overall))
    for year, stats in sorted(by_year.items()):
        sections.append("")
        sections.append("---")
        sections.append("")
        sections.append(f"## {year}")
        sections.append("")
        sections.append(_render_table(stats, include_days=False))
    sections.append("")
    return "\n".join(sections)


def generate_report(results_dir: Path, *, logfire_read_token: str) -> str:
    results = load_all_results(results_dir)
    if not results:
        raise ValueError("No results found")
    trace_ids = [result.trace_id for result in results]
    if any(not trace_id for trace_id in trace_ids):
        raise ValueError("Missing trace_id in results")
    trace_usage = fetch_trace_usage(logfire_read_token, trace_ids)
    usage_by_trace = _usage_map(trace_usage)
    missing = [trace_id for trace_id in trace_ids if trace_id not in usage_by_trace]
    if missing:
        for result in results:
            if result.trace_id in missing:
                legacy = _legacy_usage(result)
                if legacy is not None:
                    usage_by_trace[result.trace_id] = legacy
        still_missing = [trace_id for trace_id in trace_ids if trace_id not in usage_by_trace]
        if still_missing:
            raise ValueError("Logfire usage missing for some trace_ids and no legacy tokens found")
    pricing = fetch_pricing()
    overall = aggregate_by_model(results, pricing, usage_by_trace)
    by_year = aggregate_by_model_year(results, pricing, usage_by_trace)
    return render_markdown(overall, by_year)

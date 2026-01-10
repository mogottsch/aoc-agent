from collections import defaultdict
from pathlib import Path

import httpx
from pydantic import BaseModel

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


def _compute_stats(
    model: str, results: list[BenchmarkResult], pricing: ModelPricing | None
) -> ModelStats:
    days_run = len(results)
    part1_correct = sum(1 for r in results if r.part1_correct is True)
    part2_correct = sum(1 for r in results if r.part2_correct is True)
    total_correct = part1_correct + part2_correct
    avg_score = (total_correct / (days_run * 2)) * 100 if days_run > 0 else 0.0
    total_tokens = sum(r.input_tokens + r.output_tokens for r in results)
    avg_tokens = total_tokens // days_run if days_run > 0 else 0
    total_duration = sum(r.duration_seconds for r in results)
    avg_duration = total_duration / days_run if days_run > 0 else 0.0
    if pricing and days_run > 0:
        total_cost = sum(
            r.input_tokens * pricing.prompt + r.output_tokens * pricing.completion for r in results
        )
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
    results: list[BenchmarkResult], pricing: dict[str, ModelPricing]
) -> list[ModelStats]:
    by_model: dict[str, list[BenchmarkResult]] = defaultdict(list)
    for r in results:
        by_model[r.model].append(r)
    stats = [
        _compute_stats(model, model_results, pricing.get(model))
        for model, model_results in by_model.items()
    ]
    return sorted(stats, key=lambda s: (-s.avg_score, s.model))


def aggregate_by_model_year(
    results: list[BenchmarkResult], pricing: dict[str, ModelPricing]
) -> dict[int, list[ModelStats]]:
    by_year_model: dict[int, dict[str, list[BenchmarkResult]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for r in results:
        by_year_model[r.year][r.model].append(r)
    out: dict[int, list[ModelStats]] = {}
    for year, by_model in sorted(by_year_model.items()):
        stats = [
            _compute_stats(model, model_results, pricing.get(model))
            for model, model_results in by_model.items()
        ]
        out[year] = sorted(stats, key=lambda s: (-s.avg_score, s.model))
    return out


def _format_cost(cost: float | None) -> str:
    if cost is None:
        return "N/A"
    return f"${cost:.4f}"


def _format_table_row(rank: int, s: ModelStats, include_days: bool) -> str:
    parts = [
        str(rank),
        s.model,
    ]
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
    return "| " + " | ".join(parts) + " |"


def _render_cost_summary_table(stats: list[ModelStats]) -> str:
    header = "| Model | Days | Total Cost |"
    separator = "|-------|------|------------|"
    lines = [header, separator]

    sorted_stats = sorted(stats, key=lambda s: s.total_cost or 0, reverse=True)

    for s in sorted_stats:
        model_name = s.model
        days = str(s.days_run)
        total_cost = _format_cost(s.total_cost)
        lines.append(f"| {model_name} | {days} | {total_cost} |")

    total_cost_all = sum(s.total_cost for s in stats if s.total_cost is not None)
    total_days = sum(s.days_run for s in stats)
    lines.append("")
    lines.append(f"| **Total** | **{total_days}** | **{_format_cost(total_cost_all)}** |")

    return "\n".join(lines)


def _render_table(stats: list[ModelStats], include_days: bool) -> str:
    if include_days:
        header = (
            "| Rank | Model | Days | Part 1 | Part 2 | Score | "
            "Avg Tokens | Avg Cost | Avg Duration |"
        )
        separator = (
            "|------|-------|------|--------|--------|-------|"
            "------------|----------|--------------|"
        )
    else:
        header = "| Rank | Model | Part 1 | Part 2 | Score | Avg Tokens | Avg Cost | Avg Duration |"
        separator = (
            "|------|-------|--------|--------|-------|------------|----------|--------------|"
        )
    lines = [header, separator]
    for rank, s in enumerate(stats, 1):
        lines.append(_format_table_row(rank, s, include_days))
    return "\n".join(lines)


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


def generate_report(results_dir: Path) -> str:
    results = load_all_results(results_dir)
    pricing = fetch_pricing()
    overall = aggregate_by_model(results, pricing)
    by_year = aggregate_by_model_year(results, pricing)
    return render_markdown(overall, by_year)

from collections import defaultdict
from pathlib import Path

from pydantic import BaseModel

from aoc_agent.benchmark.results import BenchmarkResult, load_all_results


class ModelStats(BaseModel):
    model: str
    days_run: int
    part1_correct: int
    part2_correct: int
    avg_score: float
    avg_tokens: int
    avg_duration: float


def _compute_stats(model: str, results: list[BenchmarkResult]) -> ModelStats:
    days_run = len(results)
    part1_correct = sum(1 for r in results if r.part1_correct is True)
    part2_correct = sum(1 for r in results if r.part2_correct is True)
    total_correct = part1_correct + part2_correct
    avg_score = (total_correct / (days_run * 2)) * 100 if days_run > 0 else 0.0
    total_tokens = sum(r.input_tokens + r.output_tokens for r in results)
    avg_tokens = total_tokens // days_run if days_run > 0 else 0
    total_duration = sum(r.duration_seconds for r in results)
    avg_duration = total_duration / days_run if days_run > 0 else 0.0
    return ModelStats(
        model=model,
        days_run=days_run,
        part1_correct=part1_correct,
        part2_correct=part2_correct,
        avg_score=avg_score,
        avg_tokens=avg_tokens,
        avg_duration=avg_duration,
    )


def aggregate_by_model(results: list[BenchmarkResult]) -> list[ModelStats]:
    by_model: dict[str, list[BenchmarkResult]] = defaultdict(list)
    for r in results:
        by_model[r.model].append(r)
    stats = [_compute_stats(model, model_results) for model, model_results in by_model.items()]
    return sorted(stats, key=lambda s: (-s.avg_score, s.model))


def aggregate_by_model_year(results: list[BenchmarkResult]) -> dict[int, list[ModelStats]]:
    by_year_model: dict[int, dict[str, list[BenchmarkResult]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for r in results:
        by_year_model[r.year][r.model].append(r)
    out: dict[int, list[ModelStats]] = {}
    for year, by_model in sorted(by_year_model.items()):
        stats = [_compute_stats(model, model_results) for model, model_results in by_model.items()]
        out[year] = sorted(stats, key=lambda s: (-s.avg_score, s.model))
    return out


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
            f"{s.avg_duration:.1f}s",
        ]
    )
    return "| " + " | ".join(parts) + " |"


def _render_table(stats: list[ModelStats], include_days: bool) -> str:
    if include_days:
        header = "| Rank | Model | Days | Part 1 | Part 2 | Score | Avg Tokens | Avg Duration |"
        separator = "|------|-------|------|--------|--------|-------|------------|--------------|"
    else:
        header = "| Rank | Model | Part 1 | Part 2 | Score | Avg Tokens | Avg Duration |"
        separator = "|------|-------|--------|--------|-------|------------|--------------|"
    lines = [header, separator]
    for rank, s in enumerate(stats, 1):
        lines.append(_format_table_row(rank, s, include_days))
    return "\n".join(lines)


def render_markdown(overall: list[ModelStats], by_year: dict[int, list[ModelStats]]) -> str:
    sections = ["# Benchmark Results", "", "## Overall", ""]
    sections.append("Models ranked by average score across all attempted days.")
    sections.append("")
    sections.append(_render_table(overall, include_days=True))
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
    overall = aggregate_by_model(results)
    by_year = aggregate_by_model_year(results)
    return render_markdown(overall, by_year)

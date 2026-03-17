from collections import defaultdict
from pathlib import Path

from pydantic import BaseModel
from tabulate import tabulate

from aoc_agent.benchmark.results import BenchmarkResult, load_all_results
from aoc_agent.core.constants import OutputMode


def _display_name(result: BenchmarkResult) -> str:
    flags: list[str] = []
    if result.output_mode != OutputMode.TOOL:
        flags.append(result.output_mode.value)
    if result.disable_tool_choice:
        flags.append("no-tool-choice")
    if flags:
        return f"{result.model} ({', '.join(flags)})"
    return result.model


class ModelStats(BaseModel):
    model: str
    days_run: int
    part1_correct: int
    part2_correct: int
    avg_score: float
    avg_duration: float


def _compute_stats(
    model: str,
    results: list[BenchmarkResult],
) -> ModelStats:
    days_run = len(results)
    part1_correct = sum(1 for r in results if r.part1_correct is True)
    part2_correct = sum(1 for r in results if r.part2_correct is True)
    total_correct = part1_correct + part2_correct
    avg_score = (total_correct / (days_run * 2)) * 100 if days_run > 0 else 0.0
    total_duration = sum(r.duration_seconds for r in results)
    avg_duration = total_duration / days_run if days_run > 0 else 0.0
    return ModelStats(
        model=model,
        days_run=days_run,
        part1_correct=part1_correct,
        part2_correct=part2_correct,
        avg_score=avg_score,
        avg_duration=avg_duration,
    )


def aggregate_by_model(results: list[BenchmarkResult]) -> list[ModelStats]:
    by_display: dict[str, list[BenchmarkResult]] = defaultdict(list)
    for r in results:
        by_display[_display_name(r)].append(r)
    stats = [
        _compute_stats(display, model_results) for display, model_results in by_display.items()
    ]
    return sorted(stats, key=lambda s: (-s.avg_score, s.model))


def aggregate_by_model_year(results: list[BenchmarkResult]) -> dict[int, list[ModelStats]]:
    by_year_display: dict[int, dict[str, list[BenchmarkResult]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for r in results:
        by_year_display[r.year][_display_name(r)].append(r)
    out: dict[int, list[ModelStats]] = {}
    for year, by_display in sorted(by_year_display.items()):
        stats = [
            _compute_stats(display, model_results) for display, model_results in by_display.items()
        ]
        out[year] = sorted(stats, key=lambda s: (-s.avg_score, s.model))
    return out


def _render_table(stats: list[ModelStats], include_days: bool) -> str:
    rank = 1
    rows: list[list[str]] = []
    for i, s in enumerate(stats):
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
                f"{s.avg_duration:.1f}s",
            ]
        )
        rows.append(parts)
    headers = (
        ["Rank", "Model", "Days", "Part 1", "Part 2", "Score", "Avg Duration"]
        if include_days
        else ["Rank", "Model", "Part 1", "Part 2", "Score", "Avg Duration"]
    )
    return tabulate(rows, headers=headers, tablefmt="github")


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
    if not results:
        raise ValueError("No results found")
    overall = aggregate_by_model(results)
    by_year = aggregate_by_model_year(results)
    return render_markdown(overall, by_year)

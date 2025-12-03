from pathlib import Path

from aoc_agent.adapters.aoc.models import AOCData, ProblemHTML


class FileCache:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_paths(self, year: int, day: int) -> tuple[Path, Path, Path, Path]:
        year_dir = self.cache_dir / str(year)
        year_dir.mkdir(exist_ok=True)
        unsolved_path = year_dir / f"day_{day}.unsolved.html"
        part1_path = year_dir / f"day_{day}.part1_solved.html"
        part2_path = year_dir / f"day_{day}.part2_solved.html"
        input_path = year_dir / f"day_{day}.input.txt"
        return unsolved_path, part1_path, part2_path, input_path

    def get(self, year: int, day: int) -> AOCData | None:
        unsolved_path, part1_path, part2_path, input_path = self._get_paths(year, day)
        if not unsolved_path.exists() or not input_path.exists():
            return None

        unsolved_html = unsolved_path.read_text()
        part1_solved_html = part1_path.read_text() if part1_path.exists() else None
        part2_solved_html = part2_path.read_text() if part2_path.exists() else None
        input_content = input_path.read_text()

        return AOCData(
            problem_html=ProblemHTML(
                unsolved_html=unsolved_html,
                part1_solved_html=part1_solved_html,
                part2_solved_html=part2_solved_html,
            ),
            input_content=input_content,
        )

    def store(self, year: int, day: int, data: AOCData) -> None:
        unsolved_path, part1_path, part2_path, input_path = self._get_paths(year, day)
        unsolved_path.write_text(data.problem_html.unsolved_html)
        input_path.write_text(data.input_content)

        if data.problem_html.part1_solved_html:
            part1_path.write_text(data.problem_html.part1_solved_html)
        if data.problem_html.part2_solved_html:
            part2_path.write_text(data.problem_html.part2_solved_html)

    def exists(self, year: int, day: int) -> bool:
        unsolved_path, _, _, input_path = self._get_paths(year, day)
        return unsolved_path.exists() and input_path.exists()

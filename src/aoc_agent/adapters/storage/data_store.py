from functools import lru_cache
from pathlib import Path

from bs4 import BeautifulSoup

from aoc_agent.adapters.aoc.models import AOCData, ProblemHTML
from aoc_agent.core.models import Answers


@lru_cache(maxsize=1)
def get_data_store() -> "AOCDataStore":
    return AOCDataStore(Path("cache"))


class AOCDataStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _get_paths(self, year: int, day: int) -> tuple[Path, Path, Path, Path]:
        year_dir = self.data_dir / str(year)
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

    def _extract_answer_from_html(self, html: str, article_index: int) -> int | str | None:
        soup = BeautifulSoup(html, "html.parser")
        articles = soup.find_all("article", class_="day-desc")
        if len(articles) <= article_index:
            return None

        answer_tag = articles[article_index].find_next_sibling("p")
        if not answer_tag or "Your puzzle answer was" not in str(answer_tag):
            return None

        code_tag = answer_tag.find("code")
        if not code_tag:
            return None

        text = code_tag.get_text()
        try:
            return int(text)
        except ValueError:
            return text

    def _extract_answers(self, part1_html: str | None, part2_html: str | None) -> Answers:
        part1 = self._extract_answer_from_html(part1_html, 0) if part1_html else None
        part2 = self._extract_answer_from_html(part2_html, 1) if part2_html else None
        return Answers(part1=part1, part2=part2)

    def get_answers(self, year: int, day: int) -> Answers:
        data = self.get(year, day)
        if not data:
            return Answers()
        return self._extract_answers(
            data.problem_html.part1_solved_html, data.problem_html.part2_solved_html
        )

import httpx
from bs4 import BeautifulSoup

from aoc_agent.adapters.aoc.models import AOCData


def _fetch_problem_html(year: int, day: int, session_token: str) -> str:
    url = f"https://adventofcode.com/{year}/day/{day}"
    cookies = {"session": session_token}

    with httpx.Client(cookies=cookies, timeout=30.0) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def _fetch_input_content(year: int, day: int, session_token: str) -> str:
    url = f"https://adventofcode.com/{year}/day/{day}/input"
    cookies = {"session": session_token}

    with httpx.Client(cookies=cookies, timeout=30.0) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def _extract_problem_articles(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main")
    if not main:
        articles = soup.find_all("article", class_="day-desc")
        return "\n".join(str(article) for article in articles)
    return str(main)


def fetch_aoc_data(year: int, day: int, session_token: str) -> AOCData:
    problem_html_raw = _fetch_problem_html(year, day, session_token)
    problem_html = _extract_problem_articles(problem_html_raw)
    input_content = _fetch_input_content(year, day, session_token)

    return AOCData(
        problem_html=problem_html,
        input_content=input_content,
    )

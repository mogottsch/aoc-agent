import httpx

from aoc_agent.adapters.aoc.models import AOCData


def fetch_aoc_data(year: int, day: int, session_token: str) -> AOCData:
    base_url = "https://adventofcode.com"
    cookies = {"session": session_token}

    problem_url = f"{base_url}/{year}/day/{day}"
    input_url = f"{base_url}/{year}/day/{day}/input"

    with httpx.Client(cookies=cookies, timeout=30.0) as client:
        problem_response = client.get(problem_url)
        problem_response.raise_for_status()

        input_response = client.get(input_url)
        input_response.raise_for_status()

    return AOCData(
        problem_html=problem_response.text,
        input_content=input_response.text,
    )

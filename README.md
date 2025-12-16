# AOC Agent

An agent that solves Advent of Code problems using PydanticAI and OpenRouter.

## Setup

1. Install dependencies:
```bash
uv sync
```

2. Create a `.env` file with the following variables:
```env
OPENROUTER_API_KEY=your_openrouter_api_key
AOC_SESSION_TOKEN=your_session_token
```

## Getting Your AOC Session Token

1. Go to [Advent of Code](https://adventofcode.com/) and log in
2. Open your browser's developer tools (F12 or right-click → Inspect)
3. Go to the **Application** tab (Chrome) or **Storage** tab (Firefox)
4. In the left sidebar, expand **Cookies** and select `https://adventofcode.com`
5. Find the cookie named `session`
6. Copy the value of the `session` cookie - this is your `AOC_SESSION_TOKEN`

## Usage

Solve a single day:
```bash
uv run aoc-agent solve 2024 1
```

Solve an entire year:
```bash
uv run aoc-agent solve-year 2024
```

Fetch data for a specific day (without solving):
```bash
uv run aoc-agent fetch 2024 1
```

## Logfire

Traces stream to Logfire Cloud once you log in:

```bash
uv run logfire auth
uv run logfire projects new      # or `projects use`
```

After that, every `uv run aoc-agent ...` shows the inline summary and appears in the selected project.

# AOC Agent

An agent that solves Advent of Code problems using PydanticAI with any OpenAI-compatible API (GLM, OpenRouter, OpenAI, etc.).

## Setup

1. Install dependencies:

```bash
uv sync
```

2. Create a `.env` file with the following variables:

```env
API_KEY=your_api_key
API_BASE_URL=your_api_base_url
AOC_SESSION_TOKEN=your_session_token
MODEL=model_name
```

**Examples:**

For OpenRouter:
```env
API_KEY=your_openrouter_api_key
API_BASE_URL=https://openrouter.ai/api/v1
MODEL=google/gemini-3-pro-preview
AOC_SESSION_TOKEN=your_session_token
```

Note: `API_BASE_URL` is optional. If not provided, it defaults to OpenAI's base URL. All providers use the OpenAI-compatible API format.

## Getting Your AOC Session Token

1. Go to [Advent of Code](https://adventofcode.com/) and log in
2. Open your browser's developer tools (F12 or right-click → Inspect)
3. Go to the **Application** tab (Chrome) or **Storage** tab (Firefox)
4. In the left sidebar, expand **Cookies** and select `https://adventofcode.com`
5. Find the cookie named `session`
6. Copy the value of the `session` cookie - this is your `AOC_SESSION_TOKEN`

## Usage

Solve a single day (fetches from AOC if not cached, skips if already solved):

```bash
uv run aoc-agent solve 2024 1
```

Solve an entire year:

```bash
uv run aoc-agent solve 2024
```

Test a day using only cached data (offline mode, fails if data not in cache):

```bash
uv run aoc-agent test 2024 1
```

Test an entire year:

```bash
uv run aoc-agent test 2024
```

**Commands:**
- `solve`: Fetches data from AOC website if not in cache, skips days that are already fully solved
- `test`: Offline-only mode, uses cached data only. Useful for testing different models without network calls. Fails if data is not in cache.
- `benchmark`: Run benchmarks across multiple models. See `benchmark.example.yaml` for config format.

```bash
uv run aoc-agent benchmark --config benchmark.yaml
uv run aoc-agent benchmark --config benchmark.yaml --force  # re-run all, ignore existing
```

## Logfire

Traces stream to Logfire Cloud once you log in:

```bash
uv run logfire auth
uv run logfire projects new      # or `projects use`
```

After that, every `uv run aoc-agent ...` shows the inline summary and appears in the selected project.

## Development

Install git hooks:
```bash
uv sync --group dev
uv run pre-commit install
```

Run all hooks:
```bash
uv run pre-commit run -a
```

Run lint:
```bash
uv run ruff check .
```

Run tests:
```bash
uv run pytest -q
```

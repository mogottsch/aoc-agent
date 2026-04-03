# RL / Prime quickstart

This repo has an early offline RL-style environment for Advent of Code plus two practical hosted commands:

- `aoc-agent prime-eval` — run a bounded evaluation on the offline AoC dataset
- `aoc-agent prime-rollout` — generate hosted rollouts over the offline AoC dataset

Right now this is best treated as an experimentation harness, not a full training pipeline.

## What exists today

The current RL path is:

1. Read cached AoC tasks from `cache/`
2. Build an offline dataset
3. Run Prime-hosted evals or rollouts with tool access:
   - `get_aoc_problem_description`
   - `execute_python`
   - `submit_answer`
4. Save outputs under a results directory

## Prerequisites

From the repo root:

```bash
uv sync --group dev --group rl
```

Create a repo-local `.env` file with at least:

```env
PRIME_API_KEY=your_prime_key
AOC_OFFLINE_ONLY=true
```

Notes:

- `AOC_OFFLINE_ONLY=true` means the RL/eval flow only uses cached AoC data.
- You do not need `AOC_SESSION_TOKEN` for this offline-only RL flow.
- `prime-eval` and `prime-rollout` will load `PRIME_API_KEY` from `.env` automatically.

## Required local data

You need:

- `cache/` populated with Advent of Code inputs/problem HTML

The dataset builder scans cached years under `cache/<year>/` and can optionally be restricted with `--year`.

## Sanity check the CLI

```bash
uv run aoc-agent --help
uv run aoc-agent prime-eval --help
uv run aoc-agent prime-rollout --help
```

## Recommended first run

Use one year only so the blast radius stays small.

A good first eval shape is:

```bash
uv run aoc-agent prime-eval \
  --model meta-llama/Llama-3.2-3B-Instruct \
  --year 2022 \
  --num-examples 16 \
  --rollouts-per-example 1 \
  --max-concurrent 1 \
  --max-tokens 768 \
  --output results/prime-eval-llama32-3b-2022
```

Why this shape:

- `--year 2022` keeps it bounded
- `--num-examples 16` is enough for a quick vibe check
- `--max-concurrent 1` is safer while hosted reliability is still a bit shaky

## Run a rollout pass

```bash
uv run aoc-agent prime-rollout \
  --model meta-llama/Llama-3.2-3B-Instruct \
  --year 2022 \
  --max-concurrent 1 \
  --max-tokens 768 \
  --output results/prime-rollout-llama32-3b-2022
```

## Output format

Even if the output path looks like a file-ish name, Prime writes a directory.

Example:

```text
results/prime-eval-llama32-3b-2022/
  metadata.json
  results.jsonl
```

Same idea for rollouts.

## How to inspect results

Open the generated files directly:

```bash
cat results/prime-eval-llama32-3b-2022/metadata.json
cat results/prime-eval-llama32-3b-2022/results.jsonl
```

Useful things to look for:

- average reward
- error rate
- whether any tool calls look sane
- whether the model is actually serving successfully

## Known caveats

Current status is a bit scuffed but usable:

- some Prime-listed models do not actually serve correctly on this path
- model naming / serving mismatches were a real issue during bring-up
- `meta-llama/Llama-3.2-3B-Instruct` is the safest currently tested starting point
- keep concurrency low for first runs

## If you want a tiny smoke test

```bash
uv run aoc-agent prime-eval \
  --model meta-llama/Llama-3.2-3B-Instruct \
  --year 2022 \
  --num-examples 2 \
  --rollouts-per-example 1 \
  --max-concurrent 1 \
  --max-tokens 256 \
  --output results/prime-eval-smoke
```

## Rough mental model

- `cache/` = offline AoC task source
- `prime-eval` = score hosted runs on a bounded dataset slice
- `prime-rollout` = generate trajectories / outputs over the dataset slice

If you want, the next useful step is probably one of:

1. add a tiny `smoke` command
2. add a script/Make target for the recommended eval
3. normalize model IDs before Prime runs

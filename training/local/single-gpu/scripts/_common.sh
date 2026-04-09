#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
WORK_DIR="$ROOT_DIR/training/local/single-gpu"
ENV_FILE="$WORK_DIR/scripts/local.env"

require_env_file() {
  if [ ! -f "$ENV_FILE" ]; then
    printf 'missing %s\n' "$ENV_FILE" >&2
    exit 1
  fi
}

load_env() {
  require_env_file
  . "$ENV_FILE"
}

require_vars() {
  for name in "$@"; do
    if [ -z "${!name:-}" ]; then
      printf 'missing required variable: %s\n' "$name" >&2
      exit 1
    fi
  done
}

run_name() {
  printf '%s' "${RUN_NAME:-aoc-qwen3.5-4b-single-gpu}"
}

run_dir() {
  printf '%s/runs/%s' "$ROOT_DIR" "$(run_name)"
}

generated_config_dir() {
  printf '%s/generated' "$WORK_DIR"
}

#!/usr/bin/env bash
set -euo pipefail

. "$(git rev-parse --show-toplevel)/training/local/single-gpu/scripts/_common.sh"
load_env
require_vars WANDB_API_KEY HF_TOKEN VLLM_API_KEY NEXTCLOUD_URL NEXTCLOUD_USERNAME NEXTCLOUD_APP_PASSWORD RCLONE_REMOTE_NAME NEXTCLOUD_RUNS_DIR

for tool in git uv tmux rclone; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf 'missing required tool: %s\n' "$tool" >&2
    exit 1
  fi
done

"$WORK_DIR/scripts/15_generate_runtime_configs.sh"

for path in "$WORK_DIR/generated/train.toml" "$WORK_DIR/generated/orch.toml" "$WORK_DIR/generated/infer.toml"; do
  if [ ! -f "$path" ]; then
    printf 'missing generated config: %s\n' "$path" >&2
    exit 1
  fi
done

printf 'preflight ok\n'

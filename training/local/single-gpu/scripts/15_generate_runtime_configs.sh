#!/usr/bin/env bash
set -euo pipefail

. "$(git rev-parse --show-toplevel)/training/local/single-gpu/scripts/_common.sh"
load_env

GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.4}"
INFERENCE_PORT="${INFERENCE_PORT:-8000}"
RUN_OUTPUT_DIR="$(run_dir)"
GEN_DIR="$(generated_config_dir)"

mkdir -p "$GEN_DIR"

render() {
  local input="$1"
  local output="$2"
  sed \
    -e "s|__RUN_OUTPUT_DIR__|$RUN_OUTPUT_DIR|g" \
    -e "s|__GPU_MEMORY_UTILIZATION__|$GPU_MEMORY_UTILIZATION|g" \
    -e "s|__INFERENCE_PORT__|$INFERENCE_PORT|g" \
    "$input" > "$output"
}

render "$WORK_DIR/configs/train.template.toml" "$GEN_DIR/train.toml"
render "$WORK_DIR/configs/orch.template.toml" "$GEN_DIR/orch.toml"
render "$WORK_DIR/configs/infer.template.toml" "$GEN_DIR/infer.toml"

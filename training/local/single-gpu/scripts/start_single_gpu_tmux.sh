#!/usr/bin/env bash
set -euo pipefail

. "$(git rev-parse --show-toplevel)/training/local/single-gpu/scripts/common.sh"
load_env
require_vars VLLM_API_KEY

"$WORK_DIR/scripts/generate_configs.sh"

SESSION_NAME="${TMUX_SESSION_NAME:-aoc-single-gpu}"
GEN_DIR="$(generated_config_dir)"
TRAIN_CONFIG="$GEN_DIR/train.toml"
ORCH_CONFIG="$GEN_DIR/orch.toml"
INFER_CONFIG="$GEN_DIR/infer.toml"

if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
  tmux kill-session -t "$SESSION_NAME"
fi

tmux new-session -d -s "$SESSION_NAME" -c "$ROOT_DIR"
tmux rename-window -t "$SESSION_NAME:0" inference
tmux send-keys -t "$SESSION_NAME:0" "source \"$ENV_FILE\" && CUDA_VISIBLE_DEVICES=0 uv run inference @ \"$INFER_CONFIG\"" C-m
tmux new-window -t "$SESSION_NAME" -n orchestrator -c "$ROOT_DIR"
tmux send-keys -t "$SESSION_NAME:1" "source \"$ENV_FILE\" && uv run orchestrator @ \"$ORCH_CONFIG\"" C-m
tmux new-window -t "$SESSION_NAME" -n trainer -c "$ROOT_DIR"
tmux send-keys -t "$SESSION_NAME:2" "source \"$ENV_FILE\" && CUDA_VISIBLE_DEVICES=0 uv run trainer @ \"$TRAIN_CONFIG\"" C-m

tmux select-window -t "$SESSION_NAME:0"
tmux attach-session -t "$SESSION_NAME"

#!/usr/bin/env bash
set -euo pipefail

. "$(git rev-parse --show-toplevel)/training/local/single-gpu/scripts/common.sh"

apt_get() {
  if [ "$(id -u)" -eq 0 ]; then
    apt-get "$@"
    return
  fi

  if command -v sudo >/dev/null 2>&1; then
    sudo apt-get "$@"
    return
  fi

  printf 'apt-get available but sudo is missing and current user is not root\n' >&2
  exit 1
}

if command -v apt-get >/dev/null 2>&1; then
  apt_get update
  apt_get install -y git curl tmux unzip rclone rsync
fi

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

if [ -f "$HOME/.cargo/env" ]; then
  . "$HOME/.cargo/env"
fi

uv sync --group rl
uv run prime env install aoc-prime-env -p "$ROOT_DIR/environments"

#!/usr/bin/env bash
set -euo pipefail

. "$(git rev-parse --show-toplevel)/training/local/single-gpu/scripts/common.sh"
load_env

require_vars RCLONE_REMOTE_NAME NEXTCLOUD_RUNS_DIR

LOCAL_RUN_DIR="$(run_dir)"
REMOTE_RUN_DIR="${RCLONE_REMOTE_NAME}:${NEXTCLOUD_RUNS_DIR%/}/$(run_name)"

mkdir -p "$LOCAL_RUN_DIR"
rclone copy "$REMOTE_RUN_DIR" "$LOCAL_RUN_DIR"

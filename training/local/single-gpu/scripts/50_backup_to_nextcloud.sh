#!/usr/bin/env bash
set -euo pipefail

. "$(git rev-parse --show-toplevel)/training/local/single-gpu/scripts/_common.sh"
load_env

require_vars RCLONE_REMOTE_NAME NEXTCLOUD_RUNS_DIR

LOCAL_RUN_DIR="$(run_dir)"
REMOTE_RUN_DIR="${RCLONE_REMOTE_NAME}:${NEXTCLOUD_RUNS_DIR%/}/$(run_name)"

rclone copy "$LOCAL_RUN_DIR" "$REMOTE_RUN_DIR" --transfers 2 --checkers 4 --webdav-nextcloud-chunk-size 64M

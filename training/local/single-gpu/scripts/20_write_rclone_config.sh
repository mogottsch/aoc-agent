#!/usr/bin/env bash
set -euo pipefail

. "$(git rev-parse --show-toplevel)/training/local/single-gpu/scripts/_common.sh"
load_env

: "${NEXTCLOUD_URL:?}"
: "${NEXTCLOUD_USERNAME:?}"
: "${NEXTCLOUD_APP_PASSWORD:?}"
: "${RCLONE_REMOTE_NAME:?}"

mkdir -p "$HOME/.config/rclone"

PASSWORD="$(rclone obscure "$NEXTCLOUD_APP_PASSWORD")"

cat > "$HOME/.config/rclone/rclone.conf" <<EOF
[${RCLONE_REMOTE_NAME}]
type = webdav
url = ${NEXTCLOUD_URL%/}/remote.php/dav/files/${NEXTCLOUD_USERNAME}/
vendor = nextcloud
user = ${NEXTCLOUD_USERNAME}
pass = ${PASSWORD}
EOF

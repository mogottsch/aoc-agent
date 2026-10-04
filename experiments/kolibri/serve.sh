#!/usr/bin/env bash
# Default: print pinned container plan; --execute is a separate opt-in.
set -euo pipefail
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3 "$here/serve.py" "$@"

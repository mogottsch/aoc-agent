#!/usr/bin/env bash
# Default: offline preflight, not inference.
set -euo pipefail
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
root=$(cd -- "$here/../.." && pwd)
exec "$root/.venv/bin/python" "$here/run.py" "$@"

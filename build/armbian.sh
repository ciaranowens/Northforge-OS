#!/usr/bin/env bash
set -euo pipefail
forge_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3 "$forge_dir/forge.py" "$@"

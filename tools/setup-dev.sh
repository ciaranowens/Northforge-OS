#!/usr/bin/env bash
# Prepare tools only; image builds and QEMU runs are explicit separate commands.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo"
docker_command=(env -u DOCKER_HOST -u DOCKER_CONTEXT -u DOCKER_TLS
    -u DOCKER_TLS_VERIFY -u DOCKER_CERT_PATH docker --host=unix:///var/run/docker.sock)
"${docker_command[@]}" info --format '{{.ServerVersion}}'
build_args=(build -f build/Containerfile.tools --tag northforge-tools:dev)
if [[ -n ${CODEX_PROXY_CERT:-} ]]; then
    [[ -r $CODEX_PROXY_CERT ]] || { echo 'Configured proxy CA is unreadable.' >&2; exit 1; }
    build_args+=(--secret "id=proxy_ca,src=$CODEX_PROXY_CERT")
fi
"${docker_command[@]}" "${build_args[@]}" .
python3 tools/check.py

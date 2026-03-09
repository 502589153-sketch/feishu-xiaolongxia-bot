#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="${ROOT_DIR}/OpenClaw-master/Build_Release"
ENV_PREFIX="${HOME}/.micromamba/envs/openclaw"

if [[ ! -x "${RUN_DIR}/openclaw" ]]; then
  echo "openclaw binary not found. Run scripts/build_openclaw.sh first."
  exit 1
fi

cd "${RUN_DIR}"
export DYLD_LIBRARY_PATH="${ENV_PREFIX}/lib:${DYLD_LIBRARY_PATH:-}"

./openclaw

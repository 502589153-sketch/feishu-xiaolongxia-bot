#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="${ROOT_DIR}/OpenClaw-master"
ENV_PREFIX="${HOME}/.micromamba/envs/openclaw"
MAMBA_BIN="${HOME}/.local/bin/micromamba"

if [[ ! -x "${MAMBA_BIN}" ]]; then
  echo "micromamba not found at ${MAMBA_BIN}"
  exit 1
fi

if [[ ! -d "${PROJECT_DIR}" ]]; then
  echo "OpenClaw source not found at ${PROJECT_DIR}"
  exit 1
fi

cd "${PROJECT_DIR}"

"${MAMBA_BIN}" run -p "${ENV_PREFIX}" cmake -S . -B build \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PREFIX_PATH="${ENV_PREFIX}" \
  -DCMAKE_EXE_LINKER_FLAGS="-L${ENV_PREFIX}/lib" \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5

"${MAMBA_BIN}" run -p "${ENV_PREFIX}" cmake --build build -j8

echo "Build done: ${PROJECT_DIR}/Build_Release/openclaw"

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_SCRIPT="${ROOT_DIR}/scripts/run_openclaw.sh"
NOTIFY_SCRIPT="${ROOT_DIR}/scripts/feishu_notify.sh"
ENV_FILE="${ROOT_DIR}/.env.feishu"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

SCENARIO="${FEISHU_NOTIFY_SCENARIO:-openclaw_runtime}"

notify_best_effort() {
  local text="$1"
  if [[ -x "${NOTIFY_SCRIPT}" ]]; then
    "${NOTIFY_SCRIPT}" send "[${SCENARIO}] ${text}" >/dev/null 2>&1 || true
  fi
}

notify_best_effort "OpenClaw launch started on $(hostname)"

set +e
"${RUN_SCRIPT}"
rc=$?
set -e

if [[ $rc -eq 0 ]]; then
  notify_best_effort "OpenClaw exited normally on $(hostname)"
else
  notify_best_effort "OpenClaw exited with code ${rc} on $(hostname)"
fi

exit $rc

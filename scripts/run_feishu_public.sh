#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env.feishu"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

BOT_PORT="${FEISHU_BOT_PORT:-9000}"
SUBDOMAIN="${FEISHU_TUNNEL_SUBDOMAIN:-}"

start_bot_if_needed() {
  if lsof -nP -iTCP:"${BOT_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Feishu bot already listening on :${BOT_PORT}"
    return
  fi
  echo "Starting Feishu bot on :${BOT_PORT}"
  nohup "${ROOT_DIR}/scripts/run_feishu_bot.sh" >/tmp/feishu_bot_server.log 2>&1 &
  sleep 1
}

start_bot_if_needed

if [[ -n "${SUBDOMAIN}" ]]; then
  TUNNEL_ARG="${SUBDOMAIN}:80:localhost:${BOT_PORT}"
  echo "Requesting preferred subdomain: ${SUBDOMAIN}"
else
  TUNNEL_ARG="80:localhost:${BOT_PORT}"
fi

echo "Starting localhost.run tunnel..."
echo "When you see an https://*.lhr.life URL below, use:"
echo "  <URL>/feishu/callback"

exec ssh \
  -o StrictHostKeyChecking=no \
  -o ServerAliveInterval=30 \
  -R "${TUNNEL_ARG}" \
  nokey@localhost.run

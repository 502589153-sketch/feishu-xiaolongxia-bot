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

require_env() {
  local key="$1"
  if [[ -z "${!key:-}" ]]; then
    echo "Missing required env: ${key}" >&2
    exit 1
  fi
}

fetch_token() {
  require_env FEISHU_APP_ID
  require_env FEISHU_APP_SECRET

  local auth_resp
  auth_resp="$(curl -sS -X POST "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/" \
    -H "Content-Type: application/json; charset=utf-8" \
    -d "{\"app_id\":\"${FEISHU_APP_ID}\",\"app_secret\":\"${FEISHU_APP_SECRET}\"}")"

  local code
  code="$(echo "${auth_resp}" | jq -r '.code')"
  if [[ "${code}" != "0" ]]; then
    echo "Feishu auth failed: ${auth_resp}" >&2
    exit 1
  fi

  echo "${auth_resp}" | jq -r '.tenant_access_token'
}

send_text() {
  local receive_id_type="$1"
  local receive_id="$2"
  local text="$3"

  local token
  token="$(fetch_token)"

  local payload
  payload="$(jq -nc --arg rid "${receive_id}" --arg text "${text}" '{receive_id:$rid,msg_type:"text",content:({text:$text}|tojson)}')"

  local send_resp
  send_resp="$(curl -sS -X POST "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=${receive_id_type}" \
    -H "Authorization: Bearer ${token}" \
    -H "Content-Type: application/json; charset=utf-8" \
    -d "${payload}")"

  local code
  code="$(echo "${send_resp}" | jq -r '.code')"
  if [[ "${code}" != "0" ]]; then
    echo "Feishu send failed: ${send_resp}" >&2
    exit 1
  fi

  echo "${send_resp}" | jq -r '.data.message_id'
}

usage() {
  cat <<'USAGE'
Usage:
  scripts/feishu_notify.sh auth-test
  scripts/feishu_notify.sh send <message>
  scripts/feishu_notify.sh send-to <receive_id_type> <receive_id> <message>

Env from .env.feishu (or process env):
  FEISHU_APP_ID
  FEISHU_APP_SECRET
  FEISHU_RECEIVE_ID_TYPE   # e.g. chat_id / user_id / open_id
  FEISHU_RECEIVE_ID
USAGE
}

main() {
  local cmd="${1:-}"
  case "${cmd}" in
    auth-test)
      local token
      token="$(fetch_token)"
      echo "Feishu auth ok. token_prefix=${token:0:12}"
      ;;
    send)
      shift
      local msg="${1:-}"
      if [[ -z "${msg}" ]]; then
        usage
        exit 1
      fi
      require_env FEISHU_RECEIVE_ID_TYPE
      require_env FEISHU_RECEIVE_ID
      send_text "${FEISHU_RECEIVE_ID_TYPE}" "${FEISHU_RECEIVE_ID}" "${msg}" >/dev/null
      echo "Feishu message sent"
      ;;
    send-to)
      shift
      local receive_id_type="${1:-}"
      local receive_id="${2:-}"
      shift 2 || true
      local msg="${*:-}"
      if [[ -z "${receive_id_type}" || -z "${receive_id}" || -z "${msg}" ]]; then
        usage
        exit 1
      fi
      send_text "${receive_id_type}" "${receive_id}" "${msg}" >/dev/null
      echo "Feishu message sent"
      ;;
    *)
      usage
      exit 1
      ;;
  esac
}

main "$@"

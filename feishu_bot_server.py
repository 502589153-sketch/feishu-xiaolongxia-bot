#!/usr/bin/env python3
import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT_DIR / ".env.feishu"


def load_env_file() -> None:
    if not ENV_FILE.exists():
        return
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ[key] = value


load_env_file()

APP_ID = os.getenv("FEISHU_APP_ID", "")
APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
VERIFY_TOKEN = os.getenv("FEISHU_APP_VERIFICATION_TOKEN", "")
REPLY_PREFIX = os.getenv("FEISHU_BOT_REPLY_PREFIX", "龙虾已收到：")
HOST = os.getenv("FEISHU_BOT_HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", os.getenv("FEISHU_BOT_PORT", "9000")))

# Bot behavior: rule | openai | auto
BOT_MODE = os.getenv("FEISHU_BOT_MODE", "auto").strip().lower()
CONTEXT_TURNS = int(os.getenv("FEISHU_CONTEXT_TURNS", "8"))
SYSTEM_PROMPT = os.getenv(
    "FEISHU_BOT_SYSTEM_PROMPT",
    "你是飞书里的中文助手“龙虾”。回答要直接、清晰、实用，避免废话。",
)

# OpenAI-compatible options
OPENAI_API_KEY = os.getenv("FEISHU_OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.getenv("FEISHU_OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_MODEL = os.getenv("FEISHU_OPENAI_MODEL", "gpt-4o-mini").strip()
OPENAI_TIMEOUT_SEC = int(os.getenv("FEISHU_OPENAI_TIMEOUT_SEC", "25"))
STATE_FILE = os.getenv("FEISHU_STATE_FILE", "").strip()

_token_lock = threading.Lock()
_token_cache = {"value": "", "expires_at": 0.0}

_seen_lock = threading.Lock()
_seen_ids = set()
_seen_queue = deque(maxlen=1000)

_chat_lock = threading.Lock()
_chat_histories: dict[str, deque[dict[str, str]]] = {}


def _save_state_locked() -> None:
    if not STATE_FILE:
        return
    path = Path(STATE_FILE)
    if not path.is_absolute():
        path = ROOT_DIR / path
    path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {chat_id: list(history) for chat_id, history in _chat_histories.items()}
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps({"chat_histories": snapshot}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def load_state_file() -> None:
    if not STATE_FILE:
        return
    path = Path(STATE_FILE)
    if not path.is_absolute():
        path = ROOT_DIR / path
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[warn] failed to load state file: {e}")
        return

    source = payload.get("chat_histories", {})
    if not isinstance(source, dict):
        return

    with _chat_lock:
        _chat_histories.clear()
        maxlen = max(2, CONTEXT_TURNS * 2)
        for chat_id, rows in source.items():
            if not isinstance(chat_id, str) or not isinstance(rows, list):
                continue
            history = deque(maxlen=maxlen)
            for row in rows[-maxlen:]:
                if not isinstance(row, dict):
                    continue
                role = str(row.get("role", "")).strip()
                content = str(row.get("content", "")).strip()
                if role in {"user", "assistant", "system"} and content:
                    history.append({"role": role, "content": content})
            if history:
                _chat_histories[chat_id] = history


def http_post_json(url: str, payload: dict, headers: dict, timeout: int = 15) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url=url, data=body, method="POST")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    for k, v in headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8"))


def fetch_tenant_token() -> str:
    now = time.time()
    with _token_lock:
        if _token_cache["value"] and _token_cache["expires_at"] > now + 30:
            return _token_cache["value"]

    if not APP_ID or not APP_SECRET:
        raise RuntimeError("Missing FEISHU_APP_ID or FEISHU_APP_SECRET")

    resp = http_post_json(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/",
        {"app_id": APP_ID, "app_secret": APP_SECRET},
        {},
    )
    if str(resp.get("code")) != "0":
        raise RuntimeError(f"Feishu auth failed: {resp}")

    token = resp["tenant_access_token"]
    expires_in = int(resp.get("expire", 7200))
    with _token_lock:
        _token_cache["value"] = token
        _token_cache["expires_at"] = time.time() + expires_in
    return token


def send_text_to_chat(chat_id: str, text: str) -> None:
    token = fetch_tenant_token()
    payload = {
        "receive_id": chat_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}, ensure_ascii=False),
    }
    resp = http_post_json(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        payload,
        {"Authorization": f"Bearer {token}"},
    )
    if str(resp.get("code")) != "0":
        raise RuntimeError(f"Feishu send failed: {resp}")


def parse_text_content(raw_content: str) -> str:
    try:
        parsed = json.loads(raw_content)
        return str(parsed.get("text", "")).strip()
    except Exception:
        return raw_content.strip()


def mark_seen(message_id: str) -> bool:
    with _seen_lock:
        if message_id in _seen_ids:
            return False
        _seen_ids.add(message_id)
        _seen_queue.append(message_id)
        while len(_seen_ids) > _seen_queue.maxlen:
            oldest = _seen_queue.popleft()
            _seen_ids.discard(oldest)
        return True


def get_history(chat_id: str) -> list[dict[str, str]]:
    with _chat_lock:
        if chat_id not in _chat_histories:
            _chat_histories[chat_id] = deque(maxlen=max(2, CONTEXT_TURNS * 2))
        return list(_chat_histories[chat_id])


def add_history(chat_id: str, role: str, content: str) -> None:
    with _chat_lock:
        if chat_id not in _chat_histories:
            _chat_histories[chat_id] = deque(maxlen=max(2, CONTEXT_TURNS * 2))
        _chat_histories[chat_id].append({"role": role, "content": content})
        _save_state_locked()


def clear_history(chat_id: str) -> None:
    with _chat_lock:
        _chat_histories.pop(chat_id, None)
        _save_state_locked()


def llm_enabled() -> bool:
    return bool(OPENAI_API_KEY)


def openai_chat_reply(chat_id: str, user_text: str) -> str:
    if not llm_enabled():
        raise RuntimeError("LLM key not configured")

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(get_history(chat_id))
    messages.append({"role": "user", "content": user_text})

    payload = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "temperature": 0.7,
    }
    resp = http_post_json(
        f"{OPENAI_BASE_URL}/chat/completions",
        payload,
        {"Authorization": f"Bearer {OPENAI_API_KEY}"},
        timeout=OPENAI_TIMEOUT_SEC,
    )
    choices = resp.get("choices", [])
    if not choices:
        raise RuntimeError(f"No choices in LLM response: {resp}")
    msg = choices[0].get("message", {})
    content = str(msg.get("content", "")).strip()
    if not content:
        raise RuntimeError(f"Empty LLM reply: {resp}")
    return content


def rule_reply(user_text: str) -> str:
    text = user_text.strip()
    lower = text.lower()

    if lower in {"/ping", "ping"}:
        return "pong"
    if lower in {"/help", "help", "帮助"}:
        return (
            "我现在支持:\n"
            "1) 普通问答\n"
            "2) /reset 清空当前会话记忆\n"
            "3) /mode 查看当前对话模式"
        )
    if lower in {"/mode", "mode"}:
        mode = BOT_MODE
        llm = "on" if llm_enabled() else "off"
        return f"当前模式: {mode}, LLM: {llm}, 模型: {OPENAI_MODEL}"
    if lower in {"/reset", "reset"}:
        return "会话记忆已清空。"

    if any(k in lower for k in ["你好", "hi", "hello", "在吗"]):
        return "在，我在这。你直接说需求，我给你结论和操作。"
    if "你是谁" in text or "你能做什么" in text:
        return "我是飞书里的“龙虾”助手，可以答疑、总结、给执行步骤，也可以接入大模型做多轮对话。"
    if "谢谢" in text:
        return "不客气，继续发就行。"

    if not llm_enabled():
        return (
            f"{REPLY_PREFIX} {text}\n"
            "我现在是规则模式，能做基础对话。给我配置 FEISHU_OPENAI_API_KEY 后可切到智能多轮对话。"
        )
    return f"{REPLY_PREFIX} {text}"


def llm_failure_reply(user_text: str, err: Exception) -> str:
    err_text = str(err)
    if "429" in err_text:
        hint = "智能通道暂时不可用（限流或配额不足）。"
    else:
        hint = "智能通道暂时不可用。"
    return f"{hint} 请稍后重试。\n{REPLY_PREFIX} {user_text}"


def build_reply(chat_id: str, user_text: str) -> str:
    lower = user_text.strip().lower()

    if lower in {"/reset", "reset"}:
        clear_history(chat_id)
        return "会话记忆已清空。"
    if lower in {"/mode", "mode"}:
        return rule_reply(user_text)
    if lower in {"/help", "help", "帮助"}:
        return rule_reply(user_text)

    use_llm = BOT_MODE == "openai" or (BOT_MODE == "auto" and llm_enabled())

    if use_llm:
        try:
            assistant = openai_chat_reply(chat_id, user_text)
            add_history(chat_id, "user", user_text)
            add_history(chat_id, "assistant", assistant)
            return assistant
        except Exception as e:
            print(f"[warn] LLM reply failed, fallback to rule mode: {e}")
            fallback = llm_failure_reply(user_text, e)
            add_history(chat_id, "user", user_text)
            add_history(chat_id, "assistant", fallback)
            return fallback

    assistant = rule_reply(user_text)
    add_history(chat_id, "user", user_text)
    add_history(chat_id, "assistant", assistant)
    return assistant


def process_message(chat_id: str, user_text: str) -> None:
    reply_text = build_reply(chat_id, user_text)
    try:
        send_text_to_chat(chat_id, reply_text)
    except urllib.error.HTTPError as e:
        print(f"[warn] reply send http error: {e.code}")
    except Exception as e:
        print(f"[warn] reply send error: {e}")


class FeishuHandler(BaseHTTPRequestHandler):
    def _json(self, status: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[http] {self.address_string()} - {fmt % args}")

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._json(200, {"ok": True})
            return
        self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/feishu/callback":
            self._json(404, {"error": "not_found"})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except Exception:
            self._json(400, {"error": "invalid_json"})
            return

        if VERIFY_TOKEN:
            token_in = body.get("token")
            if token_in and token_in != VERIFY_TOKEN:
                self._json(403, {"error": "invalid_verification_token"})
                return

        if body.get("type") == "url_verification":
            challenge = body.get("challenge", "")
            self._json(200, {"challenge": challenge})
            return

        if "encrypt" in body:
            self._json(
                400,
                {
                    "error": "encrypted_event_not_supported",
                    "hint": "Disable Encrypt Key in Feishu event subscription or extend server to decrypt.",
                },
            )
            return

        header = body.get("header", {})
        event_type = header.get("event_type")
        if event_type != "im.message.receive_v1":
            self._json(200, {"ok": True, "ignored_event_type": event_type})
            return

        event = body.get("event", {})
        message = event.get("message", {})
        sender = event.get("sender", {})
        sender_type = sender.get("sender_type", "")
        message_id = message.get("message_id", "")
        chat_id = message.get("chat_id", "")
        message_type = message.get("message_type", "")

        if not message_id or not chat_id:
            self._json(200, {"ok": True, "ignored": "missing_message_id_or_chat_id"})
            return
        if not mark_seen(message_id):
            self._json(200, {"ok": True, "ignored": "duplicate"})
            return
        if sender_type and sender_type != "user":
            self._json(200, {"ok": True, "ignored": f"sender_type={sender_type}"})
            return
        if message_type != "text":
            self._json(200, {"ok": True, "ignored": f"message_type={message_type}"})
            return

        user_text = parse_text_content(message.get("content", ""))
        if not user_text:
            self._json(200, {"ok": True, "ignored": "empty_text"})
            return

        # Ack callback immediately to avoid Feishu timeout; reply is sent asynchronously.
        threading.Thread(
            target=process_message,
            args=(chat_id, user_text),
            daemon=True,
        ).start()
        self._json(200, {"ok": True, "accepted": True})


def main() -> None:
    if not APP_ID or not APP_SECRET:
        raise SystemExit("Missing FEISHU_APP_ID or FEISHU_APP_SECRET in .env.feishu")
    load_state_file()
    server = ThreadingHTTPServer((HOST, PORT), FeishuHandler)
    print(f"Feishu bot server listening on http://{HOST}:{PORT}")
    print("Callback path: /feishu/callback")
    print("Health path:   /healthz")
    print(f"Mode: {BOT_MODE}, LLM key configured: {'yes' if llm_enabled() else 'no'}")
    if STATE_FILE:
        print(f"State file: {STATE_FILE}")
    server.serve_forever()


if __name__ == "__main__":
    main()

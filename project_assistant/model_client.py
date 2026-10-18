"""Optional Responses streaming adapter using the configured local Codex login.

Only allowlisted OpenBench tools are exposed. Credentials remain in memory and
are removed from returned errors. Standard API deployments use providers.py.
"""
from __future__ import annotations

import http.client
import json
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field

from project_assistant import tool_specs

URL = "https://chatgpt.com/backend-api/codex/responses"
# 這個端點前面的 Cloudflare 會擋 Python-urllib 的 User-Agent（2026-09-23 生圖踩過：403、error code: 1010）
USER_AGENT = "node"
MAX_ROUNDS = 16  # 翻報表一題可能要查十幾次（Codex 時 S06 查了 18 次）；最後一輪只准用查到的回答
LAST_ROUND_NOTE = "（系統附註：查資料的次數到上限了。請用目前查到的內容直接回答；還沒查到的照實說，不要再查。）"
TOKEN_TTL = 300  # pi 給的權杖至少還有 10 分鐘；5 分鐘內重用，不用每一輪都叫一次 pi
QUOTA_HINTS = ("usage limit", "rate limit", "quota", "too many requests")
# 伺服器過載、5xx、連線被切：等一下再送同一個請求（2026-10-14 本機實測碰到 server_is_overloaded；
# Codex CLI 自己會重試，直接呼叫不重試的話，這種一下子的狀況就會整輪改走慢的 Codex）。
# 同一天回歸 S06 查到第 4 輪連續過載 3 次（等 1、3 秒不夠），改走 Codex 從頭再查一次，整題 119 秒
TRANSIENT_HINTS = ("overloaded", "service_unavailable", "server_error", "internal_error", "try again", "temporarily")
RETRY_WAITS = (1.0, 2.0, 4.0, 8.0)
ALLOWED_ITEMS = {"message", "reasoning", "function_call"}


class ModelError(RuntimeError):
    def __init__(self, kind: str, message: str, *, transient: bool = False):
        super().__init__(message)
        self.kind = kind  # quota／auth／unavailable／timeout／bad_response
        self.transient = transient  # 等一下再送一次可能就好


@dataclass
class TurnResult:
    status: str  # ok／quota／lockdown／error
    answer: str = ""
    blocked: str = ""
    error_kind: str = ""
    error: str = ""
    rounds: int = 0
    usage: dict = field(default_factory=dict)
    seconds: float = 0.0
    first_text: float | None = None


_CRED: dict = {}
_CRED_LOCK = threading.Lock()


def _jwt_account_id(token: str) -> str:
    import base64
    parts = token.split(".")
    if len(parts) != 3:
        return "openbench"
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
        auth = claims.get("https://api.openai.com/auth") or {}
        return str(auth.get("chatgpt_account_id") or claims.get("sub") or "openbench")
    except Exception:  # noqa: BLE001
        return "openbench"


def _default_bearer_token() -> str:
    import os
    from pathlib import Path
    env_key = (os.environ.get("OPENBENCH_API_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip()
    if env_key:
        return env_key
    auth_path = Path.home() / ".codex" / "auth.json"
    if auth_path.is_file():
        try:
            data = json.loads(auth_path.read_text(encoding="utf-8"))
            token = ((data.get("tokens") or {}).get("access_token") or data.get("OPENAI_API_KEY") or "").strip()
            if token:
                return token
        except Exception:  # noqa: BLE001
            pass
    raise RuntimeError("Configure OPENBENCH_API_KEY / OPENAI_API_KEY or local CLI authentication.")


def credentials(*, fetch=None, now=time.monotonic) -> tuple[str, str]:
    """(權杖, 帳號識別)；5 分鐘內重用。登入不能用時丟 ModelError("auth")。"""

    with _CRED_LOCK:
        if _CRED and now() - _CRED["at"] < TOKEN_TTL:
            return _CRED["token"], _CRED["account"]
        try:
            token = (fetch or _default_bearer_token)()
            account = _jwt_account_id(token)
        except Exception as exc:  # noqa: BLE001
            raise ModelError("auth", str(exc)) from None
        _CRED.update(token=token, account=account, at=now())
        return token, account


def forget_credentials() -> None:
    with _CRED_LOCK:
        _CRED.clear()


def response_tools(specs=None) -> list[dict]:
    return [{"type": "function", "name": spec["name"], "description": spec["description"],
             "parameters": spec["inputSchema"], "strict": False} for spec in (tool_specs.TOOLS if specs is None else specs)]


def request_body(*, model: str, effort: str, instructions: str, items: list, cache_key: str, tool_specs=None) -> dict:
    return {"model": model, "store": False, "stream": True, "instructions": instructions, "input": items,
            "text": {"verbosity": "low"}, "include": ["reasoning.encrypted_content"], "prompt_cache_key": cache_key,
            "tool_choice": "auto", "parallel_tool_calls": True, "tools": response_tools(tool_specs),
            "reasoning": {"effort": effort}}


def _clean(text, token: str) -> str:
    text = str(text)
    if token:
        text = text.replace(token, "…")
    return text[:400]


def _is_quota(text: str) -> bool:
    low = text.lower()
    return any(hint in low for hint in QUOTA_HINTS)


def _is_transient(text: str) -> bool:
    low = text.lower()
    return any(hint in low for hint in TRANSIENT_HINTS)


def stream_once(body: dict, *, token: str, account: str, on_delta, timeout: float,
                opener=urllib.request.urlopen) -> dict:
    """送一次請求，邊收邊把文字交給 on_delta；回傳這一次的 output 項目和用量。"""

    request = urllib.request.Request(
        URL, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {token}", "chatgpt-account-id": account, "originator": "pi",
                 "OpenAI-Beta": "responses=experimental", "accept": "text/event-stream",
                 "content-type": "application/json", "session-id": body["prompt_cache_key"],
                 "User-Agent": USER_AGENT})
    items: list[dict] = []
    usage: dict = {}
    try:
        with opener(request, timeout=timeout) as response:
            for raw in response:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    event = json.loads(line[5:].strip())
                except ValueError:
                    continue
                kind = event.get("type")
                if kind == "response.output_text.delta":
                    on_delta(event.get("delta") or "")
                elif kind == "response.output_item.done":
                    items.append(event.get("item") or {})
                elif kind == "response.completed":
                    usage = (event.get("response") or {}).get("usage") or {}
                elif kind in ("response.failed", "error"):
                    detail = json.dumps(event, ensure_ascii=False)
                    if _is_quota(detail):
                        raise ModelError("quota", _clean(detail, token))
                    raise ModelError("unavailable", _clean(detail, token), transient=_is_transient(detail))
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:600].decode("utf-8", "replace")
        if exc.code == 429 or _is_quota(detail):
            raise ModelError("quota", _clean(detail, token)) from None
        if exc.code in (401, 403):
            forget_credentials()
            raise ModelError("auth", f"{exc.code} {_clean(detail, token)}") from None
        raise ModelError("unavailable", f"{exc.code} {_clean(detail, token)}", transient=exc.code >= 500) from None
    except TimeoutError as exc:
        raise ModelError("timeout", type(exc).__name__) from None
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise ModelError("timeout", type(exc.reason).__name__) from None
        raise ModelError("unavailable", type(exc.reason).__name__, transient=True) from None
    except (OSError, http.client.HTTPException) as exc:  # 串流到一半連線被切
        raise ModelError("unavailable", type(exc).__name__, transient=True) from None
    return {"items": items, "usage": usage}


def _stream_with_retry(body: dict, *, token: str, account: str, on_delta, on_retry, deadline: float, opener, now,
                       sleep) -> dict:
    """伺服器一下子過載就等 RETRY_WAITS 再送；時間不夠或不是這類錯誤就照原樣丟出去。"""

    for attempt in range(len(RETRY_WAITS) + 1):
        left = deadline - now()
        if left <= 0:
            raise ModelError("timeout", "This turn exceeded its time limit.")
        try:
            return stream_once(body, token=token, account=account, on_delta=on_delta, timeout=max(5.0, left),
                               opener=opener)
        except ModelError as exc:
            if not exc.transient or attempt == len(RETRY_WAITS) or deadline - now() < RETRY_WAITS[attempt] + 5:
                raise
            sleep(RETRY_WAITS[attempt])
            on_retry()  # 上一次寫到一半就斷的字不算，重來
    raise AssertionError("unreachable")


def _message_text(items: list[dict]) -> str:
    parts = []
    for item in items:
        if item.get("type") == "message":
            parts += [c.get("text") or "" for c in item.get("content") or [] if c.get("type") == "output_text"]
    return "".join(parts).strip()


def run_turn(*, instructions: str, turn_text: str, call_tool, model: str, effort: str, cache_key: str,
             timeout: float, on_text=None, on_round=None, credentials_fn=credentials, images=(),
             opener=urllib.request.urlopen, now=time.monotonic, sleep=time.sleep, tool_specs=None) -> TurnResult:
    """跑完一輪：可能來回用幾次工具，最後一段文字就是回答。call_tool(name, args) 回傳要給模型的文字。
    images：使用者這一輪附的圖片（data URL），跟她的話放在同一則訊息裡。"""

    started = now()
    deadline = started + timeout
    result = TurnResult(status="error")
    allowed_names = {s['name'] for s in response_tools(tool_specs)}
    try:
        token, account = credentials_fn()
        items: list = [{"role": "user", "content": [{"type": "input_text", "text": turn_text}]
                        + [{"type": "input_image", "image_url": url} for url in images]}]
        for round_no in range(1, MAX_ROUNDS + 1):
            if now() >= deadline:
                raise ModelError("timeout", "This turn exceeded its time limit.")
            if on_round:
                on_round(round_no)
            text: list[str] = []

            def on_delta(piece: str) -> None:
                if result.first_text is None:
                    result.first_text = round(now() - started, 2)
                text.append(piece)
                if on_text:
                    on_text("".join(text))

            # 每次請求換新的快取鍵（cache_key 只當前綴）：10/14 交錯實測 7 組，沿用同一把鍵、命中快取的
            # 第一個字中位數 6.4 秒，換新鍵 3 秒，每一組都是換新鍵快；提示才 6 千 token，省下的計算比不上排隊
            key = f"{cache_key}-{uuid.uuid4().hex[:12]}"
            body = request_body(model=model, effort=effort, instructions=instructions, items=items, cache_key=key,tool_specs=tool_specs)
            if round_no == MAX_ROUNDS:
                body["tool_choice"] = "none"
                body["input"] = items + [{"role": "user", "content": [{"type": "input_text", "text": LAST_ROUND_NOTE}]}]
            got = _stream_with_retry(body,
                                     token=token, account=account, on_delta=on_delta, on_retry=text.clear,
                                     deadline=deadline, opener=opener, now=now, sleep=sleep)
            result.rounds = round_no
            for key, value in (got["usage"] or {}).items():
                # input_tokens_details／output_tokens_details 裡的 cached_tokens、reasoning_tokens 也攤平加總
                for name, number in (value.items() if isinstance(value, dict) else [(key, value)]):
                    if isinstance(number, int):
                        result.usage[name] = result.usage.get(name, 0) + number
            outside = [i.get("name") if i.get("type") == "function_call" else i.get("type")
                       for i in got["items"]
                       if i.get("type") not in ALLOWED_ITEMS
                       or (i.get("type") == "function_call" and i.get("name") not in allowed_names)]
            if outside:
                result.status, result.blocked = "lockdown", str(outside[0] or "?")
                return result
            calls = [i for i in got["items"] if i.get("type") == "function_call"]
            if not calls:
                result.status, result.answer = "ok", _message_text(got["items"]) or "".join(text).strip()
                return result
            items = items + got["items"]
            for item in calls:
                try:
                    args = json.loads(item.get("arguments") or "{}")
                except ValueError:
                    args = {}
                output = call_tool(item.get("name"), args if isinstance(args, dict) else {})
                items.append({"type": "function_call_output", "call_id": item.get("call_id"), "output": str(output)})
        raise ModelError("bad_response", f"Tool calls exceeded {MAX_ROUNDS} rounds.")
    except ModelError as exc:
        result.status = "quota" if exc.kind == "quota" else "error"
        result.error_kind, result.error = exc.kind, str(exc)
        return result
    finally:
        result.seconds = round(now() - started, 1)

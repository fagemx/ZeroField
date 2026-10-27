"""可切換的代理供應商與「頭與手腳分離」執行協定。

OpenBench 將「工作台控制面（Head）」與「代理執行器（Limb / Worker）」分離：
1. 工作台負責管理畫布狀態、任務佇列（assistant_message lease）與提案審核（Proposal Card）。
2. 代理執行器可以跑在本機背景執行緒，也可以是遠端獨立進程，並自由切換底層供應商：
   - openai_compat：標準 OpenAI `/v1/chat/completions` 相容端點；預設本機 Ollama＋qwen3.8:27b，
     託管或閉源端點要管理者放行網路、設價格上限（SPEC_20 供應商原則）
   - codex_cli：透過零依賴 MCP stdio 驅動本機 CLI 代理（codex_runner）
   ChatGPT 訂閱端點（舊 `responses` 類型與 `direct` 別名）已移除（SPEC_20 R3）。
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit

from project_assistant import model_client, tool_specs

DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_MODEL = "qwen3.8:27b"
DEFAULT_EFFORT = "medium"
REMOVED_KINDS = frozenset({"responses", "direct"})
KIND_REMOVED = ("The 'responses' model runtime (ChatGPT subscription endpoint) was removed; "
                "use kind openai_compat with a local or allowlisted endpoint.")
# 這些狀態碼代表供應商拒絕了請求、沒有執行（SPEC_20 §4.1）
REJECTED_STATUS = frozenset({400, 401, 403, 404, 413, 422, 429})


@dataclass(frozen=True)
class ProviderConfig:
    kind: str          # openai_compat | codex_cli
    base_url: str
    api_key: str
    model: str
    effort: str | None = None

    def __post_init__(self):
        if self.effort not in (None, 'low', 'medium', 'high'):
            raise ValueError('Invalid model reasoning effort.')


def local_url(url) -> bool:
    """Loopback by hostname only: a path or query that mentions localhost is not local."""
    try:
        return urlsplit(url).hostname in ('127.0.0.1', 'localhost', '::1')
    except ValueError:
        return False


def provider_from_env(env=None) -> ProviderConfig:
    env = os.environ if env is None else env
    kind = (env.get("OPENBENCH_PROVIDER") or env.get("PROJECT_ASSISTANT_ENGINE") or "openai_compat").strip().lower()
    base_url = (env.get("OPENBENCH_API_BASE") or "").strip()
    model = (env.get("OPENBENCH_MODEL") or env.get("PROJECT_ASSISTANT_MODEL") or "").strip()
    effort = (env.get("OPENBENCH_REASONING_EFFORT") or "").strip().lower()
    if effort not in ("", "low", "medium", "high"):
        raise ValueError("OPENBENCH_REASONING_EFFORT must be low, medium or high.")
    # 只有完整的本機預設才自動帶 effort；自訂端點或模型可能不收 reasoning_effort
    return ProviderConfig(kind=kind, base_url=(base_url or DEFAULT_BASE_URL).rstrip("/"),
                          api_key=(env.get("OPENBENCH_API_KEY") or env.get("OPENAI_API_KEY") or "").strip(),
                          model=model or DEFAULT_MODEL, effort=effort or (None if base_url or model else DEFAULT_EFFORT))


def _chat_tools(specs=None) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": spec["name"],
                "description": spec["description"],
                "parameters": spec["inputSchema"],
            },
        }
        for spec in (tool_specs.TOOLS if specs is None else specs)
    ]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def run_openai_compat_turn(*, config: ProviderConfig, instructions: str, turn_text: str,
                           call_tool, timeout: float, on_text=None, on_round=None,
                           images=(), opener=urllib.request.urlopen, now=time.monotonic, tool_specs=None, admission=None) -> model_client.TurnResult:
    """標準 `/v1/chat/completions` 工具呼叫迴圈（本機 Ollama / vLLM，或管理者放行的託管端點）。

    Never sends tool_choice (Ollama rejects it); the last round offers no tools and asks
    for an answer from what was found. A failed round settles per SPEC_20 §4.1: local,
    unsent or rejected requests are terminated; ambiguous remote outcomes stay uncertain.
    """

    if admission and opener is urllib.request.urlopen:
        opener = urllib.request.build_opener(_NoRedirect()).open
    started = now()
    deadline = started + timeout
    result = model_client.TurnResult(status="error")
    available_tools = _chat_tools(tool_specs)
    allowed_names = {s['function']['name'] for s in available_tools}
    local = local_url(config.base_url)
    if not config.api_key and not local:
        result.error_kind = "auth"
        result.error = "尚未設定 OPENBENCH_API_KEY"
        return result

    messages: list[dict] = [
        {"role": "system", "content": instructions},
        {"role": "user", "content": ([{"type": "text", "text": turn_text}] +
          [{"type": "image_url", "image_url": {"url": url}} for url in images]) if images else turn_text},
    ]
    url = f"{config.base_url}/chat/completions"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    where = "Local model endpoint" if local else "Model endpoint"
    # (outcome, known_terminated, observed_cost) for a round that fails after admission.
    settle = ('failed', True, None) if local else ('unknown', False, None)

    try:
        for round_no in range(1, model_client.MAX_ROUNDS + 1):
            left = deadline - now()
            if left <= 0:
                raise model_client.ModelError("timeout", "This turn exceeded its time limit.")
            if on_round:
                on_round(round_no)
            last = round_no == model_client.MAX_ROUNDS
            if last:
                messages.append({"role": "user", "content": model_client.LAST_ROUND_NOTE})
            payload = {
                "model": config.model,
                "messages": messages,
                **({'reasoning_effort': config.effort} if config.effort is not None else {}),
                **({'tools': available_tools} if available_tools and not last else {}),
            }
            if admission:
                admission.before(payload)
            req = urllib.request.Request(
                url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                method="POST", headers=headers,
            )
            try:
                with opener(req, timeout=max(.1, min(left, getattr(admission, 'timeout_limit', left)))) as resp:
                    limit = getattr(admission, 'response_limit', 2*1024*1024)
                    raw = resp.read(limit+1)
                    if len(raw) > limit:
                        raise model_client.ModelError('bad_response', 'Provider response exceeds the environment transport limit.')
                    data = json.loads(raw.decode("utf-8", "replace"))
            except urllib.error.HTTPError as exc:
                # Error bodies can echo API credentials; return only the HTTP status.
                if exc.code in REJECTED_STATUS and not local:
                    settle = ('failed', True, 0)
                detail = f'{where} returned HTTP {exc.code}.'
                if exc.code == 429:
                    raise model_client.ModelError("quota", detail) from None
                if exc.code in (401, 403):
                    raise model_client.ModelError("auth", detail) from None
                raise model_client.ModelError("unavailable", detail) from None
            except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
                # urllib wraps connect/send failures in URLError; later ones arrive raw.
                reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
                if isinstance(exc, urllib.error.URLError) and isinstance(reason, (ConnectionRefusedError, socket.gaierror)):
                    if not local:
                        settle = ('failed', True, 0)
                    cause = 'connection refused' if isinstance(reason, ConnectionRefusedError) else 'host name lookup failed'
                    hint = ' Start the local model server (for example Ollama), then retry.' if local else ' Nothing was sent.'
                    raise model_client.ModelError("unavailable", f'{where} is not reachable ({cause}).{hint}') from None
                pending = '' if local else '; the outcome is uncertain until an administrator reconciles it'
                if isinstance(reason, TimeoutError):
                    raise model_client.ModelError("timeout", f'{where} did not answer in time{pending}.') from None
                cause = type(reason).__name__ if isinstance(reason, BaseException) else type(exc).__name__
                raise model_client.ModelError("unavailable", f'{where} connection failed ({cause}){pending}.') from None
            except ValueError:
                raise model_client.ModelError('bad_response', f'{where} returned malformed JSON.') from None
            if not isinstance(data, dict):
                raise model_client.ModelError('bad_response', f'{where} returned malformed JSON.')

            usage = data.get('usage') or {}
            for name, value in usage.items():
                for key, number in (value.items() if isinstance(value, dict) else [(name, value)]):
                    if type(number) is int and number >= 0:
                        result.usage[key] = result.usage.get(key, 0) + number
            if admission:
                admission.after(usage)
            result.rounds = round_no
            choice = ((data.get("choices") or [{}])[0]).get("message") or {}
            content = (choice.get("content") or "").strip()
            if content:
                if result.first_text is None:
                    result.first_text = round(now() - started, 2)
                if on_text:
                    on_text(content)
            tool_calls = choice.get("tool_calls") or []
            if not tool_calls:
                result.status = "ok"
                result.answer = content
                return result
            if last:
                # No tools were offered this round; never execute calls the model still emits.
                outside = next((n for n in ((tc.get("function") or {}).get("name") or "" for tc in tool_calls) if n not in allowed_names), None)
                if outside is not None:
                    result.status, result.blocked = "lockdown", outside or "?"
                    return result
                break

            messages.append(choice)
            for tc in tool_calls:
                fn = tc.get("function") or {}
                name = fn.get("name") or ""
                if name not in allowed_names:
                    result.status, result.blocked = "lockdown", name or "?"
                    return result
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except ValueError:
                    args = {}
                out = call_tool(name, args if isinstance(args, dict) else {})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id") or "",
                    "content": str(out),
                })
                if getattr(out, 'images', None):
                    messages.append({'role': 'user', 'content': [{'type': 'text', 'text': 'Authorized tool contact sheet; timing is in the tool result.'}] +
                        [{'type': 'image_url', 'image_url': {'url': image}} for image in out.images]})
        raise model_client.ModelError("bad_response", "Tool calls exceeded the limit.")
    except model_client.ModelError as exc:
        result.status = "quota" if exc.kind == "quota" else "error"
        result.error_kind, result.error = exc.kind, str(exc)
        return result
    finally:
        if admission:
            # No-op once the round settled; otherwise settle the in-flight reservation.
            outcome, terminated, observed = settle
            admission.after({}, outcome, known_terminated=terminated, observed_cost=observed)
        result.seconds = round(now() - started, 1)

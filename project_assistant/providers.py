"""可切換的代理供應商與「頭與手腳分離」執行協定。

OpenBench 將「工作台控制面（Head）」與「代理執行器（Limb / Worker）」分離：
1. 工作台負責管理畫布狀態、任務佇列（assistant_message lease）與提案審核（Proposal Card）。
2. 代理執行器可以跑在本機背景執行緒，也可以是遠端獨立進程，並自由切換底層供應商：
   - openai_compat：標準 OpenAI `/v1/chat/completions` 相容端點（OpenAI / Gemini / Claude / OpenRouter / Ollama / vLLM）
   - responses：OpenAI / ChatGPT Responses 串流端點（model_client）
   - codex_cli：透過零依賴 MCP stdio 驅動本機 CLI 代理（codex_runner）
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from project_assistant import model_client, tool_specs


@dataclass(frozen=True)
class ProviderConfig:
    kind: str          # responses | openai_compat | codex_cli
    base_url: str
    api_key: str
    model: str


def provider_from_env(env=None) -> ProviderConfig:
    env = os.environ if env is None else env
    kind = (env.get("OPENBENCH_PROVIDER") or env.get("PROJECT_ASSISTANT_ENGINE") or "openai_compat").strip().lower()
    if kind == "direct":
        kind = "responses"
    base_url = (env.get("OPENBENCH_API_BASE") or "https://api.openai.com/v1").rstrip("/")
    api_key = (env.get("OPENBENCH_API_KEY") or env.get("OPENAI_API_KEY") or "").strip()
    model = (env.get("OPENBENCH_MODEL") or env.get("PROJECT_ASSISTANT_MODEL") or "gpt-4.1").strip()
    return ProviderConfig(kind=kind, base_url=base_url, api_key=api_key, model=model)


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


def run_openai_compat_turn(*, config: ProviderConfig, instructions: str, turn_text: str,
                           call_tool, timeout: float, on_text=None, on_round=None,
                           images=(), opener=urllib.request.urlopen, now=time.monotonic, tool_specs=None) -> model_client.TurnResult:
    """標準 `/v1/chat/completions` 工具呼叫迴圈（支援 OpenAI / Gemini / OpenRouter / Ollama / vLLM）。"""

    started = now()
    deadline = started + timeout
    result = model_client.TurnResult(status="error")
    available_tools = _chat_tools(tool_specs)
    allowed_names = {s['function']['name'] for s in available_tools}
    if not config.api_key and "127.0.0.1" not in config.base_url and "localhost" not in config.base_url:
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

    try:
        for round_no in range(1, model_client.MAX_ROUNDS + 1):
            left = deadline - now()
            if left <= 0:
                raise model_client.ModelError("timeout", "這一輪超過時間")
            if on_round:
                on_round(round_no)
            payload = {
                "model": config.model,
                "messages": messages,
                **({'tools':available_tools} if available_tools else {}),
                **({'tool_choice': 'none' if round_no == model_client.MAX_ROUNDS else 'auto'} if available_tools else {}),
            }
            req = urllib.request.Request(
                url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                method="POST", headers=headers,
            )
            try:
                with opener(req, timeout=max(5.0, left)) as resp:
                    data = json.loads(resp.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as exc:
                detail = exc.read()[:400].decode("utf-8", "replace")
                if exc.code == 429:
                    raise model_client.ModelError("quota", detail) from None
                if exc.code in (401, 403):
                    raise model_client.ModelError("auth", detail) from None
                raise model_client.ModelError("unavailable", detail) from None

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
        raise model_client.ModelError("bad_response", "工具呼叫超過上限")
    except model_client.ModelError as exc:
        result.status = "quota" if exc.kind == "quota" else "error"
        result.error_kind, result.error = exc.kind, str(exc)
        return result
    finally:
        result.seconds = round(now() - started, 1)

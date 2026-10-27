"""可切換的代理供應商與「頭與手腳分離」執行協定。

OpenBench 將「工作台控制面（Head）」與「代理執行器（Limb / Worker）」分離：
1. 工作台負責管理畫布狀態、任務佇列（assistant_message lease）與提案審核（Proposal Card）。
2. 代理執行器可以跑在本機背景執行緒，也可以是遠端獨立進程，並自由切換底層供應商：
   - openai_compat：標準 OpenAI `/v1/chat/completions` 相容端點；預設本機 Ollama＋qwen3.8:27b，
     託管或閉源端點要管理者放行網路、設價格上限（SPEC_20 供應商原則）
   - codex_cli：透過零依賴 MCP stdio 驅動本機 CLI 代理（codex_runner）
   ChatGPT 訂閱端點（舊 `responses` 類型與 `direct` 別名）已移除（SPEC_20 R3）。
請求依供應商目錄的能力旗標塑形（SPEC_20 R8），每輪送出前估算情境長度並修剪（R10），
失敗分成 local／quota／auth／provider／timeout／empty／output（R12）。
"""
from __future__ import annotations

import base64
import http.client
import json
import math
import os
import re
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit

from project_assistant import model_client, provider_catalog, tool_specs

DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_MODEL = "qwen3.8:27b"
DEFAULT_EFFORT = "medium"
REMOVED_KINDS = frozenset({"responses", "direct"})
KIND_REMOVED = ("The 'responses' model runtime (ChatGPT subscription endpoint) was removed; "
                "use kind openai_compat with a local or allowlisted endpoint.")
# 這些狀態碼代表供應商拒絕了請求、沒有執行（SPEC_20 §4.1）
REJECTED_STATUS = frozenset({400, 401, 403, 404, 413, 422, 429})
EFFORTS = ('low', 'medium', 'high')
TRIMMED_TOOL = '[Older tool output removed to fit the model context; call the tool again if you still need it.]'
TRIMMED_IMAGES = '[Older contact sheet removed to fit the model context.]'
NO_VISION = ' [{n} image(s) not sent: this model cannot read images.]'
STUDIO_MEDIA = re.compile(r'/projects/api/[^/?#]+/assets/pa_[0-9a-f]{32}')
_THINK = re.compile(r'(?s)<think>.*?</think>')
_MODEL_ID = re.compile(r'[a-zA-Z0-9_.:/-]{1,160}')


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


# ---------- Request shaping by capability (SPEC_20 R8) ----------

def _image_url(url, entry, read_media):
    """A URL the model can take: data URIs as they are, studio media inlined from storage.

    Studio media (a relative asset path or a loopback URL) is never fetched over HTTP and
    never handed to a hosted provider. Remote links pass through only to models that
    fetch image URLs themselves; otherwise they are refused rather than fetched here.
    """
    if not isinstance(url, str) or not url:
        raise model_client.ModelError('bad_request', 'An image input is missing.', 'provider')
    if url.startswith('data:image/'):
        return url
    try:
        parts = urlsplit(url)
        studio = (not parts.scheme and not parts.netloc and STUDIO_MEDIA.fullmatch(parts.path) is not None) or (
            parts.scheme in ('http', 'https') and parts.hostname in provider_catalog.LOOPBACK)
    except ValueError:
        raise model_client.ModelError('bad_request', 'An image link is malformed.', 'provider') from None
    if studio:
        if read_media is None:
            raise model_client.ModelError('bad_request', 'Studio media has to be read from storage, and no media reader was supplied.', 'provider')
        mime, data = read_media(url)
        if not isinstance(mime, str) or not mime.startswith('image/') or not isinstance(data, (bytes, bytearray)):
            raise model_client.ModelError('bad_request', 'Studio media is not an image.', 'provider')
        return 'data:' + mime + ';base64,' + base64.b64encode(bytes(data)).decode('ascii')
    if parts.scheme in ('http', 'https') and entry.can('image_url'):
        return url
    raise model_client.ModelError('bad_request', 'This model takes images inline only; remote image links are not fetched.', 'provider')


def _image_parts(images, entry, read_media):
    """(content parts, note): images the model can read, or a note when it reads none."""
    images = list(images or ())
    if not images:
        return [], ''
    if not entry.can('vision'):
        return [], NO_VISION.format(n=len(images))
    return [{'type': 'image_url', 'image_url': {'url': _image_url(url, entry, read_media)}} for url in images], ''


def _json_schema(json_schema):
    if json_schema is None:
        return None
    if not isinstance(json_schema, dict) or not isinstance(json_schema.get('schema'), dict) or \
            not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', str(json_schema.get('name', ''))) or set(json_schema) - {'name', 'schema', 'strict'}:
        raise ValueError('json_schema needs a name and a schema object.')
    return json_schema


def _opening(*, instructions, turn_text, history, images, entry, read_media, json_schema):
    """System prompt, earlier turns (oldest first) and the latest user turn with its images.

    `json_schema` is given only when the schema has to be stated in the prompt: the model
    has no structured output, or tools are on offer (a constrained format would stop them).
    """
    if json_schema:
        instructions += ('\n\nAnswer with only one JSON value that matches this JSON Schema, with no other text:\n'
                         + json.dumps(json_schema['schema'], ensure_ascii=False))
    messages = [{'role': 'system', 'content': instructions}]
    for item in history or ():
        if not isinstance(item, dict) or item.get('role') not in ('user', 'assistant') or not isinstance(item.get('content'), str):
            raise ValueError('History items are {"role": "user"|"assistant", "content": str}.')
        messages.append({'role': item['role'], 'content': item['content']})
    parts, note = _image_parts(images, entry, read_media)
    text = turn_text + note
    messages.append({'role': 'user', 'content': [{'type': 'text', 'text': text}] + parts if parts else text})
    return messages


def _final_answer(content, json_schema, where):
    """Validate the closing answer: empty is its own failure; a requested JSON answer must parse."""
    visible = _THINK.sub('', content).strip()
    if not visible:
        raise model_client.ModelError('empty', f'{where} returned no answer and no tool calls.')
    if not json_schema:
        return content
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', visible)
    try:
        json.loads(text)
    except ValueError:
        raise model_client.ModelError('output', f'{where} did not answer with the requested JSON.') from None
    return text


# ---------- Context budget (SPEC_20 R10) ----------

def estimate_tokens(payload, entry):
    """Conservative size: request bytes ÷ the catalog ratio (3), plus a per-image estimate."""
    images = 0
    def strip(content):
        nonlocal images
        if not isinstance(content, list):
            return content
        kept = []
        for part in content:
            if isinstance(part, dict) and part.get('type') in ('image_url', 'input_image'):
                images += 1
                kept.append({'type': part['type']})
            else:
                kept.append(part)
        return kept
    light = {**payload, 'messages': [{**m, 'content': strip(m.get('content'))} for m in payload.get('messages', [])]}
    size = len(json.dumps(light, ensure_ascii=False).encode('utf-8'))
    return math.ceil(size / entry.bytes_per_token) + images * entry.image_tokens


def _fit_context(payload, entry, turn, record):
    """Trim the oldest history, then the oldest tool outputs and contact sheets, to 80% of the context.

    The system prompt, the latest user turn and everything from the latest assistant
    message on (the round the model is answering) are never touched.
    """
    budget = entry.budget_tokens
    estimate = estimate_tokens(payload, entry)
    if estimate <= budget:
        return
    record['estimated_before'] = max(record.get('estimated_before', 0), estimate)
    messages = payload['messages']
    position = lambda: next(i for i, m in enumerate(messages) if m is turn)  # identity: an old turn may read the same
    cut = {'history': 0, 'tool_outputs': 0, 'images': 0}
    while estimate > budget and position() > 1:
        messages.pop(1)  # history sits between the system prompt and the latest turn
        cut['history'] += 1
        estimate = estimate_tokens(payload, entry)
    last = max((i for i, m in enumerate(messages) if m.get('role') == 'assistant'), default=len(messages))
    for index in range(position() + 1, last):
        if estimate <= budget:
            break
        message = messages[index]
        if message.get('role') == 'tool' and message.get('content') != TRIMMED_TOOL:
            message['content'] = TRIMMED_TOOL
            cut['tool_outputs'] += 1
        elif message.get('role') == 'user' and isinstance(message.get('content'), list):
            message['content'] = TRIMMED_IMAGES
            cut['images'] += 1
        else:
            continue
        estimate = estimate_tokens(payload, entry)
    for name, count in cut.items():
        record[name] = record.get(name, 0) + count
    record.update(context_tokens=entry.context_tokens, budget_tokens=budget, estimated_tokens=estimate,
                  over_budget=record.get('over_budget', False) or estimate > budget)


def run_openai_compat_turn(*, config: ProviderConfig, instructions: str, turn_text: str,
                           call_tool, timeout: float, on_text=None, on_round=None,
                           images=(), opener=urllib.request.urlopen, now=time.monotonic, tool_specs=None, admission=None,
                           history=(), reasoning_effort=None, json_schema=None, tool_choice=None, read_media=None,
                           entry=None) -> model_client.TurnResult:
    """標準 `/v1/chat/completions` 工具呼叫迴圈（本機 Ollama / vLLM，或管理者放行的託管端點）。

    Requests follow the catalog entry's capabilities (R8): tools only when supported,
    `tool_choice` only when supported and asked for, `response_format` for a JSON schema
    when supported (otherwise the schema goes into the instructions), images inlined as
    base64 unless the model fetches links. The last round offers no tools and asks for an
    answer from what was found. `history` holds earlier turns as chat messages so the
    context budget can drop the oldest first (R10). `reasoning_effort` overrides the
    configured effort for this call only. A failed round settles per SPEC_20 §4.1:
    local, unsent or rejected requests are terminated; ambiguous remote outcomes stay
    uncertain.
    """

    if admission and opener is urllib.request.urlopen:
        opener = urllib.request.build_opener(_NoRedirect()).open
    from project_assistant import gpu_arbiter  # SPEC_20 R13: a loopback model call holds the GPU for each request
    opener = gpu_arbiter.gate(opener, config)
    if reasoning_effort not in (None, *EFFORTS):
        raise ValueError('reasoning_effort must be low, medium or high.')
    json_schema = _json_schema(json_schema)
    entry = entry or provider_catalog.match(config)
    effort = reasoning_effort if reasoning_effort is not None else config.effort
    started = now()
    deadline = started + timeout
    result = model_client.TurnResult(status="error")
    available_tools = _chat_tools(tool_specs) if entry.can('tools') else []
    allowed_names = {s['function']['name'] for s in available_tools}
    local = local_url(config.base_url)
    if not config.api_key and not local:
        result.error_kind, result.failure = "auth", "auth"
        result.error = "尚未設定 OPENBENCH_API_KEY"
        return result

    url = f"{config.base_url}/chat/completions"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    where = "Local model endpoint" if local else "Model endpoint"
    # (outcome, known_terminated, observed_cost) for a round that fails after admission.
    # Local failures end cleanly and are never charged (SPEC_20 §4.1), even when an operator priced the model.
    settle = ('failed', True, 0) if local else ('unknown', False, None)

    try:
        messages = _opening(instructions=instructions, turn_text=turn_text, history=history, images=images, entry=entry,
                            read_media=read_media, json_schema=json_schema if json_schema and (available_tools or not entry.can('json_schema')) else None)
        turn = messages[-1]
        for round_no in range(1, model_client.MAX_ROUNDS + 1):
            left = deadline - now()
            if left <= 0:
                raise model_client.ModelError("timeout", "This turn exceeded its time limit.")
            if on_round:
                on_round(round_no)
            last = round_no == model_client.MAX_ROUNDS
            if last:
                messages.append({"role": "user", "content": model_client.LAST_ROUND_NOTE})
            offered = available_tools and not last
            payload = {
                "model": config.model,
                "messages": messages,
                **({'reasoning_effort': effort} if effort is not None else {}),
                **({'tools': available_tools} if offered else {}),
                **({'tool_choice': tool_choice} if tool_choice is not None and offered and entry.can('tool_choice') else {}),
                # A constrained format would stop tool calls, so it only goes on rounds without tools.
                **({'response_format': {'type': 'json_schema', 'json_schema': {k: v for k, v in json_schema.items() if k != 'strict' or v}}}
                   if json_schema and entry.can('json_schema') and not offered else {}),
            }
            _fit_context(payload, entry, turn, result.trimmed)
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
                if isinstance(reason, gpu_arbiter.GpuBusy):  # the GPU never came free; nothing was sent
                    raise model_client.ModelError("gpu_busy", str(reason), "gpu_busy") from None
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
            # The ledger records the model the provider says answered, not only the configured one (R12).
            reported = data.get('model') if isinstance(data.get('model'), str) and _MODEL_ID.fullmatch(data.get('model')) else ''
            result.model = reported or result.model
            if admission:
                admission.after(usage, **({'model': reported} if reported else {}))
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
                result.answer = _final_answer(content, json_schema, where)
                result.status = "ok"
                return result
            if last:
                # No tools were offered this round; never execute calls the model still emits.
                outside = next((n for n in ((tc.get("function") or {}).get("name") or "" for tc in tool_calls) if n not in allowed_names), None)
                if outside is not None:
                    result.status, result.blocked = "lockdown", outside or "?"
                    return result
                break

            messages.append(choice if choice.get('role') else {'role': 'assistant', **choice})
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
                sheets, note = _image_parts(getattr(out, 'images', None), entry, read_media)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id") or "",
                    "content": str(out) + note,
                })
                if sheets:
                    messages.append({'role': 'user', 'content': [{'type': 'text', 'text': 'Authorized tool contact sheet; timing is in the tool result.'}] + sheets})
        raise model_client.ModelError("bad_response", "Tool calls exceeded the limit.", 'output')
    except model_client.ModelError as exc:
        result.status = "quota" if exc.kind == "quota" else "error"
        result.error_kind, result.error = exc.kind, str(exc)
        result.failure = exc.failure or model_client.failure_class(exc.kind, local=local)
        return result
    finally:
        if admission:
            # No-op once the round settled; otherwise settle the in-flight reservation.
            outcome, terminated, observed = settle
            admission.after({}, outcome, known_terminated=terminated, observed_cost=observed)
        result.seconds = round(now() - started, 1)

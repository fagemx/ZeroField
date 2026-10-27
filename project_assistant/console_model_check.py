"""Model setup and health check for the Agent Console (SPEC_20 R36). Showrunner only.

Setup shows which model every built-in crew agent resolves to and can point an agent back at the
recommended local preset (Ollama at http://127.0.0.1:11434/v1 serving qwen3.8:27b).

The health check runs one step per request so the page can show each result as it lands:
  model    the endpoint answers and lists the model (local: the crew_readiness probe itself)
  chat     a plain reply
  tools    one tool call
  json     output constrained by a JSON schema (response_format)
  vision   a description of a generated test image (no production media is sent)
  context  the context length Ollama runs the model with (/api/show, /api/ps); 4096 is flagged
Every step that calls the model goes through ProviderAdmission like any crew turn (SPEC_20 fixed
decision 4): network policy, credential mounts, concurrency and the ledger apply. Local endpoints
are unbilled; a hosted endpoint needs an allowed host and a price ceiling first. Replies are
checked, never stored; errors carry status codes, never provider bodies or credentials.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import re
import struct
import time
import urllib.error
import urllib.request
import uuid
import zlib
from pathlib import Path
from urllib.parse import urlsplit

from project_assistant import agent_console_store as resources, agent_registry, crew_readiness, providers
from project_assistant import execution_governance as governance, orchestrator as cp, tools
from project_assistant.console_ops import api_root, local_json, stamp
from project_assistant.providers import local_url

STEPS = ('model', 'chat', 'tools', 'json', 'vision', 'context')
MODEL_STEPS = ('chat', 'tools', 'json', 'vision')
PRESET = {'kind': 'openai_compat', 'base_url': providers.DEFAULT_BASE_URL, 'model': providers.DEFAULT_MODEL}
STEP_SECONDS, LIST_SECONDS, SHOW_SECONDS = 120, 5, 5
CONTEXT_TARGET, OLLAMA_DEFAULT_CONTEXT, OLLAMA_PORT = 16384, 4096, 11434
TOOL = {'name': 'report_health', 'description': 'Report the result of the ZeroField model health check.',
        'inputSchema': {'type': 'object', 'properties': {'status': {'type': 'string', 'enum': ['ok']}},
                        'required': ['status'], 'additionalProperties': False}}
SCHEMA = {'type': 'object', 'properties': {'status': {'type': 'string', 'enum': ['ok']}, 'checks': {'type': 'integer'}},
          'required': ['status', 'checks'], 'additionalProperties': False}


class CheckFailed(Exception):
    def __init__(self, code, fix=None, message=None, **detail):
        super().__init__(code)
        self.code, self.fix, self.message, self.detail = code, fix, message, detail


# ---------- setup ----------

def _crew(conn, slug):
    return [a for a in agent_registry.list_agents(conn, slug) if a['runtime_kind'] == 'builtin_llm' and a['role_kind'] != 'observer']


def describe(config):
    """Where a provider points. Full URLs only for loopback; hosted endpoints by host."""
    url = urlsplit(config.base_url)
    local = local_url(config.base_url)
    return {'kind': config.kind, 'local': local, 'host': (url.hostname or '').lower(),
            'port': url.port or (443 if url.scheme == 'https' else 80), 'model': config.model,
            'baseUrl': config.base_url if local else None}


def matches_preset(config):
    url = urlsplit(config.base_url)
    return (config.kind == PRESET['kind'] and local_url(config.base_url) and url.port == OLLAMA_PORT
            and url.path.rstrip('/') == '/v1' and config.model == PRESET['model'])


def setup(conn, me, slug):
    from project_assistant import store
    from project_assistant.agent_runtime import provider_for
    resources.authorize(conn, me, slug, admin=True)
    default = json.loads(store.get_setting(conn, slug, 'console_default_provider', '{"vault_key":null}'))
    try:
        deployment = provider_for({})
        deployment = {**describe(deployment), 'matchesPreset': matches_preset(deployment)}
    except (ValueError, tools.ToolError):
        deployment = None
    crew = []
    for agent in _crew(conn, slug):
        entry = {'agentKey': agent['agent_key'], 'displayName': agent['display_name'], 'version': agent['version'],
                 'enabled': agent['enabled'], 'inherits': agent['provider_config'] == {}}
        try:
            config = provider_for(agent_registry.effective_profile(conn, agent))
            entry.update(provider=describe(config), matchesPreset=matches_preset(config), state='ok')
        except agent_registry.AgentError as exc:
            entry.update(provider=None, matchesPreset=False, state='kind_removed' if exc.code == 'kind_removed' else 'configuration_required')
        except (ValueError, tools.ToolError):
            entry.update(provider=None, matchesPreset=False, state='configuration_required')
        crew.append(entry)
    return {'preset': {**PRESET, 'label': 'Local Ollama · ' + PRESET['model'], 'contextTarget': CONTEXT_TARGET},
            'deploymentDefault': deployment, 'projectDefault': default.get('vault_key'), 'agents': crew, 'steps': list(STEPS)}


def apply_preset(conn, me, slug, body):
    """Point one crew agent at the local preset: inherit when the deployment default already is the
    preset and no project default overrides it, otherwise store the preset explicitly."""
    from project_assistant import store
    from project_assistant.agent_console_service import fields
    from project_assistant.agent_runtime import provider_for
    resources.authorize(conn, me, slug, admin=True)
    fields(body, {'agent_key', 'version'}, {'agent_key', 'version'})
    agent = agent_registry.get_agent(conn, slug, resources.key(body['agent_key']), effective=False)
    if not agent or agent['runtime_kind'] != 'builtin_llm' or agent['role_kind'] == 'observer':
        raise agent_registry.AgentError(404, 'Built-in crew agent not found.')
    default = json.loads(store.get_setting(conn, slug, 'console_default_provider', '{"vault_key":null}'))
    inherit = default.get('vault_key') is None and matches_preset(provider_for({}))
    saved = agent_registry.save_agent(conn, me, slug, {'agent_key': agent['agent_key'], 'version': body['version'],
                                                       'provider_config': {} if inherit else dict(PRESET)})
    crew_readiness.forget(slug)
    return {'agent': {'agentKey': saved['agent_key'], 'version': saved['version'], 'inherits': inherit}}


# ---------- health check ----------

def _context(factory, me, slug, agent_key):
    ctx = tools.ToolContext(factory, slug, me, Path('.'), None, agent_key=agent_key,
                            deadline_at=(cp.now() + dt.timedelta(seconds=STEP_SECONDS + 30)).isoformat())
    # One accounting session per step, so every reservation has its own request key.
    ctx.accounting_session_key = ctx.execution_key = 'model_check:' + uuid.uuid4().hex
    return ctx


def _resolve(conn, ctx):
    from project_assistant.agent_runtime import provider_for
    try:
        profile = governance.live(conn, ctx, ctx.agent_key)['profile']
        config = provider_for(profile)
    except agent_registry.AgentError as exc:
        if exc.code == 'kind_removed':
            raise CheckFailed('kind_removed', 'reconfigure_provider') from None
        raise CheckFailed('governance', 'review_agent', str(exc)) from None
    except governance.AdmissionError as exc:
        raise CheckFailed('governance', 'review_agent', str(exc)) from None
    except tools.ToolError:
        raise CheckFailed('auth_missing', 'configure_provider') from None
    if config.kind != 'openai_compat':
        removed = config.kind in providers.REMOVED_KINDS
        raise CheckFailed('kind_removed' if removed else 'unsupported_kind', 'reconfigure_provider' if removed else 'use_builtin_provider')
    return profile, config


def _ollama_like(config):
    return urlsplit(config.base_url).port == OLLAMA_PORT or ':' in config.model


def _listed(model, ids):
    tagged = lambda name: name if ':' in name else name + ':latest'  # Ollama lists untagged pulls as :latest
    return tagged(model) in {tagged(name) for name in ids}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _local_opener(request, timeout):
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect()).open(request, timeout=timeout)


def _remote_listing(ctx, config):
    destination = config.base_url.rstrip('/') + '/models'
    def validate(conn):
        binding = governance.live(conn, ctx, ctx.agent_key, destination)
        from project_assistant.agent_runtime import provider_for
        actual = provider_for(binding['profile'])
        governance.credential_binding(conn, ctx, binding['profile'], actual, binding['environment'])
        if actual != config:
            raise governance.AdmissionError('Provider changed during the health check.')
    try:
        governance.transaction(ctx, validate)
    except (agent_registry.AgentError, governance.AdmissionError) as exc:
        raise CheckFailed('governance', 'allow_host', str(exc)) from None
    headers = {'Accept': 'application/json', **({'Authorization': 'Bearer ' + config.api_key} if config.api_key else {})}
    try:
        with urllib.request.build_opener(_NoRedirect()).open(urllib.request.Request(destination, headers=headers), timeout=LIST_SECONDS) as response:
            raw = response.read(crew_readiness.MAX_LISTING + 1)
    except urllib.error.HTTPError as exc:
        exc.close()
        return ('auth', None) if exc.code in (401, 403) else ('bad', None)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return 'down', None
    try:
        listing = json.loads(raw) if len(raw) <= crew_readiness.MAX_LISTING else None
    except ValueError:
        listing = None
    if not isinstance(listing, dict) or not isinstance(listing.get('data'), list):
        return 'bad', None
    return 'ok', {m['id'] for m in listing['data'] if isinstance(m, dict) and isinstance(m.get('id'), str)}


def _model_step(ctx, slug, config):
    base, where = config.base_url.rstrip('/'), describe(config)
    detail = {'model': config.model, 'host': where['host'], 'port': where['port'], 'local': where['local']}
    if where['local']:
        state, ids = crew_readiness._probe(base)  # the readiness probe itself; it also refreshes the banner's memory
        crew_readiness.forget(slug)
    else:
        state, ids = _remote_listing(ctx, config)
    ollama = _ollama_like(config)
    if state == 'down':
        raise CheckFailed('unreachable', ('start_ollama' if ollama else 'start_model_server') if where['local'] else 'check_endpoint', **detail)
    if state == 'auth':
        raise CheckFailed('auth', 'set_api_key', **detail)
    if state == 'bad':
        raise CheckFailed('not_model_server', 'check_endpoint', **detail)
    if ids is None:
        return 'warn', 'list_unavailable', None, detail
    if not _listed(config.model, ids):
        raise CheckFailed('model_missing', 'ollama_pull' if ollama else 'load_model', available=sorted(ids)[:12], **detail)
    return 'pass', 'model_present', None, detail


class _Shaped:
    """A ProviderAdmission that adds request fields before governance sees the payload."""

    def __init__(self, admission, extra):
        self.admission, self.extra = admission, extra

    def before(self, payload):
        payload.update(self.extra)
        self.admission.before(payload)

    def after(self, *args, **kwargs):
        return self.admission.after(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.admission, name)


def test_image():
    """A 64x64 solid red PNG, built here so no production media leaves the studio."""
    size = 64
    raw = b''.join(b'\x00' + b'\xff\x00\x00' * size for _ in range(size))
    chunk = lambda tag, data: struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def _answer(text):
    text = re.sub(r'(?s)<think>.*?</think>', '', text or '').strip()
    return re.sub(r'(?s)^```(?:json)?\s*(.*?)\s*```$', r'\1', text).strip()


def _turn(ctx, profile, config, step, *, instructions, text, tool_specs=(), images=(), extra=None, call_tool=None):
    admission = governance.ProviderAdmission(ctx, profile, config, 'llm_turn', purpose='model_check:' + step)
    refuse = lambda *_: (_ for _ in ()).throw(ValueError('The health check offers no tools in this step.'))
    try:
        result = providers.run_openai_compat_turn(
            config=config, instructions=instructions, turn_text=text, call_tool=call_tool or refuse, timeout=STEP_SECONDS,
            tool_specs=list(tool_specs), images=images, admission=_Shaped(admission, extra) if extra else admission,
            **({'opener': _local_opener} if local_url(config.base_url) else {}))
    except (agent_registry.AgentError, governance.AdmissionError) as exc:
        raise CheckFailed('governance', 'review_agent', str(exc)) from None
    usage = {k: result.usage[k] for k in ('prompt_tokens', 'completion_tokens') if k in result.usage}
    detail = {'seconds': result.seconds, 'rounds': result.rounds, **({'usage': usage} if usage else {})}
    if result.status == 'quota':
        raise CheckFailed('quota', 'wait_or_raise_quota', result.error, **detail)
    if result.status == 'lockdown':
        return result, detail  # an unknown tool name; the tools step judges it
    if result.status != 'ok':
        kind, message = result.error_kind or 'error', result.error or ''
        status = re.search(r'returned HTTP (\d{3})', message)
        if kind == 'unavailable' and 'not reachable' in message:
            raise CheckFailed('unreachable', 'start_ollama' if _ollama_like(config) else 'start_model_server', message, **detail)
        if status and status[1] == '404':
            raise CheckFailed('model_missing', 'ollama_pull' if _ollama_like(config) else 'load_model', message, model=config.model, **detail)
        if status:
            raise CheckFailed('rejected', {'tools': 'tool_model', 'json': 'json_model', 'vision': 'vision_model'}.get(step, 'check_endpoint'), message, **detail)
        raise CheckFailed({'timeout': 'timeout', 'auth': 'auth'}.get(kind, 'model_error'),
                          {'timeout': 'retry_when_idle', 'auth': 'set_api_key'}.get(kind, 'check_endpoint'), message, **detail)
    return result, detail


def _chat(ctx, profile, config):
    result, detail = _turn(ctx, profile, config, 'chat', instructions='You are a connectivity check. Reply with the single word READY.',
                           text='Reply with the single word READY.')
    answer = _answer(result.answer)
    if not answer:
        raise CheckFailed('empty_reply', 'check_endpoint', **detail)
    return 'pass', 'replied', None, {**detail, 'reply': answer[:120], 'followed': 'READY' in answer.upper()}


def _tools(ctx, profile, config):
    calls = []
    def call_tool(name, args):
        calls.append({'name': name, 'arguments': args})
        return json.dumps({'recorded': True})
    result, detail = _turn(ctx, profile, config, 'tools', tool_specs=[TOOL], call_tool=call_tool,
                           instructions='You are a connectivity check. Call the report_health tool exactly once with status "ok", then reply DONE.',
                           text='Run the health check: call report_health with status "ok".')
    if not calls:
        raise CheckFailed('no_tool_call', 'tool_model', **detail)
    if calls[0]['arguments'].get('status') != 'ok':
        raise CheckFailed('tool_arguments', 'tool_model', **detail, arguments=calls[0]['arguments'])
    return 'pass', 'tool_called', None, {**detail, 'tool': TOOL['name'], 'calls': len(calls)}


def _json(ctx, profile, config):
    extra = {'response_format': {'type': 'json_schema', 'json_schema': {'name': 'health_check', 'strict': True, 'schema': SCHEMA}}}
    result, detail = _turn(ctx, profile, config, 'json', extra=extra,
                           instructions='You are a connectivity check. Answer with JSON only.',
                           text='Return the health check result with status "ok" and checks set to 3.')
    try:
        value = json.loads(_answer(result.answer))
    except ValueError:
        value = None
    if not (isinstance(value, dict) and set(value) == {'status', 'checks'} and value['status'] == 'ok' and type(value['checks']) is int):
        raise CheckFailed('json_invalid', 'json_model', **detail, reply=_answer(result.answer)[:120])
    return 'pass', 'json_valid', None, {**detail, 'value': value}


def _vision(ctx, profile, config):
    image = 'data:image/png;base64,' + base64.b64encode(test_image()).decode('ascii')
    result, detail = _turn(ctx, profile, config, 'vision', images=[image],
                           instructions='You are a connectivity check for image input. Answer with one lowercase word.',
                           text='What single color fills this image? Answer with one word.')
    answer = _answer(result.answer)
    if 'red' not in answer.lower():
        raise CheckFailed('vision_wrong', 'vision_model', **detail, reply=answer[:120])
    return 'pass', 'image_described', None, {**detail, 'reply': answer[:120]}


def _context_step(config):
    """Context length from Ollama: the loaded model (/api/ps) first, else the Modelfile num_ctx."""
    if not local_url(config.base_url):
        return 'skip', 'context_remote', None, {}
    root = api_root(config.base_url)
    state, shown = local_json(root + '/api/show', body={'model': config.model}, timeout=SHOW_SECONDS)
    if state != 'ok' or not isinstance(shown, dict):
        return 'skip', 'context_unknown_server', 'server_context', {}
    parameters = shown.get('parameters') if isinstance(shown.get('parameters'), str) else ''
    found = re.search(r'(?m)^\s*num_ctx\s+(\d+)', parameters)
    num_ctx = int(found[1]) if found else None
    info = shown.get('model_info') if isinstance(shown.get('model_info'), dict) else {}
    model_max = next((v for k, v in info.items() if k.endswith('.context_length') and type(v) is int), None)
    running = None
    state, listing = local_json(root + '/api/ps')
    if state == 'ok' and isinstance(listing, dict) and isinstance(listing.get('models'), list):
        for item in listing['models']:
            if isinstance(item, dict) and _listed(config.model, [str(item.get('name') or ''), str(item.get('model') or '')]):
                running = item.get('context_length') if type(item.get('context_length')) is int else None
    length = running or num_ctx
    detail = {'contextLength': length, 'source': 'running' if running else 'modelfile' if num_ctx else None,
              'numCtx': num_ctx, 'modelMax': model_max, 'target': CONTEXT_TARGET}
    if length is None:
        return 'warn', 'context_server_default', 'ollama_context_length', detail
    if length <= OLLAMA_DEFAULT_CONTEXT:
        return 'warn', 'context_4096', 'ollama_context_length', detail
    if length < CONTEXT_TARGET:
        return 'warn', 'context_small', 'ollama_context_length', detail
    return 'pass', 'context_ok', None, detail


def check(factory, me, slug, body):
    """One health-check step. 403 for anyone but the showrunner; every other problem is a step result."""
    from project_assistant.agent_console_service import fields
    fields(body, {'agent_key', 'step'}, {'agent_key', 'step'})
    if body['step'] not in STEPS:
        resources.bad('Unknown health-check step.')
    resources.key(body['agent_key'])
    ctx = _context(factory, me, slug, body['agent_key'])
    governance.transaction(ctx, lambda conn: resources.authorize(conn, me, slug, admin=True))
    started, step, config, message = time.monotonic(), body['step'], None, None
    try:
        profile, config = governance.transaction(ctx, lambda conn: _resolve(conn, ctx))
        status, code, fix, detail = (
            _model_step(ctx, slug, config) if step == 'model' else _context_step(config) if step == 'context' else
            {'chat': _chat, 'tools': _tools, 'json': _json, 'vision': _vision}[step](ctx, profile, config))
    except CheckFailed as failed:
        status, code, fix, message, detail = 'fail', failed.code, failed.fix, failed.message, failed.detail
    governed = step in MODEL_STEPS and config is not None
    return {'step': step, 'agentKey': body['agent_key'], 'status': status, 'code': code, 'fix': fix, 'message': message,
            'detail': detail, 'governed': governed, 'billed': governed and not local_url(config.base_url),
            'seconds': round(time.monotonic() - started, 1), 'checkedAt': stamp()}

"""Lock-down rules for the optional ACP worker (SPEC_20 R35, the "judgment desk" rules).

An ACP turn runs an external agent CLI (Codex or Claude Code through their ACP adapters) as a worker. It is off
by default: it only runs when a deployer binds an `acp_stdio` adapter to a worker and an administrator creates
an `acp_stdio` agent on it. These rules bound what that agent can reach through the ACP client and its
environment; they are not an OS sandbox for the executable (docs/WORKERS.md).

1. One MCP server only: `openbench` (mcp_stdio.py through the per-turn loopback tool host). Every config home
   the agent could read (HOME, USERPROFILE, APPDATA, XDG_*, CODEX_HOME, CLAUDE_CONFIG_DIR) points into the
   empty turn folder, and the Codex config keeps only model settings, so no user MCP server, plugin or
   extension loads.
2. The child environment is an allowlist; credential-like names never pass and the Codex config may not
   carry a credential. Only the deployer's configured model key is mapped, as OPENAI_API_KEY.
3. The session mode the agent reports must equal the required (read-only / ask-first) mode before any work is
   sent; a permissive mode cannot be configured, and leaving the mode mid-turn stops the turn.
4. Permission requests are denied unless they belong to an announced call of an allowed tool on `openbench`;
   then exactly one `allow_once` option is selected, once per tool call. `allow_always` is never chosen.
5. A tool call outside the turn's allowed list (a native tool, another server, an unlisted tool, a client
   file or terminal request) kills the agent's whole process tree and fails the turn with a clear reason.
6. Prompts whose text would reach the agent as a slash command are refused before the agent starts.
7. `manifest()` lists this surface for the offline tool-surface audit (scripts/audit_tool_surface.py).
"""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from pathlib import Path

SERVER_NAME = 'openbench'
MCP_SCRIPT = Path(__file__).with_name('mcp_stdio.py')
CLIENT_CAPABILITIES = {'fs': {'readTextFile': False, 'writeTextFile': False}, 'terminal': False}
DEFAULT_MODE = 'read-only'  # codex-acp; INITIAL_AGENT_MODE starts the session in it
# Modes that run tools or edit without asking. A deployer cannot require them (compared case- and dash-blind).
FORBIDDEN_MODES = frozenset({'auto', 'agent', 'agent-full-access', 'full-access', 'danger-full-access',
                             'workspace-write', 'bypassPermissions', 'acceptEdits', 'dontAsk', 'yolo'})
# Codex reports its MCP resource helpers as calls on the server "codex"; they only see the configured
# server (openbench), which publishes no resources.
AGENT_BUILTINS = frozenset({('codex', 'list_mcp_resources'), ('codex', 'list_mcp_resource_templates'),
                            ('codex', 'read_mcp_resource')})
NON_TOOL_KINDS = frozenset({'think'})  # Codex context compaction; no tool runs
GRANT_KINDS = ('allow_once',)  # the only permission option kind ever selected
ENV_KEEP = frozenset({'SYSTEMROOT', 'WINDIR', 'PATH', 'PATHEXT', 'COMSPEC', 'TEMP', 'TMP', 'LANG', 'LC_ALL', 'TZ',
                      'SSL_CERT_FILE', 'CODEX_PATH', 'MODEL_PROVIDER'})
# Every place an agent CLI looks for user configuration, redirected into the empty turn folder.
CONFIG_HOMES = {'HOME': '', 'USERPROFILE': '', 'APPDATA': '', 'LOCALAPPDATA': '', 'XDG_CONFIG_HOME': '.config',
                'XDG_DATA_HOME': '.local/share', 'XDG_STATE_HOME': '.local/state', 'XDG_CACHE_HOME': '.cache',
                'CODEX_HOME': '.codex', 'CLAUDE_CONFIG_DIR': '.claude'}
SECRET_NAME = re.compile(r'PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY|ACCESS_?KEY|CREDENTIAL|PRIVATE_?KEY|COOKIE|AUTH', re.I)
URL_CREDENTIAL = re.compile(r'[a-z][a-z0-9+.-]*://[^/\s@]*:[^/\s@]*@', re.I)
CODEX_SETTINGS = ('model', 'model_provider', 'model_reasoning_effort')
PROVIDER_SETTINGS = ('name', 'base_url', 'env_key', 'wire_api', 'query_params', 'request_max_retries',
                     'stream_max_retries', 'stream_idle_timeout_ms', 'requires_openai_auth')
MODE_NAME = re.compile(r'^[A-Za-z][A-Za-z0-9_-]{0,39}$')
SAFE_DETAIL = re.compile(r'[^A-Za-z0-9_./:@-]')
COMMAND_LINE = re.compile(r'/[A-Za-z][\w:.-]*(?:\s|$)')
FAILURES = {
    'unexpected_tool_call': "ACP turn stopped: the agent called a tool outside this turn's allowed list, "
                            'so its whole process tree was killed.',
    'mode_mismatch': 'ACP turn refused: the agent did not report the required restricted session mode, '
                     'so no work was sent.',
    'mode_changed': 'ACP turn stopped: the agent left the required restricted session mode, '
                    'so its whole process tree was killed.',
    'slash_command': 'ACP turn refused: the prompt contains a slash command the agent would run as a command; '
                     'the agent was not started.',
}


class Tripwire(Exception):
    """A lock-down rule stopped the turn; `reason` is a FAILURES key."""

    def __init__(self, reason, detail=''):
        super().__init__(reason)
        self.reason, self.detail = reason, safe_detail(detail)


def safe_detail(value) -> str:
    """Agent-supplied names, reduced to a short identifier that is safe to log and show."""
    return SAFE_DETAIL.sub('?', str(value or ''))[:80]


def failure_message(reason, detail='') -> str | None:
    """The plain message for a lock-down failure code, or None for an unknown code."""
    message = FAILURES.get(reason)
    if message and detail:
        message += f' ({safe_detail(detail)})'
    return message


def failure(reason, detail='', **extra) -> dict:
    """run_acp's result for a turn a lock-down rule stopped."""
    return {'status': 'failed', 'output': {}, 'reason': reason, 'error': failure_message(reason, detail), **extra}


# ---------- 1. one MCP server, 2. scrubbed environment ----------

def mcp_servers(url, token) -> list[dict]:
    """The session/new mcpServers: the per-turn openbench server and nothing else."""
    return [{'name': SERVER_NAME, 'command': sys.executable, 'args': ['-X', 'utf8', str(MCP_SCRIPT)],
             'env': [{'name': 'PA_TOOL_URL', 'value': url}, {'name': 'PA_TOKEN', 'value': token}]}]


def initialize_params() -> dict:
    return {'protocolVersion': 1, 'clientCapabilities': json.loads(json.dumps(CLIENT_CAPABILITIES)),
            'clientInfo': {'name': 'openbench', 'version': '1'}}


def turn_allowlist(specs) -> frozenset:
    """Names of the tools this turn may call: the Head's frozen grants that the MCP server exposes."""
    from project_assistant.tool_specs import MCP_TOOLS
    return frozenset(spec['name'] for spec in specs or [] if isinstance(spec, dict) and spec.get('name') in MCP_TOOLS)


def _secret_values(source) -> set:
    """Values of credential-named variables, long enough that finding one elsewhere is not a coincidence."""
    return {str(value) for name, value in source.items()
            if SECRET_NAME.search(str(name)) and len(str(value)) >= 12 and not os.path.exists(str(value))}


def locked_codex_config(raw, secrets=()) -> dict:
    """The CODEX_CONFIG an ACP turn runs with: the deployer's model settings plus the fixed lock-down.

    MCP servers, profiles, hooks, plugins and provider headers or bearer tokens are dropped, and a config
    that still carries a credential is refused rather than passed on."""
    configured = json.loads(raw or '{}')
    if not isinstance(configured, dict):
        raise ValueError('CODEX_CONFIG must be a JSON object')
    safe = {key: configured[key] for key in CODEX_SETTINGS if isinstance(configured.get(key), str)}
    providers = configured.get('model_providers')
    if isinstance(providers, dict):
        safe['model_providers'] = {str(name): {key: value for key, value in provider.items() if key in PROVIDER_SETTINGS}
                                   for name, provider in providers.items() if isinstance(provider, dict)}
    text = json.dumps(safe, ensure_ascii=False)
    if URL_CREDENTIAL.search(text) or any(secret in text for secret in secrets):
        raise ValueError('CODEX_CONFIG must not carry credentials; use api_key_env')
    from project_assistant.codex_runner import DISABLE
    safe.update(approval_policy='never', sandbox_mode='read-only', web_search='disabled',
                features={name: False for name in DISABLE})
    return safe


def clean_env(source, cwd, mode=DEFAULT_MODE) -> dict:
    """The agent's environment: allowlisted system variables, config homes in the empty turn folder, the
    locked Codex config and the one configured model key. Nothing credential-named is inherited."""
    env = {str(key): str(value) for key, value in source.items()
           if str(key).upper() in ENV_KEEP and not SECRET_NAME.search(str(key))}
    root = Path(cwd)
    for name, sub in CONFIG_HOMES.items():
        env[name] = str(root / sub) if sub else str(root)
    env.update(NO_BROWSER='1', INITIAL_AGENT_MODE=mode, PYTHONIOENCODING='utf-8')
    env['CODEX_CONFIG'] = json.dumps(locked_codex_config(source.get('CODEX_CONFIG'), _secret_values(source)))
    # Only the explicitly configured adapter credential is mapped, never ambient provider keys, the Head
    # bearer or the DB URI.
    if source.get('ACP_MODEL_API_KEY'):
        env['OPENAI_API_KEY'] = str(source['ACP_MODEL_API_KEY'])
    return env


def prepare_folder(root: Path) -> None:
    """The turn folder must start empty, so no config file or instruction file is there for the agent."""
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ValueError('ACP turn folder must start empty')
    for sub in {sub for sub in CONFIG_HOMES.values() if sub}:
        (root / sub).mkdir(parents=True, exist_ok=True)


# ---------- 3. session mode ----------

def _plain_mode(value) -> str:
    return str(value).lower().replace('-', '').replace('_', '')


def required_mode(value=None) -> str:
    """Validate the deployer's required_mode (default read-only); a permissive mode is refused."""
    mode = DEFAULT_MODE if value is None else value
    if (not isinstance(mode, str) or not MODE_NAME.match(mode)
            or _plain_mode(mode) in {_plain_mode(name) for name in FORBIDDEN_MODES}):
        raise ValueError('ACP required_mode must name a read-only or ask-first session mode')
    return mode


def session_mode(result) -> tuple:
    """(current mode, how to set it, available modes) as an ACP response or update reports them.

    Reads session config options (`configOptions`, the mode option) first, then the `modes` state."""
    result = result if isinstance(result, dict) else {}
    options = result.get('configOptions')
    if isinstance(options, list):
        for option in options:
            if isinstance(option, dict) and (option.get('id') == 'mode' or option.get('category') == 'mode'):
                values = set()
                for choice in option.get('options') or []:
                    for item in (choice.get('options') or [choice]) if isinstance(choice, dict) else []:
                        if isinstance(item, dict) and isinstance(item.get('value'), str):
                            values.add(item['value'])
                current = option.get('currentValue')
                return (current if isinstance(current, str) else None), ('config', option.get('id')), values
    modes = result.get('modes')
    if isinstance(modes, dict):
        current = modes.get('currentModeId')
        available = {m.get('id') for m in modes.get('availableModes') or [] if isinstance(m, dict)}
        return (current if isinstance(current, str) else None), ('mode', None), available
    return None, None, set()


# ---------- 4. permissions, 5. tool calls ----------

def tool_target(call) -> tuple:
    """What a tool call (or permission request) runs, as the two verified adapters describe it:
    ('mcp', server, tool), ('tool', name) for a named native tool, or ('kind', kind) otherwise."""
    call = call if isinstance(call, dict) else {}
    meta = call.get('_meta') if isinstance(call.get('_meta'), dict) else {}
    raw = call.get('rawInput') if isinstance(call.get('rawInput'), dict) else {}
    if meta.get('is_mcp_tool_call') is True and isinstance(raw.get('server'), str) and isinstance(raw.get('tool'), str):
        return ('mcp', raw['server'], raw['tool'])  # codex-acp
    claude = meta.get('claudeCode') if isinstance(meta.get('claudeCode'), dict) else {}
    name = claude.get('toolName')
    if isinstance(name, str) and name:
        if name.startswith('mcp__'):
            server, _, tool = name[5:].partition('__')
            return ('mcp', server, tool)
        return ('tool', name)  # claude-code-acp native tool (Bash, Read, Task…)
    return ('kind', str(call.get('kind') or 'other'))


def target_label(target) -> str:
    return safe_detail('/'.join(target[1:]) if target and target[0] == 'mcp' else (target[-1] if target else 'unknown'))


def tool_allowed(target, allowed) -> bool:
    """A tool call stays on the turn's list: an allowed openbench tool, an audited agent built-in, or no tool."""
    if target[0] == 'mcp':
        return (target[1] == SERVER_NAME and target[2] in allowed) or (target[1], target[2]) in AGENT_BUILTINS
    return target[0] == 'kind' and target[1] in NON_TOOL_KINDS


IDENTITY_FIELDS = ('kind', 'title', 'rawInput', '_meta')
MAX_TRACKED = 256


def _merge(base, update) -> dict:
    """A tool call's identity after an update: dict fields merge, so a status-only update keeps it, while an
    explicit new server, tool or kind replaces it (and is judged again)."""
    merged = dict(base)
    for key in IDENTITY_FIELDS:
        value = update.get(key)
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        elif value is not None:
            merged[key] = value
    return merged


def track_tool_call(update, tracked) -> tuple:
    """Merge one tool_call / tool_call_update into the tracked calls; returns (call id, target).

    An update for a call that was never announced is judged on its own fields (fail closed)."""
    ident = update.get('toolCallId') if isinstance(update.get('toolCallId'), str) else ''
    base = {} if update.get('sessionUpdate') == 'tool_call' else tracked.get(ident, {})
    merged = _merge(base, update)
    tracked.pop(ident, None)
    tracked[ident] = merged
    while len(tracked) > MAX_TRACKED:
        tracked.pop(next(iter(tracked)))
    return ident, tool_target(merged)


def answer_permission(params, tracked, allowed, granted) -> tuple:
    """(ACP result, offending target or None) for session/request_permission. Default deny.

    Grants only an announced call of an allowed openbench tool, once per call, with an allow_once option.
    A request that names any other tool is an unexpected tool call (the caller stops the turn)."""
    params = params if isinstance(params, dict) else {}
    cancelled = {'outcome': {'outcome': 'cancelled'}}
    call = params.get('toolCall')
    if not isinstance(call, dict):
        return cancelled, None
    ident = call.get('toolCallId') if isinstance(call.get('toolCallId'), str) else ''
    known = tracked.get(ident) if ident else None
    target = tool_target(_merge(known or {}, call))
    if not tool_allowed(target, allowed):
        return cancelled, target
    if known is None or ident in granted or target[0] != 'mcp':
        return cancelled, None
    option = next((o for o in params.get('options') or [] if isinstance(o, dict)
                   and o.get('kind') in GRANT_KINDS and isinstance(o.get('optionId'), str)), None)
    if option is None:
        return cancelled, None
    granted.add(ident)
    return {'outcome': {'outcome': 'selected', 'optionId': option['optionId']}}, None


def client_request_is_tool(method) -> bool:
    """fs/* and terminal/* are the agent asking this client to read, write or run: tools we never offered."""
    return isinstance(method, str) and method.split('/', 1)[0] in ('fs', 'terminal')


# ---------- 6. slash commands ----------

def _lead(text: str) -> str:
    index = 0
    while index < len(text) and (text[index].isspace() or unicodedata.category(text[index]) in ('Cf', 'Cc', 'Zs')):
        index += 1
    return text[index:]


def slash_command(text) -> str | None:
    """The offending start when `text` would reach the agent as a slash command, else None.

    The prompt may not start with '/' (after whitespace, invisible characters and full-width folding), and
    no line may start with a command-shaped token such as /logout or /mcp:server:cmd. A path line
    (/usr/local/...) is data and passes."""
    folded = unicodedata.normalize('NFKC', str(text or ''))
    head = _lead(folded)
    if head.startswith('/'):
        return head.split(None, 1)[0][:40] if head.strip() else '/'
    for line in folded.splitlines():
        start = _lead(line)
        if COMMAND_LINE.match(start):
            return start.split(None, 1)[0][:40]
    return None


# ---------- 7. offline listing ----------

def manifest() -> dict:
    """The fixed ACP surface, derived from what the bridge sends (scripts/audit_tool_surface.py)."""
    from project_assistant.codex_runner import DISABLE
    return {
        'mcp_servers': [server['name'] for server in mcp_servers('http://127.0.0.1:0', 'audit')],
        'client_capabilities': initialize_params()['clientCapabilities'],
        'default_mode': DEFAULT_MODE,
        'forbidden_modes': sorted(FORBIDDEN_MODES),
        'agent_builtins': sorted(f'{server}/{tool}' for server, tool in AGENT_BUILTINS),
        'non_tool_kinds': sorted(NON_TOOL_KINDS),
        'grant_kinds': list(GRANT_KINDS),
        'env_keep': sorted(ENV_KEEP),
        'config_homes': sorted(CONFIG_HOMES),
        'codex_features_disabled': sorted(DISABLE),
    }

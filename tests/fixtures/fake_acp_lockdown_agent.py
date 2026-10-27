"""Fake ACP agent for the SPEC_20 R35 lock-down tests: speaks ACP v1 JSON-RPC over stdio, never a model.

    python fake_acp_lockdown_agent.py <scenario> [args...]

Scenarios: env, echo, mode <current|none> <available,...> [notify], config_mode <current> <values,...>,
drift, permission, trip <variant>, db_trip. Files it writes go to its cwd (the turn folder):
agent.started, prompted, child.pid, grandchild.pid.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

SCENARIO = sys.argv[1]
ARGS = sys.argv[2:]
SESSION = 'lockdown-session'
Path('agent.started').write_text('1')
state = {'serial': 0, 'session_new': None, 'initialize': None, 'requests': []}


def send(message):
    sys.stdout.buffer.write((json.dumps({'jsonrpc': '2.0', **message}, ensure_ascii=False) + '\n').encode())
    sys.stdout.buffer.flush()


def read():
    line = sys.stdin.buffer.readline()
    if not line:
        sys.exit(0)
    return json.loads(line)


def update(body):
    send({'method': 'session/update', 'params': {'sessionId': SESSION, 'update': body}})


def ask(method, params):
    """A request from the agent to the client; returns the client's response."""
    state['serial'] += 1
    ident = f'agent-{state["serial"]}'
    send({'id': ident, 'method': method, 'params': params})
    while True:
        message = read()
        if message.get('id') == ident and 'method' not in message:
            return message


def say(text):
    update({'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': text}})


def codex_call(ident, server, tool, kind='other'):
    return {'sessionUpdate': 'tool_call', 'toolCallId': ident, 'title': f'{server}.{tool}', 'kind': kind,
            'status': 'pending', 'rawInput': {'server': server, 'tool': tool, 'arguments': {}},
            '_meta': {'is_mcp_tool_call': True}}


def spawn_tree(orphan=False):
    """child -> grandchild, both sleeping; with orphan the child exits and leaves the grandchild behind."""
    code = ("import os,subprocess,sys,time\n"
            "g=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)'])\n"
            "open('grandchild.tmp','w').write(str(g.pid)); os.replace('grandchild.tmp','grandchild.pid')\n"
            + ('' if orphan else 'time.sleep(120)\n'))
    child = subprocess.Popen([sys.executable, '-c', code])
    Path('child.pid').write_text(str(child.pid))
    until = time.monotonic() + 15
    while not Path('grandchild.pid').exists() and time.monotonic() < until:
        time.sleep(.02)
    if orphan:
        child.wait(timeout=15)


def mcp_client():
    server = state['session_new']['mcpServers'][0]
    env = {**os.environ, **{item['name']: item['value'] for item in server['env']}}
    child = subprocess.Popen([server['command'], *server['args']], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env)
    def call(method, params):
        child.stdin.write((json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}) + '\n').encode())
        child.stdin.flush()
        response = json.loads(child.stdout.readline())
        return response.get('result', response)
    return child, call


def session_result():
    if SCENARIO == 'mode':
        current, available = ARGS[0], [m for m in ARGS[1].split(',') if m and m != '-']
        if current == 'none':
            return {'sessionId': SESSION}
        return {'sessionId': SESSION, 'modes': {'currentModeId': current,
                'availableModes': [{'id': m, 'name': m} for m in available]}}
    if SCENARIO == 'config_mode':
        return {'sessionId': SESSION, 'configOptions': [config_option(ARGS[0])]}
    return {'sessionId': SESSION, 'modes': {'currentModeId': os.environ.get('INITIAL_AGENT_MODE'),
            'availableModes': [{'id': 'read-only', 'name': 'Read Only'}, {'id': 'full-access', 'name': 'Full Access'}]}}


def config_option(current):
    return {'id': 'mode', 'name': 'Mode', 'category': 'mode', 'type': 'select', 'currentValue': current,
            'options': [{'value': value, 'name': value} for value in ARGS[1].split(',')]}


def prompt(identifier, params):
    Path('prompted').write_text('1')
    text = ''.join(block.get('text', '') for block in params['prompt'])
    if SCENARIO == 'env':
        files = sorted(str(p.relative_to(Path.cwd())).replace('\\', '/') for p in Path.cwd().rglob('*') if p.is_file())
        say(json.dumps({'env': dict(os.environ), 'initialize': state['initialize'], 'session_new': state['session_new'],
                        'files': files, 'requests': state['requests']}))
    elif SCENARIO == 'echo':
        say(text)
    elif SCENARIO == 'drift':
        spawn_tree()
        update({'sessionUpdate': 'current_mode_update', 'currentModeId': 'full-access'})
        time.sleep(60)
    elif SCENARIO == 'permission':
        answers = {}
        update(codex_call('c1', 'openbench', 'read_page'))
        options = [{'optionId': 'aa', 'name': 'Always', 'kind': 'allow_always'},
                   {'optionId': 'ao', 'name': 'Once', 'kind': 'allow_once'},
                   {'optionId': 'r', 'name': 'Reject', 'kind': 'reject_once'}]
        answers['first'] = ask('session/request_permission', {'sessionId': SESSION, 'toolCall': {'toolCallId': 'c1'}, 'options': options})
        answers['replay'] = ask('session/request_permission', {'sessionId': SESSION, 'toolCall': {'toolCallId': 'c1'}, 'options': options})
        update(codex_call('c2', 'openbench', 'read_page'))
        answers['always_only'] = ask('session/request_permission', {'sessionId': SESSION, 'toolCall': {'toolCallId': 'c2'},
                                     'options': [options[0], options[2]]})
        answers['no_tool_call'] = ask('session/request_permission', {'sessionId': SESSION, 'options': options})
        answers['unannounced'] = ask('session/request_permission', {'sessionId': SESSION, 'options': options,
            'toolCall': {'toolCallId': 'c3', 'rawInput': {'server': 'openbench', 'tool': 'read_page'}, '_meta': {'is_mcp_tool_call': True}}})
        update({'sessionUpdate': 'tool_call', 'toolCallId': 'c4', 'title': 'read_page', 'kind': 'other', 'status': 'pending',
                'rawInput': {'key': 'overview'}, '_meta': {'claudeCode': {'toolName': 'mcp__openbench__read_page'}}})
        answers['claude'] = ask('session/request_permission', {'sessionId': SESSION, 'toolCall': {'toolCallId': 'c4'},
                                'options': [{'optionId': 'once', 'name': 'Allow', 'kind': 'allow_once'}]})
        update(codex_call('c5', 'codex', 'list_mcp_resources'))
        update({'sessionUpdate': 'tool_call', 'toolCallId': 'c6', 'title': 'Compacting context', 'kind': 'think', 'status': 'pending'})
        update({'sessionUpdate': 'tool_call_update', 'toolCallId': 'c1', 'status': 'completed', '_meta': {'is_mcp_tool_call': True}})
        say(json.dumps({name: answer.get('result') for name, answer in answers.items()}))
    elif SCENARIO == 'trip':
        variant = ARGS[0]
        spawn_tree(orphan=variant == 'orphan')
        if variant in ('native', 'orphan'):
            update({'sessionUpdate': 'tool_call', 'toolCallId': 't1', 'title': 'Run whoami', 'kind': 'execute',
                    'status': 'pending', 'rawInput': {'command': ['whoami']}})
        elif variant == 'claude_native':
            update({'sessionUpdate': 'tool_call', 'toolCallId': 't1', 'title': 'Bash', 'kind': 'other', 'status': 'pending',
                    '_meta': {'claudeCode': {'toolName': 'Bash'}}})
        elif variant == 'other_server':
            update(codex_call('t1', 'evil', 'read_page'))
        elif variant == 'unlisted':
            update(codex_call('t1', 'openbench', 'propose'))
        elif variant == 'update':
            update(codex_call('t1', 'openbench', 'read_page'))
            update({'sessionUpdate': 'tool_call_update', 'toolCallId': 't1', 'rawInput': {'server': 'evil'}})
        elif variant == 'permission':
            send({'id': 'p1', 'method': 'session/request_permission', 'params': {'sessionId': SESSION,
                  'toolCall': {'toolCallId': 'p1', 'kind': 'execute', 'title': 'rm -rf build'},
                  'options': [{'optionId': 'once', 'name': 'Allow', 'kind': 'allow_once'}]}})
        elif variant == 'fs':
            send({'id': 'f1', 'method': 'fs/read_text_file', 'params': {'sessionId': SESSION, 'path': '/etc/hosts'}})
        elif variant == 'terminal':
            send({'id': 'x1', 'method': 'terminal/create', 'params': {'sessionId': SESSION, 'command': 'whoami'}})
        Path('violation.sent').write_text(str(time.time()))
        time.sleep(60)
    elif SCENARIO == 'db_trip':
        child, call = mcp_client()
        update(codex_call('d1', 'openbench', 'propose_table_edit'))
        proposed = call('tools/call', {'name': 'propose_table_edit', 'arguments': {'tab_key': 'shots', 'table_id': 'b_table',
                        'row_edits': [{'row_id': 'b_shot1', 'cells': {'1': 'proposed before the trip'}}]}})
        Path('proposed.json').write_text(json.dumps(proposed))
        child.stdin.close(); child.wait(timeout=10)
        spawn_tree()
        update({'sessionUpdate': 'tool_call', 'toolCallId': 'd2', 'title': 'Run whoami', 'kind': 'execute', 'status': 'pending'})
        time.sleep(60)
    send({'id': identifier, 'result': {'stopReason': 'end_turn'}})


while True:
    message = read()
    method, identifier = message.get('method'), message.get('id')
    if method:
        state['requests'].append(method)
    if method == 'initialize':
        state['initialize'] = message['params']
        send({'id': identifier, 'result': {'protocolVersion': 1, 'agentInfo': {'name': 'lockdown-fixture', 'version': '1'},
              'authMethods': [{'id': 'api-key', 'name': 'API key'}]}})
    elif method == 'authenticate':
        send({'id': identifier, 'result': {}})
    elif method == 'session/new':
        state['session_new'] = message['params']
        send({'id': identifier, 'result': session_result()})
    elif method == 'session/set_mode':
        if ARGS[2:3] == ['notify']:
            update({'sessionUpdate': 'current_mode_update', 'currentModeId': message['params']['modeId']})
        send({'id': identifier, 'result': {}})
    elif method == 'session/set_config_option':
        send({'id': identifier, 'result': {'configOptions': [config_option(message['params']['value'])]}})
    elif method == 'session/prompt':
        prompt(identifier, message['params'])
    elif identifier is not None and method:
        send({'id': identifier, 'error': {'code': -32601, 'message': 'unsupported'}})

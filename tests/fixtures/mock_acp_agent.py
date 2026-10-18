"""Real stdio process exercising the ACP v1 wire and mounted MCP, never a model."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

MODE = sys.argv[1]

def send(message):
    raw = (json.dumps({'jsonrpc': '2.0', **message}, ensure_ascii=False) + '\n').encode()
    if MODE == 'split':
        for start in range(0, len(raw), 7):
            sys.stdout.buffer.write(raw[start:start + 7]); sys.stdout.buffer.flush()
    else:
        sys.stdout.buffer.write(raw); sys.stdout.buffer.flush()

for line in sys.stdin:
    request = json.loads(line)
    method, identifier = request.get('method'), request.get('id')
    if method == 'initialize':
        assert request['params']['protocolVersion'] == 1
        assert not request['params']['clientCapabilities'].get('terminal')
        if MODE == 'invalid':
            print('not json', flush=True); continue
        if MODE == 'oversize':
            print('x' * (1024 * 1024 + 1), flush=True); continue
        if MODE == 'eof':
            sys.exit(0)
        send({'id': identifier, 'result': {'protocolVersion': 1, 'agentInfo': {'name': 'wire-fixture', 'version': '1'}}})
    elif method == 'session/new':
        session = request['params']; assert Path(session['cwd']).is_absolute()
        assert len(session['mcpServers']) == 1
        send({'id': identifier, 'result': {'sessionId': 'fixture-session'}})
        if MODE == 'blocked_write':
            time.sleep(3)
            sys.exit(0)
    elif method == 'session/prompt':
        if MODE == 'timeout':
            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(90)'])
            Path('child.pid').write_text(str(child.pid))
            time.sleep(90)
        if MODE == 'deny':
            for index, name in enumerate(('fs/read_text_file', 'terminal/create', 'session/request_permission', 'unknown/test')):
                send({'id': 'agent-' + str(index), 'method': name, 'params': {'sessionId': 'fixture-session', 'options': []}})
                response = json.loads(sys.stdin.readline())
                assert response['id'] == 'agent-' + str(index)
                assert 'error' in response or response['result']['outcome']['outcome'] == 'cancelled'
        if MODE in ('tools','question'):
            server = session['mcpServers'][0]
            env = {**os.environ, **{item['name']: item['value'] for item in server['env']}}
            child = subprocess.Popen([server['command'], *server['args']], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env)
            def mcp(method, params):
                child.stdin.write((json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}) + '\n').encode()); child.stdin.flush()
                response = json.loads(child.stdout.readline())
                return response.get('result', response)
            specs = mcp('tools/list', {})['tools']
            if MODE=='question':
                mcp('tools/call', {'name':'ask_decision_gate','arguments':{'question':'Choose','options':['A','B']}})
                time.sleep(3)
            else:
                assert [s['name'] for s in specs] == ['read_page']
                result = mcp('tools/call', {'name': 'read_page', 'arguments': {'key': 'overview'}})
                assert result['content'][0]['text'] == 'scoped page'
                blocked = mcp('tools/call', {'name': 'propose', 'arguments': {}})
                assert 'error' in blocked
            child.terminate(); child.wait(timeout=5)
        for kind, text in [('agent_thought_chunk', 'PRIVATE REASONING'), ('agent_message_chunk', '已完成合成工作。')]:
            send({'method': 'session/update', 'params': {'sessionId': 'fixture-session', 'update': {'sessionUpdate': kind, 'content': {'type': 'text', 'text': text}}}})
        send({'id': 98765, 'result': {}})  # Unrelated response cannot complete the current request.
        send({'id': identifier, 'result': {'stopReason': 'end_turn'}})

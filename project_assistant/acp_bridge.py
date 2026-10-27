"""Bounded ACP v1 stdio client. Commands are trusted deployment config, never task input.

This controls the ACP client surface and credentials; it is not an OS sandbox for
an arbitrary executable. Use a dedicated account/container for untrusted agents.
The lock-down rules (SPEC_20 R35) live in acp_lockdown.py.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import tempfile
import threading
import contextlib

from project_assistant import acp_lockdown as lockdown, tools
from project_assistant.tool_host import ToolHost

MAX_FRAME = 1024 * 1024
MAX_TEXT = 2 * 1024 * 1024
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
ENV_KEEP = lockdown.ENV_KEEP


def clean_env(source, cwd, mode=lockdown.DEFAULT_MODE):
    return lockdown.clean_env(source, cwd, mode)


def kill_tree(proc):
    if os.name == 'nt':
        if proc.poll() is None:
            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True, timeout=10, creationflags=NO_WINDOW)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=10)


class WindowsJob:
    """A close-on-exit job retains child ownership even if the adapter exits first."""
    def __init__(self, proc):
        import ctypes as c
        from ctypes import wintypes as w
        class Basic(c.Structure):
            _fields_ = [('times', c.c_longlong * 2), ('flags', w.DWORD), ('minimum', c.c_size_t),
                ('maximum', c.c_size_t), ('active', w.DWORD), ('affinity', c.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
        class Limits(c.Structure):
            _fields_ = [('basic', Basic), ('io', c.c_ulonglong * 6), ('memory', c.c_size_t * 4)]
        self.api = c.WinDLL('kernel32', use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]; self.api.CreateJobObjectW.restype = w.HANDLE
        self.api.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
        self.api.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.api.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        self.api.CloseHandle.argtypes = [w.HANDLE]
        self.handle = self.api.CreateJobObjectW(None, None)
        limits = Limits(); limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.handle or not self.api.SetInformationJobObject(self.handle, 9, c.byref(limits), c.sizeof(limits)) or not self.api.AssignProcessToJobObject(self.handle, int(proc._handle)):
            self.close()
            raise OSError('Cannot bind ACP process to owned Windows job')
    def close(self):
        if self.handle:
            self.api.TerminateJobObject(self.handle, 1)
            self.api.CloseHandle(self.handle)
            self.handle = None


def run_acp(*, command, cwd, env, prompt, tool_proxy, deadline_at, cancel_event, required_mode=None):
    if not isinstance(command, list) or not command or any(not isinstance(arg, str) or not arg or '\0' in arg for arg in command):
        raise ValueError('ACP command must be a configured argv list')
    if Path(command[0]).suffix.lower() in ('.cmd', '.bat'):
        raise ValueError('Use an executable or node plus script, not a shell wrapper')
    mode = lockdown.required_mode(required_mode)
    root = Path(cwd).resolve()
    deadline = deadline_at if isinstance(deadline_at, dt.datetime) else dt.datetime.fromisoformat(deadline_at.replace('Z', '+00:00'))
    if deadline.tzinfo is None:
        raise ValueError('ACP deadline must include timezone')
    if cancel_event.is_set():
        return {'status': 'canceled', 'output': {}}
    blocked = lockdown.slash_command(prompt)
    if blocked:
        return lockdown.failure('slash_command', blocked)  # Refused before the agent starts.
    lockdown.prepare_folder(root)
    proc, host, job, reader = None, None, None, None
    inbox = queue.Queue(maxsize=64)
    closing = threading.Event()
    terminate_lock = threading.Lock()
    tripped = []  # The first lock-down violation; the process tree is already gone when it is recorded.
    tracked, granted = {}, set()
    state = {'session': None, 'mode': None, 'confirmed': False, 'text_size': 0}
    allowed = frozenset()
    def stop_reason():
        if tool_proxy.pending.is_set() or (host and host.pending.is_set()): return 'awaiting_gate'
        if cancel_event.is_set(): return 'canceled'
        if dt.datetime.now(dt.timezone.utc) >= deadline: return 'timeout'
        return None
    def terminate():
        with terminate_lock:
            if job: job.close()
            if proc: kill_tree(proc)
    def trip(reason, detail=''):
        """Record the first violation and kill the whole tree at once; safe from the tool host thread."""
        if not tripped:
            tripped.append(lockdown.Tripwire(reason, detail))
        terminate()
        return tripped[0]
    def watchdog():
        while not closing.wait(.05):
            if stop_reason():
                terminate()
                return
    info, chunks = {}, []
    serial = 0
    def send(message):
        raw = (json.dumps({'jsonrpc': '2.0', **message}, ensure_ascii=False) + '\n').encode()
        if len(raw) > MAX_FRAME:
            raise ValueError('ACP request exceeds frame limit')
        proc.stdin.write(raw); proc.stdin.flush()
    def read_frames():
        try:
            while not closing.is_set():
                raw = proc.stdout.readline(MAX_FRAME + 1)
                if not raw:
                    raise ValueError('ACP closed before responding')
                if len(raw) > MAX_FRAME or not raw.endswith(b'\n'):
                    raise ValueError('ACP frame exceeds limit')
                value = json.loads(raw)
                if not isinstance(value, dict) or value.get('jsonrpc') != '2.0':
                    raise ValueError('Invalid ACP envelope')
                while not closing.is_set():
                    try:
                        inbox.put(value, timeout=.1); break
                    except queue.Full:
                        continue
        except (ValueError, OSError):
            while not closing.is_set():
                try:
                    inbox.put({'_invalid': True}, timeout=.1); break
                except queue.Full:
                    continue
    def agent_request(message):
        method = message['method']
        if method == 'session/request_permission':
            # Default deny; one allow_once per announced call of an allowed openbench tool.
            result, offending = lockdown.answer_permission(message.get('params'), tracked, allowed, granted)
            if offending:
                raise trip('unexpected_tool_call', lockdown.target_label(offending))
            send({'id': message['id'], 'result': result})
        elif lockdown.client_request_is_tool(method):
            raise trip('unexpected_tool_call', method)  # We never offered files or a terminal.
        else:
            send({'id': message['id'], 'error': {'code': -32601, 'message': 'Client capability unavailable'}})
    def session_update(params):
        update = params.get('update') if isinstance(params.get('update'), dict) else {}
        kind = update.get('sessionUpdate')
        if kind in ('tool_call', 'tool_call_update'):
            _, target = lockdown.track_tool_call(update, tracked)
            if not lockdown.tool_allowed(target, allowed):
                raise trip('unexpected_tool_call', lockdown.target_label(target))
        elif kind in ('current_mode_update', 'config_option_update'):
            current = update.get('currentModeId') if kind == 'current_mode_update' else lockdown.session_mode(update)[0]
            if isinstance(current, str):
                state['mode'] = current
                if state['confirmed'] and current != mode:
                    raise trip('mode_changed', current)
        elif kind == 'agent_message_chunk' and params.get('sessionId') == state['session']:
            content = update.get('content') or {}
            if content.get('type') == 'text':
                chunks.append(str(content.get('text', '')))
                state['text_size'] += len(chunks[-1].encode('utf-8'))
                if state['text_size'] > MAX_TEXT:
                    raise ValueError('ACP answer exceeds limit')
    def request(method, params):
        nonlocal serial
        serial += 1
        identifier = serial
        send({'id': identifier, 'method': method, 'params': params})
        while True:
            if tripped:
                raise tripped[0]
            if tool_proxy.pending.is_set() or (host and host.pending.is_set()):
                raise InterruptedError('awaiting_gate')
            if cancel_event.is_set():
                raise InterruptedError('canceled')
            if dt.datetime.now(dt.timezone.utc) >= deadline:
                raise TimeoutError()
            try:
                message = inbox.get(timeout=.05)
            except queue.Empty:
                continue
            if message.get('_invalid'):
                if tripped:
                    raise tripped[0]
                raise ValueError('Invalid ACP response or unexpected EOF')
            if 'method' in message:
                if 'id' in message:
                    agent_request(message)
                elif message['method'] == 'session/update' and isinstance(message.get('params'), dict):
                    session_update(message['params'])
                continue
            if message.get('id') != identifier:
                continue
            if 'error' in message:
                raise ValueError('ACP request failed')  # Raw errors can echo secrets.
            if not isinstance(message.get('result'), dict):
                raise ValueError('Invalid ACP result')
            return message['result']
    def confirm_mode(session_id, created):
        """Work is sent only once the agent reports the required mode (set it once if it offers it)."""
        current, how, available = lockdown.session_mode(created)
        if current is not None:
            state['mode'] = current
        if state['mode'] != mode and how and mode in available:
            if how[0] == 'config':
                reported = lockdown.session_mode(request('session/set_config_option',
                    {'sessionId': session_id, 'configId': how[1], 'value': mode}))[0]
                if reported is not None:
                    state['mode'] = reported
            else:
                state['mode'] = None  # Only the agent's own current_mode_update confirms the switch.
                request('session/set_mode', {'sessionId': session_id, 'modeId': mode})
        if state['mode'] != mode:
            raise lockdown.Tripwire('mode_mismatch', state['mode'] or 'none reported')
        state['confirmed'] = True
    def call_tool(name, args):
        if tripped:
            raise tools.ToolError('POLICY_DENIED: This ACP turn has stopped.')
        if name not in allowed:
            trip('unexpected_tool_call', f'{lockdown.SERVER_NAME}/{name}')
            raise tools.ToolError("POLICY_DENIED: This tool is not on the turn's allowed list.")
        return tool_proxy.call(name, args)
    try:
        allowed = lockdown.turn_allowlist(tool_proxy.list_tools())  # Frozen for the whole turn.
        child_env = lockdown.clean_env(env, str(root), mode)
        proc = subprocess.Popen(command, cwd=str(root), env=child_env, shell=False, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW, start_new_session=os.name != 'nt')
        if os.name == 'nt':
            job = WindowsJob(proc)
        monitor = threading.Thread(target=watchdog, daemon=True); monitor.start()
        reader = threading.Thread(target=read_frames, daemon=True); reader.start()
        initialized = request('initialize', lockdown.initialize_params())
        if initialized.get('protocolVersion') != 1:
            raise ValueError('ACP protocol version is unsupported')
        info = initialized.get('agentInfo') or {}
        if child_env.get('OPENAI_API_KEY') and any(method.get('id') == 'api-key' for method in initialized.get('authMethods', [])):
            request('authenticate', {'methodId': 'api-key'})
        host = ToolHost(list_tools=lambda: [s for s in tool_proxy.list_tools() if isinstance(s, dict) and s.get('name') in allowed],
                        call_tool=call_tool)
        url, token = host.start()
        created = request('session/new', {'cwd': str(root), 'mcpServers': lockdown.mcp_servers(url, token)})
        session_id = created.get('sessionId')
        if not isinstance(session_id, str) or not session_id:
            raise ValueError('ACP session id is missing')
        state['session'] = session_id
        confirm_mode(session_id, created)
        result = request('session/prompt', {'sessionId': session_id, 'prompt': [{'type': 'text', 'text': prompt}]})
        if result.get('stopReason') != 'end_turn':
            raise ValueError('ACP did not complete the turn')
        text = ''.join(chunks)
        return {'status': 'succeeded', 'output': {'text': text}, 'agent_info': info}
    except lockdown.Tripwire as exc:
        terminate()
        return lockdown.failure(exc.reason, exc.detail, agent_info=info)
    except InterruptedError as exc:
        return {'status': str(exc), 'output': {}, 'agent_info': info}
    except TimeoutError:
        return {'status': 'timeout', 'output': {}, 'error': 'ACP deadline exceeded'}
    except (OSError, ValueError, subprocess.SubprocessError):
        if tripped:
            return lockdown.failure(tripped[0].reason, tripped[0].detail, agent_info=info)
        reason = stop_reason()
        if reason:
            return {'status': reason, 'output': {}, 'agent_info': info}
        return {'status': 'failed', 'output': {}, 'error': 'ACP protocol or process failed'}
    finally:
        closing.set()
        if proc:
            if state['session'] and proc.poll() is None:
                try:
                    send({'method': 'session/cancel', 'params': {'sessionId': state['session']}})
                except (OSError, ValueError):
                    pass
            terminate()
            if reader: reader.join(timeout=2)
            for pipe in (proc.stdin, proc.stdout):
                if pipe:
                    with contextlib.suppress(OSError): pipe.close()
        if host: host.stop()


def list_turn_tools(views, *, timeout=30):
    """Tool names each ACP turn would see through the real openbench mount, without an agent or a model.

    `views` maps a key to a list_tools callable (the Head's specs for that turn). One mcp_stdio server is
    started exactly as session/new mounts it, with the agent's scrubbed environment, and asked tools/list
    once per view (SPEC_20 R35 offline listing; scripts/audit_tool_surface.py)."""
    current = {}
    def listed():
        specs = current['list']()
        allowed = lockdown.turn_allowlist(specs)
        return [s for s in specs if isinstance(s, dict) and s.get('name') in allowed]
    def refuse(name, args):
        raise tools.ToolError('POLICY_DENIED: Offline listing never calls tools.')
    host = ToolHost(list_tools=listed, call_tool=refuse)
    url, token = host.start()
    names = {}
    try:
        with tempfile.TemporaryDirectory(prefix='openbench-acp-audit-') as folder:
            [server] = lockdown.mcp_servers(url, token)
            env = lockdown.clean_env({k: v for k, v in os.environ.items() if k.upper() in lockdown.ENV_KEEP}, folder)
            env.update({item['name']: item['value'] for item in server['env']})
            proc = subprocess.Popen([server['command'], *server['args']], cwd=folder, env=env, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
            timer = threading.Timer(timeout, proc.kill)
            timer.start()
            def call(identifier, method, params):
                proc.stdin.write((json.dumps({'jsonrpc': '2.0', 'id': identifier, 'method': method, 'params': params}) + '\n').encode())
                proc.stdin.flush()
                while True:
                    raw = proc.stdout.readline()
                    if not raw:
                        raise RuntimeError('The openbench MCP server closed during the offline listing.')
                    message = json.loads(raw)
                    if message.get('id') == identifier:
                        if 'error' in message:
                            raise RuntimeError(f'tools/list failed: {message["error"]}')
                        return message['result']
            try:
                call(1, 'initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                       'clientInfo': {'name': 'openbench-audit', 'version': '1'}})
                proc.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
                for identifier, (key, list_tools) in enumerate(views.items(), start=2):
                    current['list'] = list_tools
                    names[key] = [tool['name'] for tool in call(identifier, 'tools/list', {})['tools']]
            finally:
                timer.cancel()
                with contextlib.suppress(OSError):
                    proc.stdin.close()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait(timeout=10)
                with contextlib.suppress(OSError):
                    proc.stdout.close()
    finally:
        host.stop()
    return names

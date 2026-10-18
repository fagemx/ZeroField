"""Bounded ACP v1 stdio client. Commands are trusted deployment config, never task input.

This controls the ACP client surface and credentials; it is not an OS sandbox for
an arbitrary executable. Use a dedicated account/container for untrusted agents.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time
import contextlib

from project_assistant.tool_host import ToolHost

MAX_FRAME = 1024 * 1024
MAX_TEXT = 2 * 1024 * 1024
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
ENV_KEEP = {'SYSTEMROOT', 'WINDIR', 'PATH', 'PATHEXT', 'COMSPEC', 'TEMP', 'TMP', 'LANG', 'LC_ALL', 'TZ', 'SSL_CERT_FILE', 'CODEX_PATH', 'MODEL_PROVIDER'}


def clean_env(source, cwd):
    env = {key: str(value) for key, value in source.items() if key.upper() in ENV_KEEP}
    root = Path(cwd)
    for name in ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA'):
        env[name] = str(root)
    env.update(CODEX_HOME=str(root / '.codex'), NO_BROWSER='1', INITIAL_AGENT_MODE='read-only', PYTHONIOENCODING='utf-8')
    # Only the explicitly configured adapter credential is mapped, never the
    # worker's ambient provider credentials or Head bearer/DB URI.
    if source.get('ACP_MODEL_API_KEY'):
        env['OPENAI_API_KEY'] = str(source['ACP_MODEL_API_KEY'])
    configured = json.loads(source.get('CODEX_CONFIG') or '{}')
    safe = {key: value for key, value in configured.items() if key in ('model', 'model_provider', 'model_providers', 'model_reasoning_effort')}
    from project_assistant.codex_runner import DISABLE
    safe.update(approval_policy='never', sandbox_mode='read-only', web_search='disabled',
        features={name: False for name in DISABLE})
    env['CODEX_CONFIG'] = json.dumps(safe)
    return env


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


def run_acp(*, command, cwd, env, prompt, tool_proxy, deadline_at, cancel_event):
    if not isinstance(command, list) or not command or any(not isinstance(arg, str) or not arg or '\0' in arg for arg in command):
        raise ValueError('ACP command must be a configured argv list')
    if Path(command[0]).suffix.lower() in ('.cmd', '.bat'):
        raise ValueError('Use an executable or node plus script, not a shell wrapper')
    root = Path(cwd).resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / '.codex').mkdir(exist_ok=True)
    deadline = deadline_at if isinstance(deadline_at, dt.datetime) else dt.datetime.fromisoformat(deadline_at.replace('Z', '+00:00'))
    if deadline.tzinfo is None:
        raise ValueError('ACP deadline must include timezone')
    proc, host, job, reader = None, None, None, None
    inbox = queue.Queue(maxsize=64)
    closing = threading.Event()
    terminate_lock = threading.Lock()
    def stop_reason():
        if tool_proxy.pending.is_set() or (host and host.pending.is_set()): return 'awaiting_gate'
        if cancel_event.is_set(): return 'canceled'
        if dt.datetime.now(dt.timezone.utc) >= deadline: return 'timeout'
        return None
    def terminate():
        with terminate_lock:
            if job: job.close()
            kill_tree(proc)
    def watchdog():
        while not closing.wait(.05):
            if stop_reason():
                terminate()
                return
    info, session_id, chunks = {}, None, []
    serial, text_size = 0, 0
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
    def request(method, params):
        nonlocal serial, text_size
        serial += 1
        identifier = serial
        send({'id': identifier, 'method': method, 'params': params})
        while True:
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
                raise ValueError('Invalid ACP response or unexpected EOF')
            if 'method' in message:
                if 'id' in message:
                    # Never grant the agent host file, terminal, or native approval.
                    result = {'outcome': {'outcome': 'cancelled'}} if message['method'] == 'session/request_permission' else None
                    send({'id': message['id'], **({'result': result} if result else {'error': {'code': -32601, 'message': 'Client capability unavailable'}})})
                elif message['method'] == 'session/update':
                    params = message.get('params') or {}
                    update = params.get('update') or {}
                    content = update.get('content') or {}
                    if params.get('sessionId') == session_id and update.get('sessionUpdate') == 'agent_message_chunk' and content.get('type') == 'text':
                        chunks.append(str(content.get('text', '')))
                        text_size += len(chunks[-1].encode('utf-8'))
                        if text_size > MAX_TEXT:
                            raise ValueError('ACP answer exceeds limit')
                continue
            if message.get('id') != identifier:
                continue
            if 'error' in message:
                raise ValueError('ACP request failed')  # Raw errors can echo secrets.
            if not isinstance(message.get('result'), dict):
                raise ValueError('Invalid ACP result')
            return message['result']
    try:
        if cancel_event.is_set():
            return {'status': 'canceled', 'output': {}}
        child_env = clean_env(env, str(root))
        proc = subprocess.Popen(command, cwd=str(root), env=child_env, shell=False, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW, start_new_session=os.name != 'nt')
        if os.name == 'nt':
            job = WindowsJob(proc)
        monitor = threading.Thread(target=watchdog, daemon=True); monitor.start()
        reader = threading.Thread(target=read_frames, daemon=True); reader.start()
        initialized = request('initialize', {'protocolVersion': 1, 'clientCapabilities': {'fs': {'readTextFile': False, 'writeTextFile': False}, 'terminal': False},
            'clientInfo': {'name': 'openbench', 'version': '1'}})
        if initialized.get('protocolVersion') != 1:
            raise ValueError('ACP protocol version is unsupported')
        info = initialized.get('agentInfo') or {}
        if child_env.get('OPENAI_API_KEY') and any(method.get('id') == 'api-key' for method in initialized.get('authMethods', [])):
            request('authenticate', {'methodId': 'api-key'})
        host = ToolHost(list_tools=tool_proxy.list_tools, call_tool=tool_proxy.call)
        url, token = host.start()
        created = request('session/new', {'cwd': str(root), 'mcpServers': [{'name': 'openbench', 'command': sys.executable,
            'args': ['-X', 'utf8', str(Path(__file__).with_name('mcp_stdio.py'))],
            'env': [{'name': 'PA_TOOL_URL', 'value': url}, {'name': 'PA_TOKEN', 'value': token}]}]})
        session_id = created.get('sessionId')
        if not isinstance(session_id, str) or not session_id:
            raise ValueError('ACP session id is missing')
        result = request('session/prompt', {'sessionId': session_id, 'prompt': [{'type': 'text', 'text': prompt}]})
        if result.get('stopReason') != 'end_turn':
            raise ValueError('ACP did not complete the turn')
        text = ''.join(chunks)
        return {'status': 'succeeded', 'output': {'text': text}, 'agent_info': info}
    except InterruptedError as exc:
        return {'status': str(exc), 'output': {}, 'agent_info': info}
    except TimeoutError:
        return {'status': 'timeout', 'output': {}, 'error': 'ACP deadline exceeded'}
    except (OSError, ValueError, subprocess.SubprocessError):
        reason = stop_reason()
        if reason:
            return {'status': reason, 'output': {}, 'agent_info': info}
        return {'status': 'failed', 'output': {}, 'error': 'ACP protocol or process failed'}
    finally:
        closing.set()
        if proc:
            if session_id and proc.poll() is None:
                try:
                    send({'method': 'session/cancel', 'params': {'sessionId': session_id}})
                except (OSError, ValueError):
                    pass
            terminate()
            if reader: reader.join(timeout=2)
            for pipe in (proc.stdin, proc.stdout):
                if pipe:
                    with contextlib.suppress(OSError): pipe.close()
        if host: host.stop()

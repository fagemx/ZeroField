"""Cross-process GPU arbiter (SPEC_20 R13).

LTX-2.5 and a local 27B language model do not fit on one 24 GB GPU together, so every process that uses a GPU this
deployment owns — the server, the assistant worker, media/limb workers — takes one lock per GPU host before using it:
local ComfyUI renders, continuity grading and local model calls (agent turns, the Quickstart builder).

- **Lock:** a PostgreSQL session-level advisory lock keyed by the GPU host (all loopback endpoints share ``gpu:local``;
  a LAN ComfyUI host gets ``gpu:<host>``), held on a dedicated autocommit connection. A holder that dies closes its
  session and the lock goes with it; TCP keepalives bound a vanished peer. Without a configured database (a standalone
  worker or a unit test) the lock is process-local.
- **Waits** are bounded by the caller's deadline (a turn's remaining time, a render's timeout) and can be canceled;
  a timeout raises :class:`GpuBusy` and leaves nothing held.
- **Phases:** the arbiter remembers which workload is resident on the GPU (the language model or ComfyUI). Consecutive
  model calls (planning, chat, grading rounds) never unload the model; only a change of workload switches owners —
  ``keep_alive: 0`` for the resident models before a render, ComfyUI ``/free`` (after its queue drains, then waiting for
  the VRAM) before a model call. Switching side effects run only where a launcher enabled them
  (:func:`enable_switching`, ``OPENBENCH_GPU_SWITCHING=on``) so library and test use never touches a real GPU service;
  a caller may pass its own switch action instead (the continuity grader frees its configured ComfyUI).

:func:`status` is the read-only view for the console's GPU panel: owner, waiters and since when, per GPU host.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import threading
import time
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

LLM, COMFY, OTHER = 'llm', 'comfy', 'other'
LOCAL_KEY = 'gpu:local'
SWITCHING_ENV = 'OPENBENCH_GPU_SWITCHING'
HOSTS_ENV = 'OPENBENCH_GPU_HOSTS'  # extra comma-separated hosts whose GPU this deployment owns
STATE_SLUG = '*gpu'  # machine-level rows in projectops.assistant_setting; never a production slug
STATE_PREFIX = 'gpu_state:'
APP = 'zf-gpu'
SLICE = 2.0  # longest single lock wait between cancellation checks
FREE_TARGET = 0.75  # wait until this share of VRAM is free after ComfyUI /free (calibrate per card)
CONNECT = None  # optional connection factory override; default: the server database when one is configured

_registry = threading.Lock()
_local_locks: dict[str, threading.Lock] = {}
_holders: dict[str, dict] = {}
_waiters: dict[str, dict[int, dict]] = {}
_memory: dict[str, dict] = {}
_tls = threading.local()


class GpuBusy(TimeoutError):
    """The GPU stayed busy past the caller's deadline (or the wait was canceled); nothing is held."""


def _now():
    return datetime.now(timezone.utc).isoformat()


def switching_enabled():
    return os.environ.get(SWITCHING_ENV, '').strip().lower() in ('1', 'on', 'true', 'yes')


def enable_switching():
    """Launchers call this while they serve: owner switches may then free ComfyUI and unload resident models (an
    explicit OPENBENCH_GPU_SWITCHING=off stays off). Returns a callable that restores the previous setting."""
    previous = os.environ.get(SWITCHING_ENV)
    os.environ.setdefault(SWITCHING_ENV, 'on')

    def restore():
        if previous is None:
            os.environ.pop(SWITCHING_ENV, None)
        else:
            os.environ[SWITCHING_ENV] = previous
    return restore


def _loopback(host):
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def gpu_key(url):
    """The lock key of the GPU machine behind url, or None for a GPU this deployment does not own (a hosted service)."""
    try:
        host = (urlsplit(url or '').hostname or '').lower()
    except (ValueError, TypeError, AttributeError):
        return None
    if not host:
        return None
    if host == 'localhost' or _loopback(host):
        return LOCAL_KEY
    extra = {h.strip().lower() for h in os.environ.get(HOSTS_ENV, '').split(',') if h.strip()}
    try:
        private = ipaddress.ip_address(host).is_private
    except ValueError:
        private = '.' not in host or host.endswith(('.local', '.lan', '.internal', '.home.arpa'))
    return 'gpu:' + host if host in extra or private else None


def _clean(url):
    """scheme://host:port/path of an endpoint, without credentials, query or fragment."""
    parts = urlsplit(url)
    host = parts.hostname or ''
    netloc = ('[' + host + ']' if ':' in host else host) + (':%d' % parts.port if parts.port else '')
    return urlunsplit((parts.scheme, netloc, parts.path.rstrip('/'), '', ''))


def _label(value):
    return re.sub(r'[^A-Za-z0-9_.:@-]', '_', str(value or ''))[:40]


def _tag(key):
    return key if len(key) <= 30 else 'gpu#' + hashlib.sha1(key.encode()).hexdigest()[:12]


def _app_name(phase, workload, key, label):
    return '|'.join((APP, phase, workload, _tag(key), _label(label)))[:63]


def _connector():
    if CONNECT is not None:
        return CONNECT
    from project_docs import http
    if http._CONN_FACTORY is not None or any(os.environ.get(n) for n in ('OPENBENCH_DB_URI', 'DATABASE_URL', 'OPENBENCH_DB_HOST')):
        return http.open_connection
    return None


def _held():
    held = getattr(_tls, 'held', None)
    if held is None:
        held = _tls.held = {}
    return held


def held_in_process(key=LOCAL_KEY):
    with _registry:
        return key in _holders


class _Holder:
    """One real hold of a GPU key by this thread; nested acquisitions share it."""

    def __init__(self, key, mode, *, conn=None, number=None, lock=None, backend=None):
        self.key, self.mode, self.conn, self.number, self.lock, self.backend = key, mode, conn, number, lock, backend
        self.depth = 1

    def leave(self):
        self.depth -= 1
        if self.depth > 0:
            return
        _held().pop(self.key, None)
        with _registry:
            _holders.pop(self.key, None)
        try:
            state = _load(self)
            if state.get('owner'):
                _store(self, {**state, 'owner': None})
        finally:
            if self.mode == 'database':
                try:
                    self.conn.execute('SELECT pg_advisory_unlock(%s::bigint)', (self.number,))
                except Exception:
                    pass  # closing the session releases it anyway
                finally:
                    self.conn.close()
            else:
                self.lock.release()


class Grant:
    """A hold of one GPU for one workload. ``previous`` is what was resident before; ``switched`` says the workload
    changed (only then were switch actions run, their result is ``switch``); ``waited`` says another holder came first."""

    def __init__(self, holder, workload, previous, switched, waited, switch):
        self._holder, self.key, self.workload = holder, holder.key, workload
        self.previous, self.switched, self.waited, self.switch = previous, switched, waited, switch
        self._released = False

    def release(self):
        if not self._released:
            self._released = True
            self._holder.leave()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()


def _load(holder):
    if holder.mode == 'database':
        try:
            row = holder.conn.execute('SELECT value FROM projectops.assistant_setting WHERE project_slug=%s AND key=%s',
                                      (STATE_SLUG, STATE_PREFIX + holder.key)).fetchone()
            value = json.loads(row[0]) if row else {}
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}
    with _registry:
        return dict(_memory.get(holder.key) or {})


def _store(holder, state):
    if holder.mode == 'database':
        try:
            holder.conn.execute("""INSERT INTO projectops.assistant_setting (project_slug, key, value) VALUES (%s, %s, %s)
                ON CONFLICT (project_slug, key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()""",
                                (STATE_SLUG, STATE_PREFIX + holder.key, json.dumps(state)))
        except Exception:
            pass  # bookkeeping only: an unknown resident workload makes the next switch conservative
        return
    with _registry:
        _memory[holder.key] = state


def _wait_register(key, workload, label):
    token = object()
    with _registry:
        _waiters.setdefault(key, {})[id(token)] = {'workload': workload, 'label': _label(label), 'since': _now()}
    return token


def _wait_unregister(key, token):
    with _registry:
        _waiters.get(key, {}).pop(id(token), None)
        if not _waiters.get(key):
            _waiters.pop(key, None)


def _busy(key, canceled=False):
    where = 'local GPU' if key == LOCAL_KEY else 'GPU on ' + key.split(':', 1)[1]
    return GpuBusy(('Waiting for the %s was canceled.' if canceled else
                    'The %s stayed busy with another workload; retry once it finishes.') % where)


def _enter_process(key, workload, label, deadline, cancelled, on_wait):
    with _registry:
        lock = _local_locks.setdefault(key, threading.Lock())
    if lock.acquire(blocking=False):
        return _Holder(key, 'process', lock=lock), False
    token = _wait_register(key, workload, label)
    try:
        if on_wait:
            on_wait()
        while True:
            left = deadline - time.monotonic()
            if cancelled and cancelled():
                raise _busy(key, canceled=True)
            if left <= 0:
                raise _busy(key)
            if lock.acquire(timeout=min(left, SLICE)):
                return _Holder(key, 'process', lock=lock), True
    finally:
        _wait_unregister(key, token)


def _enter_database(connect, key, workload, label, deadline, cancelled, on_wait):
    import psycopg
    try:
        conn = connect()
    except Exception:
        return None  # the database is unreachable: fall back to the process-local lock
    try:
        conn.autocommit = True
        conn.execute("SELECT set_config('application_name', %s, false)", (_app_name('wait', workload, key, label),))
        for name, value in (('tcp_keepalives_idle', '30'), ('tcp_keepalives_interval', '10'), ('tcp_keepalives_count', '3')):
            try:
                conn.execute('SELECT set_config(%s, %s, false)', (name, value))
            except psycopg.Error:
                pass  # unsupported on this platform or socket type
        number, backend = conn.execute('SELECT hashtextextended(%s, 0), pg_backend_pid()', (key,)).fetchone()
    except psycopg.Error:
        conn.close()
        return None
    token, waited = None, False
    try:
        if not conn.execute('SELECT pg_try_advisory_lock(%s::bigint)', (number,)).fetchone()[0]:
            waited, token = True, _wait_register(key, workload, label)
            if on_wait:
                on_wait()
            while True:
                left = deadline - time.monotonic()
                if cancelled and cancelled():
                    raise _busy(key, canceled=True)
                if left <= 0:
                    raise _busy(key)
                conn.execute("SELECT set_config('lock_timeout', %s, false)", ('%dms' % max(1, int(min(left, SLICE) * 1000)),))
                try:
                    conn.execute('SELECT pg_advisory_lock(%s::bigint)', (number,))
                    break
                except (psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled):
                    continue
        conn.execute("SELECT set_config('lock_timeout', '5s', false)")
        conn.execute("SELECT set_config('application_name', %s, false)", (_app_name('hold', workload, key, label),))
        return _Holder(key, 'database', conn=conn, number=number, backend=backend), waited
    except GpuBusy:
        conn.close()
        raise
    except psycopg.Error:
        conn.close()
        raise GpuBusy('The GPU arbiter lost its database connection; retry shortly.') from None
    except BaseException:
        conn.close()
        raise
    finally:
        if token is not None:
            _wait_unregister(key, token)


def _next_state(previous, workload, url, model):
    if workload == OTHER:
        return {k: v for k, v in previous.items() if k != 'owner'}
    same = previous.get('workload') == workload
    state = {'workload': workload, 'since': previous.get('since') if same and previous.get('since') else _now()}
    if workload == LLM:
        models = [m for m in (previous.get('llm') or []) if isinstance(m, dict)] if same else []
        entry = {'base_url': _clean(url), 'model': str(model or '')}
        if entry['model'] and entry not in models:
            models.append(entry)
        state['llm'] = models[-8:]
    else:
        state['comfy'] = _clean(url)
    return state


def _default_switch(previous, workload, deadline):
    if workload == LLM and previous.get('workload') == COMFY and previous.get('comfy'):
        return {'comfy': free_comfy(previous['comfy'], timeout=max(0.0, deadline - time.monotonic()))}
    if workload == COMFY and previous.get('workload') == LLM:
        return {'unloaded': [m['model'] for m in previous.get('llm') or []
                             if isinstance(m, dict) and unload_model(m.get('base_url', ''), m.get('model', ''))]}
    return None


def acquire(workload, url, *, model=None, label='', timeout=60.0, cancelled=None, on_wait=None, on_switch=None):
    """Hold the GPU behind url for one workload (LLM, COMFY or OTHER) until Grant.release().

    Waits at most timeout seconds (GpuBusy after), calling on_wait once if it has to wait and cancelled() between
    slices. Re-entrant per thread. When the resident workload differs, on_switch(previous) runs if given, else the
    default switch when switching is enabled; a failing switch releases the GPU and propagates.
    """
    key = gpu_key(url)
    if key is None:
        raise ValueError('This endpoint is not on a GPU this deployment owns.')
    deadline = time.monotonic() + max(0.0, float(timeout))
    held = _held()
    holder, waited = held.get(key), False
    if holder is not None:
        holder.depth += 1
    else:
        connect = _connector()
        entered = _enter_database(connect, key, workload, label, deadline, cancelled, on_wait) if connect else None
        holder, waited = entered or _enter_process(key, workload, label, deadline, cancelled, on_wait)
        held[key] = holder
        with _registry:
            _holders[key] = {'workload': workload, 'label': _label(label), 'since': _now(), 'mode': holder.mode}
    try:
        previous = _load(holder)
        switched = workload != OTHER and previous.get('workload') != workload
        result = None
        if switched:
            if on_switch is not None:
                result = on_switch(previous)
            elif switching_enabled():
                result = _default_switch(previous, workload, deadline)
        state = _next_state(previous, workload, url, model)
        state['owner'] = {'workload': workload, 'label': _label(label), 'since': _now(), 'backend': holder.backend}
        _store(holder, state)
    except BaseException:
        holder.leave()
        raise
    return Grant(holder, workload, {k: v for k, v in previous.items() if k != 'owner'}, switched, waited, result)


def hold(workload, url, **options):
    """acquire() as a context manager."""
    return acquire(workload, url, **options)


def render(base_url, *, label='render', timeout=1800, cancelled=None):
    """Grant for a ComfyUI render on a GPU this deployment owns, or None (Comfy Cloud and other hosted runners)."""
    if gpu_key(base_url) is None:
        return None
    return acquire(COMFY, base_url, label=label, timeout=timeout, cancelled=cancelled)


class _HeldResponse:
    def __init__(self, response, grant):
        self._response, self._grant = response, grant

    def __enter__(self):
        return self._response.__enter__()

    def __exit__(self, *exc):
        try:
            return self._response.__exit__(*exc)
        finally:
            self._grant.release()

    def __getattr__(self, name):
        return getattr(self._response, name)


def gate(opener, config, *, label=None):
    """Wrap a model-call opener so each round holds the local GPU while its HTTP call runs.

    Only loopback model endpoints share this machine's GPU; any other endpoint passes straight through. The GPU wait
    spends the round's own timeout (so it respects the turn deadline) and a timeout surfaces as TimeoutError.
    """
    if gpu_key(config.base_url) != LOCAL_KEY:
        return opener

    def gated(request, timeout):
        started = time.monotonic()
        grant = acquire(LLM, config.base_url, model=config.model, label=label or 'model:' + config.model, timeout=timeout)
        try:
            response = opener(request, timeout=max(.1, timeout - (time.monotonic() - started)))
        except BaseException:
            grant.release()
            raise
        return _HeldResponse(response, grant)
    return gated


class CompatLock:
    """Stand-in for the old process-local ``take_grader.GPU_LOCK``: a lock-shaped hold of the local GPU through the
    arbiter (workload OTHER: no owner switch). ``locked()`` says whether this process holds the local GPU."""

    def __init__(self, url='http://127.0.0.1'):
        self.url = url
        self._stack = threading.local()

    def acquire(self, blocking=True, timeout=-1):
        wait = 0 if not blocking else (timeout if timeout is not None and timeout >= 0 else 86400)
        try:
            grant = acquire(OTHER, self.url, label='legacy', timeout=wait)
        except GpuBusy:
            return False
        stack = getattr(self._stack, 'grants', None)
        if stack is None:
            stack = self._stack.grants = []
        stack.append(grant)
        return True

    def release(self):
        stack = getattr(self._stack, 'grants', None)
        if not stack:
            raise RuntimeError('release unlocked lock')
        stack.pop().release()

    def locked(self):
        return held_in_process(gpu_key(self.url))

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()


def _http(url, body=None, timeout=10):
    request = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw) if raw.strip() else {}


def free_comfy(comfy, *, on_wait=None, timeout=3600, poll=5, opener=None, sleep=time.sleep):
    """Wait for ComfyUI's queue to empty (never interrupt a render), then POST /free and wait for the VRAM."""
    opener = opener or _http
    comfy = comfy.rstrip('/')
    deadline, waited = time.monotonic() + timeout, False
    while True:
        try:
            queue = opener(comfy + '/queue')
        except OSError:
            return {'comfyFreed': False, 'comfyOnline': False}  # nothing of ComfyUI's holds the GPU
        if not queue.get('queue_running') and not queue.get('queue_pending'):
            break
        if time.monotonic() > deadline:
            raise GpuBusy('ComfyUI stayed busy; retry once the renders finish.')
        if not waited and on_wait:
            on_wait()
        waited = True
        sleep(poll)
    opener(comfy + '/free', {'unload_models': True, 'free_memory': True})
    free = None
    for _ in range(20):
        try:
            device = opener(comfy + '/system_stats')['devices'][0]
            free = device['vram_free'] / max(device['vram_total'], 1)
        except (OSError, KeyError, IndexError, TypeError, ValueError):
            break
        if free >= FREE_TARGET or time.monotonic() > deadline:
            break
        sleep(1)
    return {'comfyFreed': True, 'comfyOnline': True, 'waitedForRenders': waited,
            **({'vramFree': round(free, 2)} if free is not None else {})}


def unload_model(base_url, model, opener=None):
    """keep_alive 0 on an Ollama-style loopback endpoint; other endpoints manage their own memory."""
    if gpu_key(base_url) != LOCAL_KEY or not model:
        return False
    opener = opener or _http
    root = re.sub(r'/v1/?$', '', base_url.rstrip('/'))
    try:
        opener(root + '/api/generate', {'model': model, 'keep_alive': 0}, 30)
        return True
    except (OSError, ValueError):
        return False


def _public(info):
    return {'workload': info.get('workload'), 'label': info.get('label'), 'since': info.get('since')}


def _resident(state):
    if not state or not state.get('workload'):
        return None
    return {'workload': state['workload'], 'since': state.get('since'),
            'models': [m.get('model') for m in state.get('llm') or [] if isinstance(m, dict)],
            **({'comfy': state['comfy']} if state.get('comfy') else {})}


def status(connect=None):
    """Read-only arbiter view per GPU host: current owner, waiters (oldest first), resident workload, since when.

    With a database it covers every process using it; otherwise this process only. Returns no credentials.
    """
    connect = connect if connect is not None else _connector()
    with _registry:
        holders = {k: dict(v) for k, v in _holders.items()}
        waiters = {k: [dict(w) for w in v.values()] for k, v in _waiters.items()}
        memory = {k: dict(v) for k, v in _memory.items()}
    gpus = {}

    def gpu(key):
        return gpus.setdefault(key, {'key': key, 'owner': None, 'waiters': [], 'resident': None})
    result = {'mode': 'process', 'switching': switching_enabled()}
    rows = states = None
    if connect is not None:
        try:
            conn = connect()
            try:
                rows = conn.execute("""SELECT pid, application_name, backend_start FROM pg_stat_activity
                    WHERE datname=current_database() AND application_name LIKE %s ORDER BY backend_start""", (APP + '|%',)).fetchall()
                states = conn.execute('SELECT key, value FROM projectops.assistant_setting WHERE project_slug=%s AND key LIKE %s',
                                      (STATE_SLUG, STATE_PREFIX + '%')).fetchall()
            finally:
                conn.rollback()
                conn.close()
            result['mode'] = 'database'
        except Exception:
            result['error'] = 'database_unavailable'
    for key, info in holders.items():
        if info.get('mode') == 'process' or rows is None:
            gpu(key)['owner'] = _public(info)
    if rows is None:
        for key, items in waiters.items():
            gpu(key)['waiters'] = sorted((_public(w) for w in items), key=lambda w: w['since'])
        for key, state in memory.items():
            gpu(key)['resident'] = _resident(state)
    else:
        parsed = {}
        for key, raw in states:
            key = key[len(STATE_PREFIX):]
            try:
                parsed[key] = json.loads(raw)
            except ValueError:
                parsed[key] = {}
            gpu(key)['resident'] = _resident(parsed[key])
        tags = {_tag(key): key for key in [*parsed, *holders, *waiters, LOCAL_KEY]}
        for pid, name, started in rows:
            parts = name.split('|', 4)
            if len(parts) < 4:
                continue
            key = tags.get(parts[3], parts[3])
            entry = {'workload': parts[2], 'label': parts[4] if len(parts) > 4 else '',
                     'since': started.isoformat() if started else None}
            if parts[1] == 'hold':
                owner = (parsed.get(key) or {}).get('owner') or {}
                if owner.get('backend') == pid and owner.get('since'):
                    entry['since'] = owner['since']
                gpu(key)['owner'] = entry
            elif parts[1] == 'wait':
                gpu(key)['waiters'].append(entry)
    result['gpus'] = sorted(gpus.values(), key=lambda g: g['key'])
    return result

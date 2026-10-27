"""The 3D Stage's own plan code in a headless browser (SPEC_20 R27, R28; decision 6).

The previs solver and renderer are JavaScript (``ui/src/previs/ops.js``, ``previsRender.js`` over ``plan.js``,
``blocking.js``, ``scene.js``); they are never rewritten in Python, and the server does not need Node. This module
starts a Chromium-family browser (Microsoft Edge on Windows by default; ``ZEROFIELD_PREVIS_BROWSER`` names another,
``off`` disables it), opens the build's ``previs-solver.html`` and calls its ``window.zfPrevis`` over the DevTools
protocol: ``solve`` (operations to a plan) and ``render`` (a contact sheet PNG of a plan).

Safety and bounds:
- **No network.** The page is opened on a reserved origin (``ORIGIN``, the ``.invalid`` top-level domain never
  resolves) and every request the page makes is intercepted (``Fetch.requestPaused``): files of this build under
  ``/projects/`` and the files the caller hands in (a set image read from the production) are served from memory, any
  other URL is refused. The browser also runs with ``--host-resolver-rules=MAP * ~NOTFOUND``, so even a request that
  slipped past interception could not reach a host. The page only ever navigates to ``ORIGIN + PAGE``.
- **Bounded time.** One deadline (``ZEROFIELD_PREVIS_TIMEOUT`` seconds, default 60) covers launch, load, solve and
  render; every socket wait is cut to what is left of it. One session runs at a time per process.
- **Cleanup.** The browser gets a throwaway profile directory; on exit the browser is closed over DevTools, its
  process tree is killed if it lingers (``taskkill /T`` on Windows, the process group elsewhere) and the profile is
  deleted.
- **No GPU.** WebGL runs on SwiftShader (``--use-angle=swiftshader``): previews never compete with ComfyUI or the local
  model for the GPU, so this path does not take the GPU arbiter.

Failures that mean "there is no headless solver here" raise :class:`Unavailable` (with a ``code``); the caller then
stores the operations only and the reviewer's 3D Stage solves them. A solver refusal of the operations raises
:class:`Refused` with the JavaScript validator's ``path`` and message.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

BROWSER_ENV = 'ZEROFIELD_PREVIS_BROWSER'   # a Chromium-family browser executable; "off" turns headless solving off
TIMEOUT_ENV = 'ZEROFIELD_PREVIS_TIMEOUT'   # seconds for one session (launch, load, solve, render)
DEFAULT_TIMEOUT = 60.0
ORIGIN = 'http://previs.zerofield.invalid'
PAGE = '/projects/previs-solver.html'
MAX_MESSAGE = 48 * 1024 * 1024            # one DevTools message (a contact sheet arrives as a data URL)
MAX_IMAGE = 8 * 1024 * 1024
CANDIDATES = (
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
)
NAMES = ('msedge', 'microsoft-edge', 'microsoft-edge-stable', 'google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'chrome')
TYPES = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
         '.css': 'text/css; charset=utf-8', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png',
         '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.woff2': 'font/woff2'}
_GUID = b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
_LIMIT = threading.BoundedSemaphore(1)


class Unavailable(RuntimeError):
    """No headless solve or render here: no browser, no solver page, launch failure, timeout or a page failure."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class Refused(ValueError):
    """The page's solver refused the operations (its validator), with the operation path it names."""

    def __init__(self, path, message, code='PREVIS_OPS_INVALID'):
        super().__init__(message)
        self.path, self.code = path, code


# ---------- where things are ----------

def static_dir() -> Path:
    from openbench_data import resource_path
    return Path(resource_path('static', 'projects'))


def browser_path():
    """The browser to run headless: ZEROFIELD_PREVIS_BROWSER, else an installed Edge or Chrome; None when there is none
    or the variable says off."""
    named = os.environ.get(BROWSER_ENV, '').strip()
    if named.lower() in ('off', '0', 'false', 'no', 'none'):
        return None
    if named:
        return named if Path(named).is_file() else shutil.which(named)
    for path in CANDIDATES:
        if Path(path).is_file():
            return path
    for name in NAMES:
        found = shutil.which(name)
        if found:
            return found
    return None


def availability(root=None):
    """(True, None) when a headless session could start, else (False, reason code)."""
    if os.environ.get(BROWSER_ENV, '').strip().lower() in ('off', '0', 'false', 'no', 'none'):
        return False, 'disabled'
    if not browser_path():
        return False, 'no_browser'
    if not (Path(root) if root else static_dir()).joinpath(PAGE.rsplit('/', 1)[1]).is_file():
        return False, 'no_page'
    return True, None


# ---------- a minimal WebSocket client (RFC 6455) for the DevTools endpoint on 127.0.0.1 ----------

def _mask(data, key):
    if not data:
        return b''
    repeated = (key * (len(data) // 4 + 1))[:len(data)]
    return (int.from_bytes(data, 'big') ^ int.from_bytes(repeated, 'big')).to_bytes(len(data), 'big')


class _Socket:
    def __init__(self, port, path, deadline):
        self.deadline, self.buffer = deadline, b''
        try:
            self.sock = socket.create_connection(('127.0.0.1', port), timeout=max(0.05, deadline - time.monotonic()))
        except OSError as exc:
            raise Unavailable('launch_failed', f'Could not connect to the browser: {exc}') from None
        key = base64.b64encode(os.urandom(16))
        self.sock.sendall(b'GET %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                          b'Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n' % (path.encode('ascii'), port, key))
        head = b''
        while b'\r\n\r\n' not in head:
            head += self._recv(4096)
            if len(head) > 65536:
                raise Unavailable('page_failed', 'The browser answered the DevTools handshake with too much data.')
        head, _, self.buffer = head.partition(b'\r\n\r\n')
        accept = base64.b64encode(hashlib.sha1(key + _GUID).digest())
        if not head.startswith(b'HTTP/1.1 101') or accept not in head:
            raise Unavailable('page_failed', 'The browser refused the DevTools connection.')

    def _recv(self, size):
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise Unavailable('timeout', 'The headless browser ran out of time.')
        self.sock.settimeout(left)
        try:
            data = self.sock.recv(size)
        except socket.timeout:
            raise Unavailable('timeout', 'The headless browser ran out of time.') from None
        except OSError as exc:
            raise Unavailable('page_failed', f'The DevTools connection failed: {exc}') from None
        if not data:
            raise Unavailable('page_failed', 'The browser closed the DevTools connection.')
        return data

    def _exact(self, size):
        while len(self.buffer) < size:
            self.buffer += self._recv(max(65536, size - len(self.buffer)))
        data, self.buffer = self.buffer[:size], self.buffer[size:]
        return data

    def _frame(self, opcode, payload):
        key = os.urandom(4)
        size = len(payload)
        head = bytes([0x80 | opcode]) + (bytes([0x80 | size]) if size < 126 else bytes([0x80 | 126]) + struct.pack('>H', size)
                                         if size < 65536 else bytes([0x80 | 127]) + struct.pack('>Q', size))
        try:
            self.sock.sendall(head + key + _mask(payload, key))
        except OSError as exc:
            raise Unavailable('page_failed', f'The DevTools connection failed: {exc}') from None

    def send(self, text):
        self._frame(0x1, text.encode('utf-8'))

    def receive(self):
        parts, total = [], 0
        while True:
            first, second = self._exact(2)
            size = second & 0x7F
            if size == 126:
                size = struct.unpack('>H', self._exact(2))[0]
            elif size == 127:
                size = struct.unpack('>Q', self._exact(8))[0]
            key = self._exact(4) if second & 0x80 else None
            total += size
            if total > MAX_MESSAGE:
                raise Unavailable('page_failed', 'A DevTools message was too large.')
            payload = self._exact(size)
            if key:
                payload = _mask(payload, key)
            opcode = first & 0x0F
            if opcode == 0x8:
                raise Unavailable('page_failed', 'The browser closed the DevTools connection.')
            if opcode == 0x9:
                self._frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            parts.append(payload)
            if first & 0x80:
                return b''.join(parts).decode('utf-8')

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class _Cdp:
    def __init__(self, ws, on_event):
        self.ws, self.on_event, self.counter = ws, on_event, 0

    def send(self, method, params=None, session=None):
        self.counter += 1
        message = {'id': self.counter, 'method': method, 'params': params or {}}
        if session:
            message['sessionId'] = session
        self.ws.send(json.dumps(message))
        return self.counter

    def call(self, method, params=None, session=None):
        ident = self.send(method, params, session)
        while True:
            message = json.loads(self.ws.receive())
            if message.get('id') == ident:
                if 'error' in message:
                    raise Unavailable('page_failed', f"{method}: {message['error'].get('message', 'failed')}")
                return message.get('result') or {}
            if 'method' in message:
                self.on_event(message)


# ---------- one browser session ----------

class Session:
    """``with Session(files=...) as page: page.solve(request); page.render(plan, title)``.

    files: {"/projects/api/<slug>/assets/<id>": (content type, bytes)}, extra files the page may load (a set image)."""

    def __init__(self, *, files=None, timeout=None, root=None, browser=None):
        self.files = dict(files or {})
        try:
            self.timeout = float(timeout or os.environ.get(TIMEOUT_ENV) or DEFAULT_TIMEOUT)
        except ValueError:
            self.timeout = DEFAULT_TIMEOUT
        self.root = Path(root) if root else static_dir()
        self.browser = browser
        self.proc = self.profile = self.ws = self.cdp = self.session = None
        self.held = False
        self.served, self.refused = [], []

    # -- lifecycle --
    def __enter__(self):
        self.deadline = time.monotonic() + self.timeout
        self.browser = self.browser or browser_path()
        if not self.browser:
            raise Unavailable('disabled' if os.environ.get(BROWSER_ENV, '').strip() else 'no_browser',
                              'No headless browser is available (set ZEROFIELD_PREVIS_BROWSER to a Chromium-family browser).')
        if not (self.root / PAGE.rsplit('/', 1)[1]).is_file():
            raise Unavailable('no_page', 'The UI build has no previs-solver.html; run npm run build --prefix ui.')
        if not _LIMIT.acquire(timeout=max(0.0, self.deadline - time.monotonic())):
            raise Unavailable('timeout', 'Another headless previs is still running.')
        self.held = True
        try:
            port, path = self._launch()
            self.ws = _Socket(port, path, self.deadline)
            self.cdp = _Cdp(self.ws, self._event)
            target = self.cdp.call('Target.createTarget', {'url': 'about:blank'})['targetId']
            self.session = self.cdp.call('Target.attachToTarget', {'targetId': target, 'flatten': True})['sessionId']
            self.cdp.call('Fetch.enable', {'patterns': [{'urlPattern': '*'}]}, self.session)
            opened = self.cdp.call('Page.navigate', {'url': ORIGIN + PAGE}, self.session)
            if opened.get('errorText'):
                raise Unavailable('page_failed', 'The solver page did not open: ' + opened['errorText'])
            while not self._evaluate('window.zfPrevisReady === true && typeof window.zfPrevis === "object"'):
                if time.monotonic() > self.deadline:
                    raise Unavailable('timeout', 'The solver page did not load in time.')
                time.sleep(0.05)
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *exc):
        self.close()

    def _launch(self):
        self.profile = tempfile.mkdtemp(prefix='zf-previs-')
        args = [self.browser, '--headless=new', '--remote-debugging-port=0', '--user-data-dir=' + self.profile,
                '--no-first-run', '--no-default-browser-check', '--disable-extensions', '--disable-sync',
                '--disable-background-networking', '--disable-component-update', '--disable-default-apps',
                '--disable-client-side-phishing-detection', '--metrics-recording-only', '--no-pings', '--mute-audio',
                '--disable-features=Translate,MediaRouter,OptimizationHints,AutofillServerCommunication',
                '--host-resolver-rules=MAP * ~NOTFOUND', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
                '--window-size=1280,800', 'about:blank']
        options = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}
        if os.name == 'nt':
            options['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        else:
            options['start_new_session'] = True
        try:
            self.proc = subprocess.Popen(args, **options)
        except OSError as exc:
            raise Unavailable('launch_failed', f'Could not start the headless browser: {exc}') from None
        marker = Path(self.profile) / 'DevToolsActivePort'
        while time.monotonic() < self.deadline:
            if self.proc.poll() is not None:
                raise Unavailable('launch_failed', f'The headless browser exited ({self.proc.returncode}).')
            try:
                lines = marker.read_text(encoding='utf-8').split()
            except OSError:
                lines = []
            if len(lines) >= 2 and lines[0].isdigit():
                return int(lines[0]), lines[1]
            time.sleep(0.05)
        raise Unavailable('timeout', 'The headless browser did not open its DevTools port in time.')

    def close(self):
        """Close the browser, kill what is left of its process tree and delete its profile. Safe to call twice."""
        if self.cdp is not None:
            try:
                self.cdp.send('Browser.close')
            except Exception:  # noqa: BLE001 - already gone
                pass
            self.cdp = None
        if self.ws is not None:
            self.ws.close()
            self.ws = None
        if self.proc is not None:
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _kill_tree(self.proc)
            self.proc = None
        if self.profile:
            for _ in range(20):
                shutil.rmtree(self.profile, ignore_errors=True)
                if not os.path.exists(self.profile):
                    break
                time.sleep(0.1)
            self.profile = None
        if self.held:
            self.held = False
            _LIMIT.release()

    # -- the page --
    def _event(self, message):
        method, params = message.get('method'), message.get('params') or {}
        if method == 'Fetch.requestPaused':
            url = (params.get('request') or {}).get('url', '')
            found = self._resolve(url)
            if found:
                kind, body = found
                self.served.append(url)
                self.cdp.send('Fetch.fulfillRequest', {
                    'requestId': params['requestId'], 'responseCode': 200,
                    'responseHeaders': [{'name': 'Content-Type', 'value': kind}, {'name': 'Cache-Control', 'value': 'no-store'}],
                    'body': base64.b64encode(body).decode('ascii')}, message.get('sessionId'))
            else:
                self.refused.append(url)
                self.cdp.send('Fetch.failRequest', {'requestId': params['requestId'], 'errorReason': 'BlockedByClient'},
                              message.get('sessionId'))
        elif method in ('Inspector.targetCrashed', 'Target.targetCrashed') or (method == 'Target.detachedFromTarget'
                                                                               and params.get('sessionId') == self.session):
            raise Unavailable('page_failed', 'The solver page crashed.')

    def _resolve(self, url):
        """(content type, bytes) for a URL the page may load, else None (refused)."""
        parts = urlsplit(url)
        if f'{parts.scheme}://{parts.netloc}' != ORIGIN:
            return None
        path = unquote(parts.path)
        if path in self.files:
            return self.files[path]
        if not path.startswith('/projects/') or '\\' in path:
            return None
        root = self.root.resolve()
        target = (root / path[len('/projects/'):]).resolve()
        if root not in target.parents or not target.is_file() or target.suffix.lower() not in TYPES:
            return None
        return TYPES[target.suffix.lower()], target.read_bytes()

    def _evaluate(self, expression, await_promise=False):
        result = self.cdp.call('Runtime.evaluate', {'expression': expression, 'awaitPromise': await_promise,
                                                    'returnByValue': True}, self.session)
        if result.get('exceptionDetails'):
            details = result['exceptionDetails']
            text = (details.get('exception') or {}).get('description') or details.get('text') or 'error'
            raise Unavailable('page_failed', 'The solver page failed: ' + str(text)[:500])
        return (result.get('result') or {}).get('value')

    def solve(self, request):
        """The page's solveRequest: {version, plan, warnings, base}; Refused when its validator refuses the operations."""
        answer = json.loads(self._evaluate('window.zfPrevis.solve(%s)' % json.dumps(json.dumps(request))) or 'null')
        if not isinstance(answer, dict):
            raise Unavailable('page_failed', 'The solver page gave no answer.')
        if not answer.get('ok'):
            error = answer.get('error') or {}
            if error.get('code') == 'PREVIS_OPS_INVALID':
                raise Refused(error.get('path'), error.get('message') or 'The operations were refused.')
            raise Unavailable('page_failed', 'The solver failed: ' + str(error.get('message'))[:500])
        return {key: value for key, value in answer.items() if key != 'ok'}

    def render(self, plan, title=''):
        """A contact sheet of the plan: (PNG bytes, {width, height, frames})."""
        answer = json.loads(self._evaluate('window.zfPrevis.render(%s)' % json.dumps(json.dumps({'plan': plan, 'title': title})),
                                           await_promise=True) or 'null')
        if not isinstance(answer, dict) or not answer.get('ok'):
            raise Unavailable('render_failed', 'The preview did not render: ' + str(((answer or {}).get('error') or {}).get('message'))[:500])
        url = answer.get('dataUrl') or ''
        if not url.startswith('data:image/png;base64,'):
            raise Unavailable('render_failed', 'The preview is not a PNG image.')
        image = base64.b64decode(url.split(',', 1)[1])
        if not image.startswith(b'\x89PNG\r\n\x1a\n') or len(image) > MAX_IMAGE:
            raise Unavailable('render_failed', 'The preview is not a PNG image of at most 8 MB.')
        return image, {'width': answer.get('width'), 'height': answer.get('height'), 'frames': answer.get('frames') or []}


def _kill_tree(proc):
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=15, check=False)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def run(request, *, title='', files=None, render=True, timeout=None):
    """Solve a request and (by default) render the solved plan in one session. title: the sheet's header line, or a
    function of the solved plan that returns it.

    Returns {"solved": {version, plan, warnings, base}, "image": PNG bytes | None, "sheet": {width, height, frames} | None,
    "renderError": str | None, "browser": executable name, "seconds": float}. Raises Unavailable or Refused."""
    started = time.monotonic()
    with Session(files=files, timeout=timeout) as page:
        solved = page.solve(request)
        image = sheet = error = None
        if render:
            try:
                image, sheet = page.render(solved['plan'], title(solved['plan']) if callable(title) else title)
            except Unavailable as exc:
                if exc.code == 'timeout':
                    raise
                error = str(exc)
        name = Path(page.browser).name
    return {'solved': solved, 'image': image, 'sheet': sheet, 'renderError': error, 'browser': name,
            'seconds': round(time.monotonic() - started, 2)}


if __name__ == '__main__':  # pragma: no cover - a manual probe: python -m project_assistant.headless_previs
    print(json.dumps({'available': availability(), 'browser': browser_path(), 'page': str(static_dir() / 'previs-solver.html')}))
    sys.exit(0)

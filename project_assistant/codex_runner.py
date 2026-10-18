"""跑一輪 codex exec：只開專案助理的工具，關掉執行指令、讀檔、上網、瀏覽器、外掛等功能。

code mode 要留著：gpt-6.1-sol 透過它呼叫 MCP 工具。10/14 實測它是隔離的 JavaScript，讀不到檔案、
連不了網、拿不到環境變數；寫檔被唯讀沙箱擋下。其餘一律關掉，事件裡出現白名單外的項目就結束整棵行程樹。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

DISABLE = [
    "shell_tool", "unified_exec", "shell_snapshot",
    "browser_use", "browser_use_external", "browser_use_full_cdp_access", "in_app_browser",
    "computer_use", "apps", "plugins", "remote_plugin", "plugin_sharing",
    "image_generation", "view_image", "multi_agent", "hooks",
    "skill_search", "skill_mcp_dependency_install", "tool_suggest", "workspace_dependencies",
    "browser_annotation_api", "unified_exec_tty", "sleep_tool", "worktrees", "in_app_local_automation",
    "realtime_conversation", "daemon_auto_start", "write_stdin_approval", "in_app_voice",
]
ALLOWED_ITEMS = {"agent_message", "reasoning", "mcp_tool_call", "todo_list"}
ENV_KEEP = {
    "SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
    "HOME", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432",
    "COMMONPROGRAMFILES", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS", "USERNAME", "USERDOMAIN",
    "COMPUTERNAME", "CODEX_HOME", "LANG", "LC_ALL", "TZ", "SSL_CERT_FILE", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY",
}
QUOTA_RE = re.compile(r"usage limit|rate limit|quota|too many requests|\b429\b", re.I)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class CodexResult:
    status: str
    answer: str = ""
    seconds: float = 0.0
    tool_items: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    stderr_tail: str = ""
    blocked: str = ""


def _prefix(codex) -> list[str]:
    return [str(x) for x in codex] if isinstance(codex, (list, tuple)) else [str(codex)]


def toml_str(value) -> str:
    return json.dumps(str(value))


_FEATURES: dict = {}
_VERSION: dict = {}


def known_features(codex) -> set:
    key = tuple(_prefix(codex))
    if key not in _FEATURES:
        out = subprocess.run(_prefix(codex) + ["features", "list"], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=60, creationflags=NO_WINDOW).stdout
        _FEATURES[key] = {line.split()[0] for line in out.splitlines() if line.strip()}
    return _FEATURES[key]


def codex_version(codex) -> str:
    key = tuple(_prefix(codex))
    cached = _VERSION.get(key)
    if cached and time.monotonic() - cached[1] < 600:
        return cached[0]
    try:
        out = subprocess.run(_prefix(codex) + ["--version"], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=30, creationflags=NO_WINDOW).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    _VERSION[key] = (out or "unknown", time.monotonic())
    return _VERSION[key][0]


def build_command(codex, *, model, effort, mcp_python, mcp_script, tool_url, token, workdir, last_file) -> list[str]:
    env_table = "{PA_TOOL_URL=%s, PA_TOKEN=%s, PYTHONIOENCODING=\"utf-8\"}" % (toml_str(tool_url), toml_str(token))
    cmd = _prefix(codex) + [
        "exec", "--ignore-user-config", "--skip-git-repo-check", "--ephemeral", "--json",
        "-s", "read-only", "-m", model, "-c", f"model_reasoning_effort={toml_str(effort)}",
        "-c", 'web_search="disabled"',
        "-c", f"mcp_servers.pa.command={toml_str(mcp_python)}",
        "-c", "mcp_servers.pa.args=[%s, %s, %s]" % (toml_str("-X"), toml_str("utf8"), toml_str(mcp_script)),
        "-c", f"mcp_servers.pa.env={env_table}",
        "-c", "mcp_servers.pa.startup_timeout_sec=60",
        "-c", "mcp_servers.pa.tool_timeout_sec=120",
        "-C", str(workdir), "-o", str(last_file),
    ]
    known = known_features(codex)
    for feature in DISABLE:
        if feature in known:
            cmd += ["--disable", feature]
    return cmd + ["-"]


def scrub_env(environ) -> dict:
    env = {key: value for key, value in environ.items() if key.upper() in ENV_KEEP}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _kill_tree(proc) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=15,
                       creationflags=NO_WINDOW)
    else:
        proc.kill()


def _blocked_reason(item: dict) -> str:
    kind = item.get("type") or ""
    if kind not in ALLOWED_ITEMS:
        return kind or "unknown"
    if kind == "mcp_tool_call" and item.get("server") != "pa":
        return f"mcp:{item.get('server')}"
    return ""


def run(prompt, *, codex, model, effort, mcp_python, mcp_script, tool_url, token, timeout, workdir, cancel_event=None) -> CodexResult:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    last = workdir / f"last-{uuid.uuid4().hex[:8]}.txt"
    cmd = build_command(codex, model=model, effort=effort, mcp_python=mcp_python, mcp_script=mcp_script,
                        tool_url=tool_url, token=token, workdir=workdir, last_file=last)
    started = time.monotonic()
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=scrub_env(os.environ), cwd=str(workdir), creationflags=NO_WINDOW)
    proc.stdin.write(prompt.encode("utf-8"))
    proc.stdin.close()
    stderr_chunks: list[bytes] = []
    reader = threading.Thread(target=lambda: stderr_chunks.extend(iter(lambda: proc.stderr.read(4096), b"")),
                              daemon=True)
    reader.start()
    timed_out = threading.Event()
    monitor_stop = threading.Event()
    def monitor_cancel():
        while not monitor_stop.wait(.1):
            if cancel_event is not None and cancel_event.is_set():
                _kill_tree(proc)
                return
    monitor = threading.Thread(target=monitor_cancel, daemon=True)
    monitor.start()

    def on_timeout():
        timed_out.set()
        _kill_tree(proc)

    timer = threading.Timer(timeout, on_timeout)
    timer.start()
    result = CodexResult(status="error")
    try:
        for raw in iter(proc.stdout.readline, b""):
            try:
                event = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            kind = event.get("type") or ""
            item = event.get("item") or {}
            if kind in ("item.started", "item.completed") and item:
                reason = _blocked_reason(item)
                if reason:
                    result.blocked = reason
                    _kill_tree(proc)
                    break
                if kind == "item.completed" and item.get("type") == "mcp_tool_call":
                    result.tool_items.append({"tool": item.get("tool"), "status": item.get("status")})
            elif kind == "turn.completed":
                result.usage = event.get("usage") or {}
            elif kind in ("error", "turn.failed"):
                message = event.get("message") or (event.get("error") or {}).get("message") or ""
                result.errors.append(str(message)[:300])
        proc.wait(timeout=30)
    finally:
        monitor_stop.set()
        timer.cancel()
        if proc.poll() is None:
            _kill_tree(proc)
        reader.join(timeout=5)
        monitor.join(timeout=1)
        proc.stdout.close()
        if not reader.is_alive():
            proc.stderr.close()
    result.seconds = round(time.monotonic() - started, 1)
    result.stderr_tail = b"".join(stderr_chunks).decode("utf-8", "replace")[-1500:]
    result.answer = last.read_text(encoding="utf-8").strip() if last.exists() else ""
    failed = proc.returncode not in (0, None) or not result.answer
    if result.blocked:
        result.status = "lockdown"
    elif timed_out.is_set():
        result.status = "timeout"
    elif failed and (any(QUOTA_RE.search(e) for e in result.errors) or QUOTA_RE.search(result.stderr_tail)):
        result.status = "quota"
    elif failed:
        result.status = "error"
    else:
        result.status = "ok"
    return result

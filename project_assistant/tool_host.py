"""每一輪一個的工具主機：只綁 127.0.0.1、隨機埠號，權杖只活在這一輪的記憶體裡。

mcp_stdio.py 把模型的工具呼叫 POST 到這裡；這裡用使用者本人的身分執行 tools.call。
經 Cloudflare 進來的請求（帶 Cf-* 標頭）一律拒絕——正常情況外面也連不到這個埠。
"""
from __future__ import annotations

import datetime as dt
import hmac
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from project_assistant import tools

MAX_BODY = 64 * 1024
LABELS = {"list_pages": "專案頁分頁", "read_page": "專案頁", "search_pages": "搜尋專案頁", "my_todo": "待辦",
          "report_list": "報表清單", "report_overview": "報表總覽", "report_sheet": "報表", "report_cell": "報表格子",
          "report_find": "在報表裡找", "propose": "提出修改",
          "offer_document": "準備文件下載"}


def summarize(name: str, args: dict) -> dict:
    """畫面上「正在看：…」用的白話；只記工具名和查了什麼，不記結果。"""

    a = {k: str(v) for k, v in (args or {}).items() if v is not None}
    detail = {
        "read_page": a.get("key", "") + (f"〈{a['section']}〉" if a.get("section") else ""),
        "search_pages": f"「{a.get('query', '')}」",
        "report_overview": a.get("code", ""),
        "report_sheet": f"{a.get('code', '')}〈{a.get('sheet', '')}〉",
        "report_cell": f"{a.get('code', '')}〈{a.get('sheet', '')}〉{a.get('cell', '')}",
        "report_find": f"「{a.get('text', '')}」",
        "propose": a.get("action", ""),
    }.get(name, "")
    return {"tool": name, "label": LABELS.get(name, name), "detail": detail[:60]}


class ToolHost:
    def __init__(self, ctx, *, on_call=None):
        self.ctx = ctx
        self.on_call = on_call
        self.token = secrets.token_urlsafe(32)
        self.calls: list[dict] = []
        self._server = None

    def start(self) -> tuple[str, str]:
        host = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                host._handle(self)

            def do_GET(self):  # noqa: N802
                if (self.path!='/tools' or any(k.lower().startswith('cf-') for k in self.headers)
                    or not hmac.compare_digest(self.headers.get('X-PA-Token') or '',host.token)):
                    return host._reply(self,403,{'error':'權杖或工具清單路徑不正確'})
                from project_assistant import agent_policy,agent_registry
                conn = host.ctx.connection_factory()
                try:
                    profile=agent_registry.get_agent(conn,host.ctx.slug,getattr(host.ctx,'agent_key','coordinator'))
                    specs=agent_policy.tool_specs_for(profile) if profile and profile['enabled'] else []
                    frozen=getattr(host.ctx,'allowed_tools',None)
                    if frozen is not None:
                        specs=[s for s in specs if s['name'] in frozen]
                    host._reply(self,200,{'tools':specs})
                finally:
                    conn.close()

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, daemon=True, name="pa-tool-host").start()
        return f"http://127.0.0.1:{self._server.server_address[1]}", self.token

    def stop(self) -> None:
        server, self._server = self._server, None
        if server:
            server.shutdown()
            server.server_close()

    @staticmethod
    def _reply(request, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request.send_response(status)
        request.send_header("Content-Type", "application/json; charset=utf-8")
        request.send_header("Content-Length", str(len(data)))
        request.end_headers()
        request.wfile.write(data)

    def _handle(self, request) -> None:
        if any(key.lower().startswith("cf-") for key in request.headers.keys()):
            return self._reply(request, 403, {"error": "不接受從外面來的請求"})
        if not hmac.compare_digest(request.headers.get("X-PA-Token") or "", self.token):
            return self._reply(request, 403, {"error": "權杖不對"})
        if not request.path.startswith("/tool/"):
            return self._reply(request, 404, {"error": "沒有這個功能"})
        name = request.path[len("/tool/"):]
        length = int(request.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._reply(request, 413, {"error": "參數太長"})
        try:
            args = json.loads(request.rfile.read(length) or b"{}")
        except ValueError:
            return self._reply(request, 400, {"error": "參數不是 JSON"})
        args = args if isinstance(args, dict) else {}
        summary = summarize(name, args)
        try:
            payload = {"text": tools.call(self.ctx, name, args)}
            summary["ok"] = True
        except tools.ToolError as exc:
            payload = {"error": str(exc)}
            summary["ok"] = False
        except Exception as exc:  # noqa: BLE001 - 工具壞了要回給模型，不能讓這一輪卡住
            print(f"project-assistant: tool {name} failed: {type(exc).__name__}: {exc}", flush=True)
            payload = {"error": "工具出錯了，請換個方式再試一次"}
            summary["ok"] = False
        summary["at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        self.calls.append(summary)
        if self.on_call:
            try:
                self.on_call(summary)
            except Exception as exc:  # noqa: BLE001
                print(f"project-assistant: tool log failed: {type(exc).__name__}: {exc}", flush=True)
        self._reply(request, 200, payload)

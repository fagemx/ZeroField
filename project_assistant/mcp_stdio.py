"""專案助理的 MCP 工具伺服器（stdio，只用標準函式庫）。

Codex 每一輪開一個；它不碰資料庫、不讀檔，只把工具呼叫轉給這一輪的工具主機。
環境變數：PA_TOOL_URL（http://127.0.0.1:<埠號>）、PA_TOKEN（這一輪的權杖）。
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from project_assistant.tool_specs import TOOL_NAMES, TOOLS  # noqa: E402

PROTOCOL = "2025-06-18"


def _send(obj) -> None:
    sys.stdout.buffer.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def _call_tool(name: str, args: dict) -> tuple[str, bool]:
    url = os.environ.get("PA_TOOL_URL", "").rstrip("/") + "/tool/" + name
    request = urllib.request.Request(
        url, data=json.dumps(args or {}, ensure_ascii=False).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "X-PA-Token": os.environ.get("PA_TOKEN", "")})
    try:
        with urllib.request.urlopen(request, timeout=110) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except ValueError:
            payload = {"error": f"Tool host returned HTTP {exc.code}."}
    except Exception as exc:  # noqa: BLE001 - 連不上也要回一個工具錯誤，不能讓伺服器掛掉
        payload = {"error": f"The tool is temporarily unavailable ({type(exc).__name__}). Try again."}
    if "error" in payload:
        return str(payload["error"]), True
    return str(payload.get("text", "")), False


def _host_tools():
    request=urllib.request.Request(os.environ.get('PA_TOOL_URL','').rstrip('/')+'/tools',
        headers={'X-PA-Token':os.environ.get('PA_TOKEN','')})
    with urllib.request.urlopen(request,timeout=10) as response:
        return json.loads(response.read())['tools']


def handle(message: dict):
    method = message.get("method")
    params = message.get("params") or {}
    if method == "initialize":
        return {"protocolVersion": params.get("protocolVersion") or PROTOCOL,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "project-assistant", "version": "1.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": _host_tools()}
    if method == "tools/call":
        name = params.get("name")
        if name not in {s['name'] for s in _host_tools()}:
            raise LookupError(f"Tool {name} does not exist.")
        text, is_error = _call_tool(name, params.get("arguments") or {})
        return {"content": [{"type": "text", "text": text}], "isError": is_error}
    raise NotImplementedError(method)


def main() -> None:
    for raw in sys.stdin.buffer:
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            _send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Invalid JSON."}})
            continue
        if "id" not in message:
            continue  # 通知（例如 notifications/initialized）不用回
        try:
            _send({"jsonrpc": "2.0", "id": message["id"], "result": handle(message)})
        except NotImplementedError as exc:
            _send({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": f"Unsupported operation: {exc}"}})
        except LookupError as exc:
            _send({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32602, "message": str(exc)}})
        except Exception as exc:  # noqa: BLE001
            _send({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32603, "message": type(exc).__name__}})


if __name__ == "__main__":
    main()

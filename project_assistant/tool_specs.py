"""專案助理工具表：全部由 project_assistant/tool_registry.py 產生，保留給既有的 import。

新增或修改工具只改 tool_registry.py（再更新工具清單快照）；這裡不手寫任何工具。
純資料：MCP 伺服器（零依賴）和工具主機都讀這一份。
"""
from __future__ import annotations

from project_assistant import tool_registry as _registry
from project_docs.doc_schema import STATUSES  # noqa: F401  (re-exported for older imports)

PROPOSE_ACTIONS = _registry.PROPOSE_ACTIONS
LABELS = _registry.PROPOSE_LABELS
TOOLS = _registry.specs()
STUDIO_SCHEMAS = {spec['name']: spec['inputSchema'] for spec in TOOLS if spec['name'] in _registry.STUDIO}
DEFAULT_POLICIES = dict(_registry.DEFAULT_POLICIES)
TOOL_NAMES = set(_registry.NAMES)
DELEGATION_TOOLS = set(_registry.DELEGATION)
MUTATING_TOOLS = set(_registry.MUTATING)
CONSOLE_TOOLS = set(_registry.CONSOLE)
MCP_TOOLS = frozenset(_registry.MCP)
UI_TOOLS = list(_registry.UI)


def validate_studio_args(name, args):
    """Fail fast on Studio arguments before a connection opens, exactly as before the registry.

    agent_policy.authorize_tool validates every tool (tool_registry.validate_args) once policy allows it."""
    if name in STUDIO_SCHEMAS:
        _registry.validate_args(name, args)

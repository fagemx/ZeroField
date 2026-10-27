"""Declarative tool registry: every product tool is declared once, here (SPEC_20 R15).

A Tool declares its name, description, JSON schema, default permission policy, whether it changes
production state, its category, where it is exposed, the built-in crew roles that receive it by default,
and its handler as a lazy "module:function" reference. The older tool tables are derived from this one,
so existing imports keep working: tool_specs (TOOLS, STUDIO_SCHEMAS, DEFAULT_POLICIES, MUTATING_TOOLS,
TOOL_NAMES, DELEGATION_TOOLS), the agent_policy deny lists, studio_tools.HANDLERS and EXTERNAL_TOOLS,
tool_host.LABELS, agent_console_store.STUDIO_TOOLS, agent_registry.default_tools, the MCP tools/list
filter and what zerofield-mcp lists to service-account tokens (ZEROFIELD_MCP, SPEC_20 R30).
validate_args() checks any tool's arguments against its schema; agent_policy.authorize_tool runs it for
every tool on every transport.

Adding a tool
1. Declare it once below, or in a data-only module named in EXTENSIONS (see there).
2. Write the handler `def <name>(ctx, conn, args)` in the module its `handler` names. tools.call
   dispatches through tools.HANDLERS: the tools.py table plus delegation_tools.HANDLERS and
   studio_tools.HANDLERS (studio_tools derives its table from here). A handler kept anywhere else must be
   merged there too; tests/test_tool_registry.py fails while dispatch and the registry disagree.
3. Accept the new tool surface deliberately, then review and commit the snapshot with the change:
       python -X utf8 scripts/audit_tool_surface.py --write
   tests/test_tool_registry.py fails until tests/fixtures/tool_surface.json matches.
4. A ui=True tool is also listed in STUDIO_TOOLS in ui/src/agentConsole/model.js (the same test names
   any drift).

This module imports only the standard library and project_docs.doc_schema, and never imports a handler
module: the zero-dependency MCP server loads it, and handler modules can import it without a cycle.
The built-in names and descriptions follow the 10/14 test build (21 scenarios); propose carries the
locating arguments production needs.
"""
from __future__ import annotations

import copy
import importlib
import json
import re
from dataclasses import dataclass
from types import MappingProxyType

from project_docs.doc_schema import STATUSES

BUILTIN_ROLES = ('coordinator', 'doc_writer', 'sheet_ops', 'qa_critic')  # agent_registry.ROSTER keys
PRIMARY_ROLES = ('coordinator',)  # seeded with role_kind=primary
POLICIES = ('auto', 'always_ask', 'disabled')
REQUIREMENTS = ('allow_subagents', 'allow_workflows', 'advisor_agent_key')  # multiagent_config switches
STUDIO_CATEGORIES = ('studio', 'advisor')  # their argument errors keep the historic "Studio" wording

# Data-only declaration modules owned by other packages. Each exposes TOOLS, a sequence of dicts with
# Tool's field names. Such a module imports nothing from project_assistant (not this module, not its
# handlers), so importing it never circles back and the MCP server stays dependency-free.
EXTENSIONS: tuple[str, ...] = ()

PROPOSE_ACTIONS = ["寫進那一題的討論", "改狀態", "填交接追蹤", "留言問負責人", "在段落加標註", "私下轉給負責人"]
PROPOSE_LABELS = {"問題": "q", "要修改": "fix"}


@dataclass(frozen=True)
class Tool:
    """One product tool. The defaults describe a read-only tool that no role receives by default."""

    name: str
    description: str
    schema: dict  # closed JSON object schema, the subset validate_args understands
    category: str  # legacy | delegation | studio | advisor | ...
    handler: str  # "module:function", resolved lazily
    policy: str = 'auto'  # default permission when the agent sets none: auto | always_ask | disabled
    mutating: bool = False  # changes or spends production state: journaled, denied to viewers
    annotations: dict | None = None  # MCP annotations, emitted only when declared
    label: str | None = None  # crew-facing activity label ("Reading: …"); None shows the tool name
    # Console catalog (tool_specs.CONSOLE_TOOLS): may be granted or configured on an agent. The Console
    # validators still accept any TOOL_NAMES entry; switch them to CONSOLE_TOOLS before declaring False.
    console: bool = True
    ui: bool = False  # always offered in the Console agent editor (ui/src/agentConsole/model.js)
    mcp: bool = True  # listed and callable through the MCP server (still per-agent grants)
    analysis_only: bool = True  # usable in write_mode=analysis_only tasks
    race_candidate: bool = True  # usable by race candidates before winner review
    primary_only: bool = False  # hidden from worker roles
    external: bool = False  # handler runs outside the shared transaction (inference, FFmpeg, probes)
    requires: tuple = ()  # multiagent_config switches that must be set
    grants: tuple = ()  # built-in roles that receive the tool by default
    # Listed by zerofield-mcp to external service-account tokens (SPEC_20 R30), still narrowed per token.
    # None derives it (see zerofield_exposed): read-only tools outside the legacy/delegation categories that
    # need no review turn. Writes and legacy tools opt in explicitly with True.
    zerofield_mcp: bool | None = None

    def spec(self) -> dict:
        """The tool-host/MCP shape, identical to the historic tool_specs.TOOLS entries."""
        spec = {'name': self.name, 'description': self.description, 'inputSchema': self.schema}
        if self.annotations is not None:
            spec['annotations'] = self.annotations
        return spec


_TOOLS: dict[str, Tool] = {}
_sealed = False


def declare(item) -> Tool:
    """A checked Tool from a Tool or a dict of Tool fields (the EXTENSIONS format)."""
    if isinstance(item, dict):
        item = Tool(**{**item, 'requires': tuple(item.get('requires', ())), 'grants': tuple(item.get('grants', ()))})
    if not isinstance(item, Tool):
        raise TypeError('Declare Tool objects or dicts of Tool fields.')
    _check_declaration(item)
    return item


def register(*tools) -> None:
    """Add declarations. Only possible while this module loads; afterwards the derived tables are fixed."""
    if _sealed:
        raise RuntimeError('The tool registry is sealed; declare tools in tool_registry or an EXTENSIONS module.')
    for tool in map(declare, tools):
        if tool.name in _TOOLS:
            raise ValueError(f'Tool {tool.name!r} is declared twice.')
        _TOOLS[tool.name] = tool


# ---------- declaration checks: fail at import, not at the first model call ----------

_NAME = re.compile(r'^[a-z][a-z0-9_]{0,63}$')
_HANDLER = re.compile(r'^[A-Za-z_][\w.]*:[A-Za-z_]\w*$')
_KEYWORDS = {
    'object': {'properties', 'required', 'additionalProperties'},
    'string': {'minLength', 'maxLength', 'enum', 'pattern'},
    'integer': {'minimum', 'maximum', 'enum'},
    'boolean': set(),
    'array': {'items', 'minItems', 'maxItems', 'uniqueItems'},
}
_SCHEMA_ANNOTATIONS = {'type', 'description', 'title'}
_FLAGS = ('mutating', 'console', 'ui', 'mcp', 'analysis_only', 'race_candidate', 'primary_only', 'external')


def _check_declaration(tool: Tool) -> None:
    def bad(message):
        raise ValueError(f'Tool {tool.name!r}: {message}')
    if not isinstance(tool.name, str) or not _NAME.fullmatch(tool.name):
        bad('the name must be a lower-case identifier.')
    if not isinstance(tool.description, str) or not tool.description.strip():
        bad('a description is required.')
    if not isinstance(tool.category, str) or not _NAME.fullmatch(tool.category):
        bad('the category must be a lower-case identifier.')
    if not isinstance(tool.handler, str) or not _HANDLER.fullmatch(tool.handler):
        bad('the handler must be "module:function".')
    if tool.policy not in POLICIES:
        bad('the default policy must be one of ' + ', '.join(POLICIES) + '.')
    for flag in _FLAGS:
        if type(getattr(tool, flag)) is not bool:
            bad(f'{flag} must be a boolean.')
    if not isinstance(tool.requires, tuple) or any(r not in REQUIREMENTS for r in tool.requires):
        bad('requires lists multiagent_config switches: ' + ', '.join(REQUIREMENTS) + '.')
    if not isinstance(tool.grants, tuple) or len(set(tool.grants)) != len(tool.grants) or any(
            r not in BUILTIN_ROLES for r in tool.grants):
        bad('grants lists distinct built-in roles: ' + ', '.join(BUILTIN_ROLES) + '.')
    if tool.annotations is not None and not isinstance(tool.annotations, dict):
        bad('annotations must be a dict.')
    if tool.label is not None and (not isinstance(tool.label, str) or not tool.label.strip()):
        bad('the label must be a non-empty string.')
    if tool.ui and not tool.console:
        bad('a UI catalog tool must be in the Console catalog.')
    if tool.grants and not tool.console:
        bad('only Console catalog tools can be granted by default.')
    if tool.primary_only and set(tool.grants) - set(PRIMARY_ROLES):
        bad('a primary-only tool can only be granted to primary roles.')
    if tool.zerofield_mcp is not None and type(tool.zerofield_mcp) is not bool:
        bad('zerofield_mcp must be a boolean or None.')
    if tool.zerofield_mcp and (not tool.mcp or tool.policy != 'auto' or tool.requires or tool.primary_only):
        # An external call has no review turn, crew switches or primary role to satisfy.
        bad('a zerofield-mcp tool must be MCP-exposed, default to auto, and need no switches or primary role.')
    _check_schema(tool, tool.schema, 'inputSchema', top=True)


def _check_schema(tool, schema, path, top=False):
    def bad(message):
        raise ValueError(f'Tool {tool.name!r}: {path} {message}')
    if not isinstance(schema, dict) or schema.get('type') not in _KEYWORDS:
        bad('needs a supported type: ' + ', '.join(_KEYWORDS) + '.')
    kind = schema['type']
    unknown = set(schema) - _KEYWORDS[kind] - _SCHEMA_ANNOTATIONS
    if unknown:
        bad('uses keywords validate_args does not enforce: ' + ', '.join(sorted(unknown)) + '.')
    if top and (kind != 'object' or schema.get('additionalProperties', True) is not False
                or not isinstance(schema.get('properties'), dict)):
        bad('must be a closed object: properties plus additionalProperties false.')
    count = lambda key: key not in schema or (type(schema[key]) is int and schema[key] >= 0)  # noqa: E731
    if kind == 'object':
        properties = schema.get('properties', {})
        if not isinstance(properties, dict):
            bad('properties must be a dict.')
        for key, item in properties.items():
            _check_schema(tool, item, f'{path}.{key}')
        required = schema.get('required', [])
        if not isinstance(required, list) or any(key not in properties for key in required):
            bad('required may only name declared properties.')
        extra = schema.get('additionalProperties', True)
        if isinstance(extra, dict):
            _check_schema(tool, extra, path + '.*')
        elif type(extra) is not bool:
            bad('additionalProperties must be a boolean or a schema.')
    elif kind == 'string':
        if not count('minLength') or not count('maxLength'):
            bad('lengths must be non-negative integers.')
        if 'enum' in schema and (not isinstance(schema['enum'], list) or not all(isinstance(v, str) for v in schema['enum'])):
            bad('enum must list strings.')
        if 'pattern' in schema:
            try:
                re.compile(schema['pattern'])
            except (re.error, TypeError):
                bad('pattern must be a valid regular expression.')
    elif kind == 'integer':
        if any(key in schema and type(schema[key]) is not int for key in ('minimum', 'maximum')):
            bad('bounds must be integers.')
        if 'enum' in schema and (not isinstance(schema['enum'], list) or not all(type(v) is int for v in schema['enum'])):
            bad('enum must list integers.')
    elif kind == 'array':
        if 'items' not in schema:
            bad('needs an items schema.')
        _check_schema(tool, schema['items'], path + '[]')
        if not count('minItems') or not count('maxItems'):
            bad('item counts must be non-negative integers.')
        if 'uniqueItems' in schema and type(schema['uniqueItems']) is not bool:
            bad('uniqueItems must be a boolean.')


# ---------- argument validation shared by every transport ----------

_MESSAGES = {
    True: {'arguments': 'Unknown or missing Studio tool arguments.', 'string': 'Invalid Studio string length.',
           'option': 'Invalid Studio option.', 'selection': 'Invalid Studio selection.',
           'duplicate': 'Duplicate Studio selection.'},
    False: {'arguments': 'Unknown or missing tool arguments.', 'string': 'Invalid tool string length.',
            'option': 'Invalid tool option.', 'selection': 'Invalid tool selection.',
            'duplicate': 'Duplicate tool selection.'},
}


def validate_args(name, args) -> None:
    """Raise ValueError unless args match the tool's declared schema; never trust MCP or client validation.

    Strings reject NUL and default to at most 10000 characters, as the Studio validator always did."""
    tool = _TOOLS.get(name)
    if tool is None:
        raise ValueError(f'Tool {name} does not exist.')
    _validate(args, tool.schema, _MESSAGES[tool.category in STUDIO_CATEGORIES])


def _validate(value, schema, messages):
    kind = schema['type']
    if kind == 'object':
        properties = schema.get('properties', {})
        extra = schema.get('additionalProperties', True)
        if (not isinstance(value, dict) or not set(schema.get('required', ())) <= value.keys()
                or extra is False and set(value) - properties.keys()):
            raise ValueError(messages['arguments'])
        for key, item in value.items():
            if key in properties:
                _validate(item, properties[key], messages)
            elif isinstance(extra, dict):
                _validate(item, extra, messages)
    elif kind == 'string':
        if not isinstance(value, str) or '\x00' in value or not schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', 10000):
            raise ValueError(messages['string'])
        if 'enum' in schema and value not in schema['enum'] or 'pattern' in schema and not re.fullmatch(schema['pattern'], value):
            raise ValueError(messages['option'])
    elif kind == 'integer':
        if (type(value) is not int or value < schema.get('minimum', value) or value > schema.get('maximum', value)
                or 'enum' in schema and value not in schema['enum']):
            raise ValueError(messages['option'])
    elif kind == 'boolean':
        if type(value) is not bool:
            raise ValueError(messages['option'])
    elif kind == 'array':
        if not isinstance(value, list) or not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', len(value)):
            raise ValueError(messages['selection'])
        for item in value:
            _validate(item, schema['items'], messages)
        if schema.get('uniqueItems') and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            raise ValueError(messages['duplicate'])


# ---------- built-in declarations ----------

_S = {"type": "string"}
_RO = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
_ID = {'type': 'string', 'minLength': 1, 'maxLength': 180}
_TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 10000}
_IDS = {'type': 'array', 'items': _ID, 'minItems': 1, 'maxItems': 200, 'uniqueItems': True}
_EVERYONE = BUILTIN_ROLES
_WORKBOOK_READERS = ('coordinator', 'sheet_ops', 'qa_critic')


def _obj(props: dict, required=()) -> dict:
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


def _legacy(name, description, schema, **declared):
    return Tool(name, description, schema, 'legacy', 'project_assistant.tools:' + name, **declared)


def _delegation(name, description, schema, **declared):
    return Tool(name, description, schema, 'delegation', 'project_assistant.delegation_tools:' + name, **declared)


def _studio(name, description, schema, *, category='studio', read_only=False, mutating=True, ui=True, **declared):
    # Studio tools spend or change production resources, so they are mutating (journaled, no viewers).
    return Tool(name, description, schema, category, 'project_assistant.studio_tools:' + name, mutating=mutating,
                annotations={'readOnlyHint': read_only, 'destructiveHint': False}, ui=ui, **declared)


register(
    _legacy("propose_table_edit",
            "跨分頁批次修改表格；先 read_page 取得 row_id/table_id，cells 用零起算欄號。new_rows 為完整儲存格陣列。只建立可審核提案，確認後才寫入，過期或鎖定時整批拒絕。",
            # new_rows is optional, as in every consumer (args.get("new_rows", []), proposal_output, the HTTP
            # table edit); the pre-registry schema listed it as required but nothing enforced it.
            _obj({"tab_key": _S, "table_id": _S,
                  "row_edits": {"type": "array", "items": _obj({"row_id": _S, "cells": {"type": "object", "additionalProperties": {"type": "string"}}}, ["row_id", "cells"])},
                  "new_rows": {"type": "array", "items": {"type": "array", "items": _S}}}, ["tab_key", "row_edits"]),
            annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
            mutating=True, analysis_only=False, label="Propose Slate Changes", grants=('coordinator', 'sheet_ops'),
            zerofield_mcp=True),
    _legacy("list_pages", "列出專案頁所有分頁：代號、名稱、第一段說明。", _obj({}),
            annotations=_RO, label="Production Pages", grants=_EVERYONE, zerofield_mcp=True),
    _legacy("read_page",
            "讀專案頁某一個分頁的最新內容。key 用 list_pages 的代號（也可以寫分頁名稱）；section 可以只讀某一段"
            "（段落標題的關鍵字）。狀態會顯示成〔等待回覆〕這種樣子，可填的空格顯示成（空白，可填）。",
            _obj({"key": _S, "section": _S, "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 30}}, ["key"]),
            annotations=_RO, label="Production Page", grants=_EVERYONE, zerofield_mcp=True),
    _legacy("search_pages", "在整個專案頁搜尋關鍵字，回傳出現在哪個分頁、哪一段，以及那一行。",
            _obj({"query": _S}, ["query"]), annotations=_RO, label="Search Pages", grants=_EVERYONE),
    _legacy("my_todo",
            "目前這位使用者的待辦：負責人交代的事、要回答的待確認問題和狀態、交接追蹤上行銷要交的東西、@ 他還沒解決的討論。",
            _obj({}), annotations=_RO, label="Tasks", grants=('coordinator',)),
    _legacy("report_list", "列出行銷提供的報表：代號、用途、工作表。報表裡的數字一律看不到，只有結構和公式。",
            _obj({}), annotations=_RO, label="Workbooks", grants=_WORKBOOK_READERS),
    _legacy("report_overview",
            "看一本報表的總覽：每張工作表的大小、日期範圍、最後有填資料的日期、表頭、是否隱藏、Power Query。"
            "code 用 report_list 的代號。",
            _obj({"code": _S}, ["code"]), annotations=_RO, label="Workbook Overview", grants=_WORKBOOK_READERS),
    _legacy("report_sheet",
            "看某一張工作表每一欄的內容：欄名、是手動輸入還是公式、公式寫法（同一欄常見的寫法，[r] 代表同一列、"
            "[r-1] 代表上一列）、最後有填的日期、文字值。columns 可以只看某幾欄，例如 \"A:K\" 或 \"B,F,AA\"。",
            _obj({"code": _S, "sheet": _S, "columns": _S}, ["code", "sheet"]), annotations=_RO, label="Worksheet",
            grants=_WORKBOOK_READERS),
    _legacy("report_cell",
            "看某一格：它屬於哪一欄（欄名）、那一列是哪一天、是手動輸入還是公式；是公式就給公式（手打的數字已遮成 ▢）。"
            "手動輸入的數值不提供。cell 例如 \"F12\"。",
            _obj({"code": _S, "sheet": _S, "cell": _S}, ["code", "sheet", "cell"]), annotations=_RO,
            label="Worksheet Cell", grants=_WORKBOOK_READERS),
    _legacy("report_find",
            "在報表裡找字：工作表名稱、表頭、文字格、公式寫法。例如找「0.65」「營運」「首日」。code 可以只找某一本。",
            _obj({"text": _S, "code": _S}, ["text"]), annotations=_RO, label="Search Workbooks", grants=_WORKBOOK_READERS),
    _legacy("offer_document",
            "對方明確要「廣告數據專案總覽」的文件檔（Word）、要下載、或要轉寄給別人時才呼叫；呼叫後，這則回答下方會出現"
            "下載按鈕。回答裡請說「請按下面的按鈕下載」，不要自己貼網址；對方沒要就不要呼叫。檔案內容是專案頁下載當下的最新版。",
            _obj({}), annotations=_RO, label="Prepare Document Download", grants=('coordinator', 'doc_writer')),
    _legacy("propose",
            "提出一項專案頁的修改，等使用者在畫面上按確認才會生效（這個工具本身不會改任何東西）。"
            "action：寫進那一題的討論（要 page、row、content）、改狀態（page、row、status）、"
            "填交接追蹤（page、row、content；那一列可填的格子不只一個時加 column）、"
            "留言問負責人（page，加 row 或 quote，content）、"
            "在段落加標註（page、quote＝頁面上一字不差的一段字、label、content 可空白）、"
            "私下轉給負責人（只要 content，只有負責人看得到）。"
            "page 寫分頁代號或名稱；row 寫題號（例如 1；別張表的第 1 題寫「營運 1」）或那一列第一格的名稱"
            "（例如 AppsFlyer 事件名稱）。content 用使用者的口吻。",
            _obj({"action": {"type": "string", "enum": PROPOSE_ACTIONS}, "page": _S, "row": _S, "column": _S,
                  "quote": _S, "label": {"type": "string", "enum": list(PROPOSE_LABELS)},
                  "status": {"type": "string", "enum": list(STATUSES)}, "content": _S}, ["action"]),
            annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
            mutating=True, analysis_only=False, label="Propose Changes", grants=('coordinator', 'doc_writer', 'qa_critic')),
    _delegation('list_agents', '列出此專案可用代理、能力、標籤與負載。',
                _obj({'capability': _S, 'domain': _S}), annotations=_RO, label='Agents & Workers',
                primary_only=True, grants=('coordinator',)),
    _delegation('spawn_agent', '委派可追蹤的背景工作。只能縮小固定範圍；預設產出待核對提案。wait 最多等 5 秒，遇到人工決策或容量不足即回傳工作編號。',
                _obj({'objective': _S, 'target_agent': _S, 'label_selector': {'type': 'object', 'additionalProperties': _S},
                      'scope': {'type': 'object'}, 'target': {'type': 'object'}, 'depends_on': {'type': 'array', 'items': _S},
                      'strategy': {'type': 'string', 'enum': ['single', 'race', 'fanout_rows']}, 'race_agents': {'type': 'array', 'items': _S},
                      'write_mode': {'type': 'string', 'enum': ['proposal', 'analysis_only']}, 'wait': {'type': 'boolean'}}, ['objective']),
                mutating=True, label='Assign Task', primary_only=True, requires=('allow_subagents',), grants=('coordinator',)),
    _delegation('check_delegation', '查詢自己交辦的工作進度、摘要、待核對提案和問題。',
                _obj({'run_id': _S, 'dispatch_handle': _S}), annotations=_RO, label='Task Progress',
                primary_only=True, grants=('coordinator',)),
    _delegation('cancel_delegation', '以精確派發憑證取消工作，作廢未核對的提案。',
                _obj({'dispatch_handle': _S, 'reason': _S}, ['dispatch_handle']),
                mutating=True, label='Cancel Task', primary_only=True, grants=('coordinator',)),
    _delegation('ask_decision_gate', '建立需要使用者決定的問題，提供 2～5 個明確選項。保存工作後釋放執行名額；回答後由系統續跑。',
                _obj({'question': _S, 'options': {'type': 'array', 'items': _S, 'minItems': 2, 'maxItems': 5},
                      'context_tab': _S, 'blocking_task_ids': {'type': 'array', 'items': _S}}, ['question', 'options']),
                mutating=True, label='Decision Required', grants=_EVERYONE),
    _delegation('trigger_flow_run', '核對來源與權限後啟動已儲存工作流。單步使用 execution_mode=single_step 及 node_id；批次可用 start_node_id。',
                _obj({'flow_tab_key': _S, 'execution_mode': {'type': 'string', 'enum': ['workflow', 'single_step']},
                      'node_id': _S, 'start_node_id': _S, 'sample_row_id': _S, 'row_ids': {'type': 'array', 'items': _S}, 'target_tab': _S}, ['flow_tab_key']),
                mutating=True, analysis_only=False, label='Run Pipeline', primary_only=True, requires=('allow_workflows',),
                grants=('coordinator',)),
    # Studio wire schemas; production-changing ones ask first and wait for the race winner's review.
    _studio('studio_ingest_script', 'Review a script import, asset extraction and storyboard construction in the active episode.',
            _obj({'episode_id': _ID, 'script': {'type': 'string', 'minLength': 1, 'maxLength': 100000}}, ['episode_id', 'script']),
            policy='always_ask', analysis_only=False, race_candidate=False, grants=('coordinator', 'doc_writer')),
    _studio('studio_manage_asset', 'Review a cast/set/prop or costume variant change in the active production.',
            _obj({'episode_id': _ID, 'operation': {'type': 'string', 'enum': ['create', 'update', 'variant']},
                  'asset_id': _ID, 'type': {'type': 'string', 'enum': ['CHARACTER', 'SCENE', 'PROP']}, 'name': {'type': 'string', 'minLength': 1, 'maxLength': 200},
                  'prompt': _TEXT, 'key': {'type': 'string', 'pattern': '^[a-z0-9_-]{1,60}$'}, 'kind': {'type': 'string', 'enum': ['OUTFIT', 'POSE', 'LOOK']}},
                 ['episode_id', 'operation', 'name', 'prompt']),
            policy='always_ask', analysis_only=False, race_candidate=False, grants=('coordinator', 'doc_writer')),
    _studio('studio_plan_allocation', 'Preview actual configuration_and_inputs readiness; retain the returned allocationId for dispatch.',
            _obj({'episode_id': _ID, 'shot_ids': _IDS, 'budget_mode': {'type': 'string', 'enum': ['lab_economical', 'hybrid_balanced', 'deadline_rush']},
                  'time_pressure': {'type': 'string', 'enum': ['low', 'normal', 'high']}, 'app_code': _ID}, ['episode_id']),
            read_only=True, external=True, grants=('coordinator', 'sheet_ops')),
    _studio('studio_dispatch_shot', 'Consume an authorized allocation once and enqueue M8 media proposals, never select a candidate.',
            _obj({'episode_id': _ID, 'shot_ids': _IDS, 'allocation_id': _ID}, ['episode_id', 'shot_ids', 'allocation_id']),
            policy='always_ask', analysis_only=False, race_candidate=False, grants=('coordinator', 'sheet_ops')),
    _studio('studio_inspect_frames', 'Inspect authorized source/candidate video as an attached timestamped 8-frame contact sheet.',
            _obj({'episode_id': _ID, 'shot_id': _ID, 'candidate_id': _ID}, ['episode_id', 'shot_id']),
            read_only=True, external=True, grants=('coordinator', 'sheet_ops', 'qa_critic')),
    _studio('studio_edit_timeline', 'Review a shot split, merge, or episode rough-cut export.',
            _obj({'episode_id': _ID, 'operation': {'type': 'string', 'enum': ['split', 'merge', 'export']}, 'shot_ids': _IDS}, ['episode_id', 'operation']),
            policy='always_ask', analysis_only=False, race_candidate=False, grants=('coordinator', 'sheet_ops')),
    _studio('consult_advisor', 'Ask the configured independent specialist for one bounded, read-only critique; no delegation.',
            _obj({'question': {'type': 'string', 'minLength': 1, 'maxLength': 4000}, 'candidate': {'type': 'string', 'maxLength': 12000}}, ['question']),
            category='advisor', read_only=True, external=True, requires=('advisor_agent_key',),
            grants=('coordinator', 'doc_writer', 'sheet_ops')),
)

# External-agent tools (SPEC_20 R30, §4.7). No built-in role receives them by default; an admin may still
# grant them in the Console. request_generation dispatches only for a generate-mode service account.
register(
    Tool('get_workflow',
         'Read a ZeroField workflow guide (skills/<name>/SKILL.md), such as crew pre-production, beat prompts, '
         '3D blocking or continuity checks. Without name, lists the installed guides. A long guide is returned '
         'in pages: call again with the offset it gives. Guides describe the work; the tools still enforce '
         'scope, review and spending limits.',
         _obj({'name': {'type': 'string', 'pattern': '^[a-z0-9][a-z0-9-]{0,63}$'},
               'offset': {'type': 'integer', 'minimum': 0, 'maximum': 1000000}}),
         'workflow', 'project_assistant.external_tools:get_workflow', annotations=_RO, label='Workflow Guide',
         zerofield_mcp=True),
    Tool('request_generation',
         'Request video takes for shots of one episode through the production policy and return the cost '
         'estimate. Only free local open-weights renders are submitted; a plan with closed, hosted or paid '
         'generation is refused so a crew member can review it in ZeroField. Takes arrive as candidates for '
         'review and are never adopted automatically. request_id makes retries safe: the same request_id with '
         'the same arguments returns the first result without submitting again.',
         # At most 40 shots, so the result (one task per shot) stays within the tool output limit.
         _obj({'episode_id': _ID, 'shot_ids': {**_IDS, 'maxItems': 40},
               'request_id': {'type': 'string', 'pattern': '^[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}$'},
               'budget_mode': {'type': 'string', 'enum': ['lab_economical', 'hybrid_balanced', 'deadline_rush']},
               'app_code': _ID}, ['episode_id', 'shot_ids', 'request_id']),
         'generation', 'project_assistant.external_tools:request_generation', mutating=True, analysis_only=False,
         race_candidate=False, label='Request Generation', zerofield_mcp=True,
         annotations={'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': True, 'openWorldHint': False}),
)

for _module in EXTENSIONS:
    register(*importlib.import_module(_module).TOOLS)
_sealed = True


# ---------- derived views (the registry is sealed, so these never go stale) ----------

def all_tools() -> tuple[Tool, ...]:
    """Every declared tool in registration order (the order models and MCP clients see)."""
    return tuple(_TOOLS.values())


def get(name) -> Tool | None:
    return _TOOLS.get(name)


def specs() -> list[dict]:
    """Fresh copies of every tool's MCP spec, in registration order (tool_specs.TOOLS)."""
    return [copy.deepcopy(tool.spec()) for tool in _TOOLS.values()]


def _names(keep) -> frozenset:
    return frozenset(tool.name for tool in _TOOLS.values() if keep(tool))


NAMES = frozenset(_TOOLS)
MUTATING = _names(lambda t: t.mutating)
DELEGATION = _names(lambda t: t.category == 'delegation')
STUDIO = _names(lambda t: t.category in STUDIO_CATEGORIES)
PRIMARY_ONLY = _names(lambda t: t.primary_only)
ANALYSIS_ONLY_DENIED = _names(lambda t: not t.analysis_only)
RACE_DENIED = _names(lambda t: not t.race_candidate)
EXTERNAL = _names(lambda t: t.external)
CONSOLE = _names(lambda t: t.console)
MCP = _names(lambda t: t.mcp)

# Categories that predate zerofield-mcp: their tools reach external agents only by declaring zerofield_mcp=True.
INTERNAL_CATEGORIES = ('legacy', 'delegation')


def zerofield_exposed(tool) -> bool:
    """Whether zerofield-mcp may list this tool to a service-account token (SPEC_20 R30).

    An explicit zerofield_mcp wins. Otherwise only a read-only MCP tool outside INTERNAL_CATEGORIES, running
    inside the shared transaction with an auto default and no switches or primary role, is exposed; so the
    R16 read tools appear without extra flags, while every write must opt in."""
    if tool.zerofield_mcp is not None:
        return tool.zerofield_mcp
    return (tool.mcp and not tool.mutating and not tool.external and tool.category not in INTERNAL_CATEGORIES
            and tool.policy == 'auto' and not tool.requires and not tool.primary_only)


ZEROFIELD_MCP = _names(zerofield_exposed)
GENERATION = _names(lambda t: t.category == 'generation')  # never listed to propose_only tokens
UI = tuple(tool.name for tool in _TOOLS.values() if tool.ui)
REQUIRES = MappingProxyType({tool.name: tool.requires for tool in _TOOLS.values() if tool.requires})
DEFAULT_POLICIES = MappingProxyType({tool.name: tool.policy for tool in _TOOLS.values()})
LABELS = MappingProxyType({tool.name: tool.label for tool in _TOOLS.values() if tool.label})

# Seeded allowed_tools are ordered JSON lists and the pristine-seed upgrade compares them exactly, so
# worker roles keep this historic order; tools not listed here (every new one) follow in registration
# order. The Showrunner's list is alphabetical.
_HISTORIC_GRANT_ORDER = ('list_pages', 'read_page', 'search_pages', 'report_cell', 'report_find', 'report_list',
                         'report_overview', 'report_sheet', 'propose', 'propose_table_edit', 'offer_document',
                         'studio_ingest_script', 'studio_manage_asset', 'studio_plan_allocation', 'studio_dispatch_shot',
                         'studio_inspect_frames', 'studio_edit_timeline', 'consult_advisor', 'ask_decision_gate')


def default_grants(role, orchestration=True) -> list[str]:
    """Ordered default allowed_tools of a built-in role; orchestration=False leaves out delegation tools."""
    names = [t.name for t in _TOOLS.values() if role in t.grants and (orchestration or t.category != 'delegation')]
    if role in PRIMARY_ROLES:
        return sorted(names)
    historic = {name: rank for rank, name in enumerate(_HISTORIC_GRANT_ORDER)}
    position = {name: rank for rank, name in enumerate(_TOOLS)}
    return sorted(names, key=lambda name: (historic.get(name, len(historic)), position[name]))


def handler(name):
    """Resolve one tool's handler, importing its module on first use."""
    module, _, attribute = _TOOLS[name].handler.partition(':')
    return getattr(importlib.import_module(module), attribute)


def handlers(module, namespace) -> dict:
    """{tool name: function} for the tools whose handler lives in `module`, read from its namespace.

    Call it at the bottom of the handler module: `HANDLERS = tool_registry.handlers(__name__, globals())`."""
    table = {}
    for tool in _TOOLS.values():
        owner, _, attribute = tool.handler.partition(':')
        if owner == module:
            function = namespace.get(attribute)
            if not callable(function):
                raise LookupError(f'Tool {tool.name!r}: handler {tool.handler} is not defined.')
            table[tool.name] = function
    return table

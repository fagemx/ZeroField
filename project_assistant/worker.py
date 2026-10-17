"""Standalone assistant worker: lease queued messages, call the configured provider,
persist proposals and responses, and refresh configured report sources.
Codex CLI is selected explicitly; OpenAI-compatible failures keep that provider.
"""
from __future__ import annotations

import base64
import concurrent.futures
import datetime as dt
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

from project_assistant import codex_runner, model_client, privacy, prompting, report_index, store, tools
from project_assistant.tool_host import ToolHost, summarize
from project_assistant.tools import ToolContext
from project_docs.service import ROLE_LABEL

DEFAULT_MODEL = "gpt-6.1-sol"
DEFAULT_EFFORT = "medium"
ENGINES = ("direct", "codex")
DIRECT_VERSION = "direct"  # 存在 codex_version 欄，管理頁照版本分組
FALLBACK_KINDS = ("auth", "unavailable")  # 直接呼叫遇到這些，這一輪改走 Codex CLI
PARTIAL_EVERY = 0.4  # 寫到一半的字最快多久存一次（秒）
LEASE_SECONDS = 300
HEARTBEAT_SECONDS = 60
REPORT_EVERY = 600
TAIPEI = dt.timezone(dt.timedelta(hours=8))
MESSAGES = {
    "retry_exhausted": "這次沒答完，請再送一次；一直這樣的話，請直接留言給負責人。",
    "quota": "助理暫時忙不過來（額度用完），請晚一點再試，或直接留言給負責人。",
    "lockdown": "這一輪被系統停下來了，沒有給出回答。請換個說法再問一次，或直接留言給負責人。",
    "not_member": "助理還沒開放給你，請找負責人。",
}


def _log(message: str) -> None:
    print(f"project-assistant: {message}", flush=True)


@dataclass(frozen=True)
class Settings:
    codex: object
    model: str
    effort: str
    runtime_root: Path | None
    python: str
    mcp_script: Path
    timeout: int
    concurrency: int
    engine: str  # direct（預設）／codex


def settings_from_env(env=None) -> Settings:
    env = os.environ if env is None else env
    root = env.get("OPENBENCH_RUNTIME_ROOT")
    engine = (env.get("PROJECT_ASSISTANT_ENGINE") or "direct").strip().lower()
    if env.get("OPENBENCH_PROVIDER") == "codex_cli":
        engine = "codex"
    return Settings(codex=env.get("CODEX_PATH") or "codex",
                    model=env.get("OPENBENCH_MODEL") or env.get("PROJECT_ASSISTANT_MODEL") or DEFAULT_MODEL,
                    effort=env.get("PROJECT_ASSISTANT_EFFORT") or DEFAULT_EFFORT,
                    runtime_root=Path(root) if root else None, python=sys.executable,
                    mcp_script=Path(__file__).resolve().parent / "mcp_stdio.py",
                    timeout=int(env.get("PROJECT_ASSISTANT_TIMEOUT") or 240),
                    concurrency=int(env.get("PROJECT_ASSISTANT_CONCURRENCY") or 2),
                    engine=engine if engine in ENGINES else "direct")


def data_root(settings: Settings) -> Path:
    base = settings.runtime_root or (Path(__file__).resolve().parents[1] / ".openbench_runtime")
    return base / "project-assistant"


def report_dir(settings: Settings, slug: str) -> Path:
    return data_root(settings) / slug / "reports"


def deployment_pending(settings: Settings) -> bool:
    return bool(settings.runtime_root and (settings.runtime_root / "deployment" / "deployment.lock").exists())


def _identity(conn, owner_id: str):
    from project_docs import repository as repo
    from project_docs.service import Identity

    member = next((m for m in repo.active_members(conn) if m["actor_id"] == owner_id), None)
    return Identity(actor_id=member["actor_id"], name=member["name"], role=member["role"]) if member else None


def _with_conn(connection_factory, action):
    conn = connection_factory()
    try:
        value = action(conn)
        conn.commit()
        return value
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@dataclass
class Outcome:
    """一輪跑完的結果；直接呼叫和 Codex CLI 兩條路都整理成這個樣子再存。"""

    status: str  # ok／quota／lockdown／error
    answer: str = ""
    blocked: str = ""
    kind: str = ""
    detail: str = ""
    version: str = ""


class _PartialWriter:
    """邊寫邊顯示：把寫到一半的字存進那一則回答（同一條連線、最快每 PARTIAL_EVERY 秒一次）。"""

    def __init__(self, connection_factory, message_id: int, worker_id: str):
        self.factory, self.message_id, self.worker_id = connection_factory, message_id, worker_id
        self.conn = None
        self.at = 0.0
        self.last = None

    def write(self, text: str, *, force: bool = False) -> None:
        if text == self.last or (not force and time.monotonic() - self.at < PARTIAL_EVERY):
            return
        try:
            if self.conn is None:
                self.conn = self.factory()
            store.write_partial(self.conn, self.message_id, self.worker_id, text)
            self.conn.commit()
            self.at, self.last = time.monotonic(), text
        except Exception as exc:  # noqa: BLE001 - 半段沒存到只是畫面慢一點，不能讓這一輪失敗
            _log(f"partial write failed: {type(exc).__name__}: {exc}")
            self.close()

    def close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:  # noqa: BLE001
                pass
            self.conn = None


def _tool_caller(ctx, record):
    """直接呼叫時，模型要用工具就在這個程序裡呼叫；「正在看：…」照樣記下來。"""

    def call_tool(name: str, args: dict) -> str:
        summary = summarize(name, args)
        try:
            text = tools.call(ctx, name, args)
            summary["ok"] = True
        except tools.ToolError as exc:
            text, summary["ok"] = f"工具錯誤：{exc}", False
        except Exception as exc:  # noqa: BLE001 - 工具壞了要回給模型，不能讓這一輪卡住
            _log(f"tool {name} failed: {type(exc).__name__}: {exc}")
            text, summary["ok"] = "工具錯誤：工具出錯了，請換個方式再試一次", False
        summary["at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        try:
            record(summary)
        except Exception as exc:  # noqa: BLE001
            _log(f"could not record tool call: {type(exc).__name__}: {exc}")
        return text

    return call_tool


def _run_direct(connection_factory, claim, settings: Settings, worker_id: str, ctx, record, parts,
                images=()) -> Outcome:
    from project_assistant import providers
    instructions, turn_text = parts
    writer = _PartialWriter(connection_factory, claim["id"], worker_id)

    def on_round(number: int) -> None:
        if number > 1:  # 前一輪查資料前說的話不算回答，換一輪就清掉
            writer.write("", force=True)

    provider_cfg = providers.provider_from_env()
    try:
        if provider_cfg.kind == "openai_compat":
            result = providers.run_openai_compat_turn(
                config=provider_cfg, instructions=instructions, turn_text=turn_text,
                call_tool=_tool_caller(ctx, record), timeout=settings.timeout,
                on_text=writer.write, on_round=on_round, images=images)
        else:
            result = model_client.run_turn(
                instructions=instructions, turn_text=turn_text, call_tool=_tool_caller(ctx, record),
                model=settings.model, effort=settings.effort, cache_key=f"pa-{claim['slug']}-{claim['owner_id']}",
                timeout=settings.timeout, on_text=writer.write, on_round=on_round, images=images)
    finally:
        writer.close()
    usage = result.usage
    first = "-" if result.first_text is None else f"{result.first_text}s"
    _log(f"turn {claim['id']} {provider_cfg.kind} {result.status}: {result.rounds} rounds, first text {first}, "
         f"{result.seconds}s, in {usage.get('input_tokens', 0)} (cached {usage.get('cached_tokens', 0)}) "
         f"out {usage.get('output_tokens', 0)} (reasoning {usage.get('reasoning_tokens', 0)})")
    return Outcome(status=result.status, answer=result.answer, blocked=result.blocked,
                   kind=result.error_kind or result.status, detail=result.error, version=provider_cfg.kind or DIRECT_VERSION)


def _run_codex(settings: Settings, host, prompt: str) -> Outcome:
    url, token = host.start()
    workdir = Path(tempfile.mkdtemp(prefix="pa-turn-"))
    try:
        result = codex_runner.run(prompt, codex=settings.codex, model=settings.model, effort=settings.effort,
                                  mcp_python=settings.python, mcp_script=settings.mcp_script, tool_url=url,
                                  token=token, timeout=settings.timeout, workdir=workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    status = result.status if result.status in ("ok", "quota", "lockdown") else "error"
    return Outcome(status=status, answer=result.answer, blocked=result.blocked, kind=result.status,
                   detail=str(result.errors[-1:] or result.stderr_tail[-300:]),
                   version=codex_runner.codex_version(settings.codex) if status == "ok" else "")


def execute(connection_factory, claim: dict, settings: Settings, worker_id: str) -> str:
    started = time.monotonic()
    stop = threading.Event()

    def heartbeat():
        while not stop.wait(HEARTBEAT_SECONDS):
            try:
                _with_conn(connection_factory, lambda c: store.renew(c, claim["id"], worker_id, LEASE_SECONDS))
            except Exception as exc:  # noqa: BLE001
                _log(f"heartbeat failed: {type(exc).__name__}: {exc}")

    threading.Thread(target=heartbeat, daemon=True, name="pa-heartbeat").start()
    host = None
    try:
        conn = connection_factory()
        try:
            me = _identity(conn, claim["owner_id"])
            if not me or not (me.can_edit or store.is_member_enabled(conn, claim["slug"], me.actor_id)):
                status = store.fail(conn, claim["id"], worker_id, kind="not_member", body=MESSAGES["not_member"],
                                    retry=False)
                conn.commit()
                return status
            question = store.message(conn, claim["reply_to"])
            history = store.history(conn, claim["slug"], me.actor_id, before_id=claim["reply_to"])
            pending = store.proposals(conn, claim["slug"], owner_id=me.actor_id, status="pending")
            files = store.turn_attachments(conn, claim["reply_to"])
            privacy_mode = privacy.mode(conn, claim["slug"])
            conn.rollback()
        finally:
            conn.close()
        system, knowledge = prompting.load()
        if question.get("request_scope"):
            scope = {k: v for k, v in question["request_scope"].items() if k != "fingerprint"}
            system += "\n這次使用者固定的處理範圍如下。可跨分頁讀參考，修改只能對此範圍提出提案；不要猜測其他列或新增資料。\n" + json.dumps(scope, ensure_ascii=False)
        system += ("\n目前專案 privacy_mode=mask_numbers：數值已遮罩，禁止猜測或還原；圖片不提供。" if privacy_mode == "mask_numbers"
                   else "\n目前專案 privacy_mode=full_access：允許完整讀寫、計算數值、公式、鏡號和 Seed。")
        prompt_args = dict(system=system, knowledge=knowledge, today=dt.datetime.now(TAIPEI).date(),
                           owner_name=me.name, owner_role=ROLE_LABEL.get(me.role, "行銷"), history=history,
                           pending=pending, message=question["body"], guard_notes=question.get("notes") or [],
                           attachments=[{"kind": f["kind"], "name": f["name"], "extracted": f["extracted"]}
                                        for f in files])
        prompt_args = privacy.sanitize(prompt_args, privacy_mode)
        # 圖片交給助理的是預覽那張（長邊 1500 內的 WebP），跟她的話放在同一則訊息裡
        images = ["data:image/webp;base64," + base64.b64encode(f["preview"]).decode("ascii")
                  for f in files if f["kind"] == "image" and f["preview"] and privacy_mode == "full_access"]
        if privacy_mode == "mask_numbers" and any(f["kind"] == "image" for f in files):
            prompt_args["guard_notes"].append("數值遮罩模式不會把圖片傳送給模型，請以文字描述所需內容。")
        ctx = ToolContext(connection_factory=connection_factory, slug=claim["slug"], me=me,
                          report_dir=report_dir(settings, claim["slug"]), message_id=claim["id"])

        def record(summary):
            _with_conn(connection_factory, lambda c: store.append_tool(c, claim["id"], summary))

        outcome = None
        if settings.engine == "direct":
            outcome = _run_direct(connection_factory, claim, settings, worker_id, ctx, record,
                                  prompting.build_parts(**prompt_args), images=images)
            if outcome.status == "error" and outcome.kind in FALLBACK_KINDS and outcome.version == "responses":
                # 登入或端點出問題：這一輪改走 Codex CLI（慢一點，但答得出來）
                _log(f"turn {claim['id']}: direct call {outcome.kind} ({outcome.detail[:200]}); falling back to codex")
                _with_conn(connection_factory, lambda c: store.write_partial(c, claim["id"], worker_id, ""))
                outcome = None
        if outcome is None:
            host = ToolHost(ctx, on_call=record)
            if images:  # 備援路線看不到圖片：照實說，請她用文字描述
                prompt_args["guard_notes"] = prompt_args["guard_notes"] + [
                    f"這一輪附了 {len(images)} 張圖片，但這次你看不到圖片；請照實說看不到，請對方用文字描述畫面"]
            outcome = _run_codex(settings, host, prompting.build_prompt(**prompt_args))

        def save(c):
            if outcome.status == "ok":
                done = store.finish(c, claim["id"], worker_id, body=outcome.answer,
                                    seconds=time.monotonic() - started, model=settings.model,
                                    codex_version=outcome.version)
                return "done" if done else "lost"
            if outcome.status == "quota":
                return store.fail(c, claim["id"], worker_id, kind="quota", body=MESSAGES["quota"], retry=False)
            if outcome.status == "lockdown":
                from project_docs import repository as repo

                repo.add_audit(c, claim["slug"], action="assistant_lockdown", actor_id=me.actor_id,
                               target=str(claim["id"]), detail={"blocked": outcome.blocked, "via": "assistant"})
                return store.fail(c, claim["id"], worker_id, kind="lockdown", body=MESSAGES["lockdown"], retry=False)
            _log(f"turn {claim['id']} {outcome.kind}: {outcome.detail[-300:]}")
            return store.fail(c, claim["id"], worker_id, kind=outcome.kind, body=MESSAGES["retry_exhausted"],
                              retry=True)

        return _with_conn(connection_factory, save)
    except Exception as exc:  # noqa: BLE001
        _log(f"turn {claim.get('id')} crashed: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
        try:
            _with_conn(connection_factory, lambda c: store.fail(c, claim["id"], worker_id, kind="crash",
                                                                body=MESSAGES["retry_exhausted"], retry=True))
        except Exception as inner:  # noqa: BLE001
            _log(f"could not record crash: {type(inner).__name__}: {inner}")
        return "crash"
    finally:
        stop.set()
        if host:
            host.stop()


def poll_once(connection_factory, settings: Settings, worker_id: str, submit, busy: int) -> int:
    """部署鎖在就不領；有空位就一則一則領，交給 submit。回傳這次領了幾則。"""

    if deployment_pending(settings):
        return 0
    claimed = 0
    while busy + claimed < settings.concurrency:
        claim = _with_conn(connection_factory, lambda c: store.claim_next(c, worker_id, LEASE_SECONDS))
        if not claim:
            break
        submit(claim)
        claimed += 1
    return claimed


def refresh_reports(connection_factory, settings: Settings) -> None:
    sources = _with_conn(connection_factory, lambda c: {
        slug: store.get_setting(c, slug, "report_source") for slug in store.slugs_with_setting(c, "report_source")})
    for slug, source in sources.items():
        try:
            result = report_index.refresh(Path(source), report_dir(settings, slug))
        except Exception as exc:  # noqa: BLE001
            result = {"state": "error", "error": f"{type(exc).__name__}: {exc}"[:300]}
        if result["state"] == "unchanged":
            continue
        result["checked_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        _with_conn(connection_factory, lambda c: store.set_setting(
            c, slug, "report_status", json.dumps(result, ensure_ascii=False)))


def _ensure_schema(connection_factory, shutdown) -> bool:
    from project_docs import repository as repo

    failures = 0
    while not shutdown.is_set():
        try:
            _with_conn(connection_factory, repo.ensure_schema)
            return True
        except Exception as exc:  # noqa: BLE001
            failures += 1
            _log(f"schema not ready ({failures}): {type(exc).__name__}: {exc}")
            shutdown.wait(min(60, 2 ** min(failures, 6)))
    return False


def run_forever(connection_factory, *, shutdown, settings: Settings | None = None, poll_seconds: float = 1.5):
    settings = settings or settings_from_env()
    worker_id = f"{socket.gethostname()}:{os.getpid()}:assistant"
    if not _ensure_schema(connection_factory, shutdown):
        return
    futures: set = set()
    last_report, report_future, failures = 0.0, None, 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=settings.concurrency + 1,
                                               thread_name_prefix="project-assistant") as pool:
        while not shutdown.is_set():
            futures = {f for f in futures if not f.done()}
            try:
                claimed = poll_once(connection_factory, settings, worker_id,
                                    lambda c: futures.add(pool.submit(execute, connection_factory, c, settings,
                                                                      worker_id)),
                                    len(futures))
                if time.monotonic() - last_report >= REPORT_EVERY and (report_future is None or report_future.done()):
                    last_report = time.monotonic()
                    report_future = pool.submit(refresh_reports, connection_factory, settings)
                failures = 0
            except Exception as exc:  # noqa: BLE001
                failures += 1
                wait = min(60.0, poll_seconds * (2 ** min(failures, 6)))
                _log(f"poll failed ({failures}): {type(exc).__name__}: {exc}; retry in {wait:.0f}s")
                shutdown.wait(wait)
                continue
            if not claimed:
                shutdown.wait(poll_seconds)


def _guarded(connection_factory, shutdown) -> None:
    try:
        run_forever(connection_factory, shutdown=shutdown)
    except Exception as exc:  # noqa: BLE001
        _log(f"stopped: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")


def start_in_background(connection_factory, shutdown, env=None):
    env = os.environ if env is None else env
    if (env.get("PROJECT_ASSISTANT_WORKER") or "1") == "0":
        return None
    thread = threading.Thread(target=_guarded, args=(connection_factory, shutdown), name="project-assistant",
                              daemon=True)
    thread.start()
    return thread

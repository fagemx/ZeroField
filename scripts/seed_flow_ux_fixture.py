"""Seed a synthetic, nonexecuted 10-step branching flow in the QA project only."""
import os
import psycopg
from project_assistant import flow_runner
from project_docs import repository as repo, service

SLUG = "ux-usability-1016"
KEY = "flow-10"

with psycopg.connect(os.environ["OPENBENCH_TEST_DB_URI"]) as conn:
    if not repo.get_project(conn, SLUG):
        raise SystemExit("Create the synthetic QA project first")
    actor = next(member for member in repo.active_members(conn) if member["role"] == "admin")
    me = service.Identity(actor["actor_id"], actor["name"], actor["role"])
    tabs = repo.list_tabs(conn, SLUG)
    source = next(tab for tab in tabs if tab.get("surface_type") == "sheet")
    source_tab = repo.get_tab(conn, SLUG, source["key"])
    table = next(table for table in source_tab["doc"]["content"] if table.get("type") == "table")
    if not repo.get_tab(conn, SLUG, KEY):
        repo.create_tab(conn, SLUG, key=KEY, title="十步驟分支核對", parent_key=None,
                        doc={"type": "doc", "content": []}, actor_id=me.actor_id, surface_type="flow")
    names = ["讀取資料", "整理每筆", "分類標籤", "摘要內容", "核對建議", "彙整分析", "整理異常", "生成說明", "準備寫回", "總結結果"]
    positions = [(40, 160), (350, 160), (660, 30), (660, 290), (970, 30), (970, 290), (1280, 30), (1280, 290), (1590, 160), (1900, 160)]
    nodes = []
    for i, title in enumerate(names):
        scoped = i in (1, 2, 3, 4, 6)
        nodes.append({"id": f"step{i + 1}", "title": title, "capability": "llm", "scope": "rows" if scoped else "aggregate" if i == 9 else "once",
                      "prompt": f"{title}。這是合成操作驗收資料；保留來源依據並輸出可核對的說明。",
                      "input_tabs": [source["key"]], "target": {}, "write_mode": "proposal",
                      **({"row_source": {"tab_key": source["key"], "table_id": table["attrs"]["bid"]}} if scoped or i == 9 else {}),
                      "x": positions[i][0], "y": positions[i][1]})
    links = [(1, 2), (2, 3), (2, 4), (3, 5), (4, 6), (5, 7), (6, 8), (7, 9), (8, 9), (9, 10)]
    value = {"nodes": nodes, "edges": [{"source": f"step{a}", "target": f"step{b}"} for a, b in links], "fixture": "synthetic-ux-10-step"}
    revision = flow_runner.definition(conn, SLUG, KEY)["revision"]
    if revision:
        raise SystemExit("Fixture already exists; existing edits preserved")
    flow_runner.save_definition(conn, me, SLUG, KEY, {"definition": value, "revision": revision})
    print(f"Created {SLUG}/{KEY}: 10 steps, 10 dependency edges, no execution queued")

# OpenBench M8 多代理編排 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use the executing-plans skill to implement this plan task-by-task. 若使用者另選代理分工，使用 subagent-driven-development；兩個以上平行代理必須先套用 fleet-orchestrate，兩個並行寫入者起保留唯讀 verifier。Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓使用者在既有文件／表格工作台中選擇專家代理、交辦背景任務、回答問題與核對候選提案，確認後才寫回並推進下游工作。

**Architecture:** 沿用 Python、PostgreSQL、既有 Worker、ProposalCard、固定範圍及 Flow 引擎。新增專案代理設定與持久化編排狀態；以資料庫交易控制派發、租約、取消及核對，不另建訊息中介服務。既有 Flow 管理節點相依，編排層管理綁定代理的執行，單一工作只有一個領取入口。

**Tech Stack:** Python >=3.11、psycopg 3、PostgreSQL、unittest；React 19.2、Vite 6.4.4、既有 @xyflow/react 12.12.0、Node test runner。核心階段不新增 runtime dependency。

**Spec:** [AGENT_ORCHESTRATION_SPEC.md](../../AGENT_ORCHESTRATION_SPEC.md)。同讀 [PRODUCTIZATION_ROADMAP.md](../../PRODUCTIZATION_ROADMAP.md)、[ROADMAP_COMPLETION.md](../../ROADMAP_COMPLETION.md)、[ACCEPTANCE.md](../../ACCEPTANCE.md)、[PRODUCT_UX_REPLAN.md](../../PRODUCT_UX_REPLAN.md)、[UX_IMPLEMENTATION.md](../../UX_IMPLEMENTATION.md)。

## Global Constraints

- 本文件日期：2026-10-18（Asia/Taipei）。狀態：**執行計畫已編寫；M8 尚未實作／驗收**。本次授權範圍是接手寫 plan。
- 接手基準 SHA：`72670290a9c60737478f2becc89c77110948a031`。當時工作區已有未追蹤的 `docs/AGENT_ORCHESTRATION_SPEC.md`；保留這份交接成果。開工前重新核對 HEAD／工作區差異。
- 所有產品修改在 OpenBench 範圍內；參考庫只讀，不複製私人平台程式／業務資料，不引入公司內部識別資訊。
- 延續「建立專案 → 放入文件／表格 → 描述工作 → 核對提案 → 確認寫回」；空白專案預設不變；**影片僅附件與下載，不顯示播放器**。
- 規格固定值：`primary / worker / observer`；`builtin_llm / acp_stdio / remote_limb`；`single / race / fanout_rows`；預設 `max_depth = 1`、`max_parallel_dispatches = 6`、`max_tasks_per_run = 200`；profile `max_concurrency` 預設 2、範圍 1～32；競速 2～3 位代理；問題選項 2～5 個。
- 預設角色鍵：`coordinator`、`doc_writer`、`sheet_ops`、`qa_critic`；外部手腳顯示為 `limb:<uuid>`。不得為角色硬綁規格示例中的模型品牌或型號。
- `privacy_mode` 保留 `full_access | mask_numbers`。身分、角色、租約、來源版本、鎖與固定範圍由伺服器驗證，不信任模型／瀏覽器傳入的權限欄位。
- 測試沿用 `unittest` 與 `node --test`。共享 PostgreSQL 測試序列執行；競態測試在單一測試內使用獨立連線。資料庫測試被 skip 不算通過。
- 不將歷史 **116 後端／63 前端**、build、fixture 或代理操作走查視為這輪已通過，更不視為使用者日常驗收。

## Review Focus

1. 同角色同時送出、舊租約遲到、取消後重試：只接受有效嘗試，且不能覆蓋競速的其他有效候選。測試：A2、B2、C1。
2. 切頁、刪列／改欄、來源更新與遮罩模式：範圍不可擴大，舊提案不能覆蓋新值，私有對話不可透過看板外洩。測試：A3、B1、B4、C2。
3. 當機、worker_done 重播、Gate 重複回答、父任務取消：狀態可恢復，副作用只做一次，不能讓模型佔滿執行緒等待自己派出的工作。測試：B2、B3、B5。
4. 雙人同時選不同競速勝出者，或選用時目標被鎖／改動：只有一個勝出版本，失敗時整筆回滾，舊核對入口不能繞過規則。測試：B4、C1。
5. 1280×720、鍵盤／中文輸入法、輪詢刷新與對話切換：保留草稿、選取及焦點；關閉面板仍有背景狀態提示。測試：A3、C2、E1；未實測項目明列。

---

## 1. 接手裁定：把規格接到現有程式

以下為本計畫明示的實作補充／修正，原始規格保留。實作 PR 需同步更新規格中的相應段落。

| 現況／規格落差 | 本計畫採用的決定 |
| --- | --- |
| `ensure_schema()` 目前依序執行到 `157_execution.sql`；規格將全部內容塞入 158 | A 使用 `158_agent_profiles.sql`；B 使用 `159_agent_orchestration.sql`；C 使用 `160_agent_races.sql`。各階段新增 migration，不回頭擴寫已交付 migration 來承載下一階段。開工先查號碼是否仍空閒。 |
| 規格寫 Admin / Editor，但 `Identity.can_edit` 實際僅 admin | profile 新增、修改、停用全部限 `can_edit`；一般 `can_write` 成員可交辦。暫不新增 editor 角色或逐專案 ACL。 |
| 既有提案僅 owner 能決定；規格 Gate 只寫 can_write | Gate／選用／略過須同時為 run creator 且 can_write。Admin 可取消 run、管理 profile；不因此取得他人私聊／提案內容。既有公開 Flow 摘要維持原權限。 |
| 規格同時要求 worker 提問，又稱六工具全部只供 primary | 六工具包含 `ask_decision_gate`；primary 可用全部，worker 僅可用被允許的提問工具，其餘委派／啟動工具拒絕；observer 不承接任務、不產生副作用。 |
| 規格 `max_depth` SQL 上限 3，正文僅說放寬至 2 | 本輪 API 僅接受 1 或 2，預設 1。2 不自動授予 worker 委派權；有權限的 primary 可再委派，但仍禁止循環。 |
| `propose` 同時能標註、改狀態、填欄；光有工具名稱白名單不夠 | QA 僅允許 `在段落加標註`、`寫進那一題的討論`、`留言問負責人`，拒絕改狀態、填值、私下轉送。另限制到指定寫入 scope。 |
| `tools.call()` 目前只有兩個 propose 工具 commit，其餘 rollback | 新增明確 `MUTATING_TOOLS` 集合；委派、取消、提問及 Flow 啟動必須持久化。等待只能在 commit／釋放連線後進行。 |
| Provider、Responses、MCP 都各自取得全域工具表 | 三條路都接收同一份過濾工具表；`tools.call()` 再檢查一次，不能只隱藏名稱。 |
| `open_reply()` 全 owner 阻塞；前端也用全 thread busy 禁止發送 | 送出限制改為同 slug／owner／agent；新建／切換對話保留「任一對話回答未結束就拒絕」，避免附件及歷史錯接；背景 run 可獨立運作。 |
| scope 目前只從 `message_id` 回查原訊息，dispatch 沒有這條路 | `ToolContext` 加伺服器建立的 execution context；dispatch 自 task 讀 scope，不能因 `message_id=None` 失去範圍限制。 |
| `service.apply_proposal()`／`dismiss_proposal()` 只通知 Flow | 同一交易通知編排層；不得在 commit 後另呼叫而產生「畫布已改、任務未完成」。 |
| 規格「一個 task 最新 admission」無法表示 race／fanout | 每個派發槽獨立追蹤有效 admission：single=`single`、race=`agent:<key>`、fanout=`row:<id>`；只淘汰同槽舊 attempt。 |
| `worker_done` 不等於已寫回／task 完成 | 一次執行嘗試的終態回報由 runtime／sweeper 保證一次；提案與問題仍可使 task 停在 `awaiting_gate`。 |
| `doc_writer` 現有工具能提出標註，不能任意改正文 | A 交付聊天稿／標註／Word 下載；B 的有明確 doc target 工作沿用 Flow 已有 append／replace 轉提案能力。不得假稱 A 已支援正文自動寫回。 |
| 表格檔名在規格為 `SheetSurface.jsx` | 現在 `SheetSurface.jsx` 只是 re-export；批次入口修改 `SheetWorkspace.jsx`，不要在 re-export 寫新實作。 |
| `agent_key` 帶底線，HTTP `KEY` 只接受連字號 | 新增 agent key 專用 parser，勿直接沿用 tab key regex；不得讓 `limb:<uuid>` 被當成可任意修改的 profile key。 |
| 動態編排的 direct write 會跳過主要操作路徑 | M8 新建 task 僅接受 `proposal / analysis_only`，拒絕模型指定 direct；既有使用者明確設定的 Flow direct 行為保留。 |
| 群組核對既有可局部接受 | 一般聊天維持局部接受；M8 綁定 task 的輸出整組核對，race 必須整候選選用。UI 與伺服器都要判斷綁定，不能只看 `message_id`。 |

## 2. 交付順序與檔案責任

| 階段 | 任務 | 可獨立驗收的結果 | 依賴 |
| --- | --- | --- | --- |
| M8-A | A1～A3 | 四角色設定、受控工具、同串多角色對話與點名 | 現有主線 |
| M8-B | B1～B6 | 持久化 DAG、精確租約、問題／提案閘門、對話與 Flow／遠端手腳打通 | A |
| M8-C | C1～C2 | 2～3 候選選用、集中看板、表格／段落交辦 | B |
| 驗證交接 | E1 | 三類合成工作操作證據、回歸及部署界線 | A～C |
| M8-D 選配 | D1 | 一個實測 ACP adapter ＋ mock 契約測試 | B、E1；獨立排程 |

主路徑：`A1 → A2 → A3 → B1 → B2 → B3 → B4 → B5 → B6 → C1 → C2 → E1`。預設循序施工；先交付 A 的可操作版本，再開 B。D 不阻塞 A～C。

- `agent_registry.py`：profile 種子／設定／路由／公開 roster；`agent_policy.py`：工具及 action 白名單；`agent_runtime.py`：兩種任務共用的模型執行入口。
- `orchestrator.py`：交易狀態轉換；`orchestration_store.py`：集中 SQL／claim／查詢，不另造通用 repository framework；`orchestration_service.py`：HTTP 權限與 payload。
- `proposal_output.py`：將既有 Flow 的 snapshot／結構化 output 轉提案邏輯抽出共用；不另造文件編輯引擎。
- `worker.py`：既有訊息＋dispatch 排程；`limb_worker.py`：既有遠端 adapters 加新隊列入口；`flow_runner.py`：Flow scheduler 及 profile 節點轉接。
- `AgentSelector.jsx`、`AgentBoard.jsx`、`ProposalRaceView.jsx`、`AgentSettings.jsx`：選角、看板、候選比對、管理設定；`agentModel.js`／`orchestrationModel.js` 放實際 UI 使用的純函式供 Node 測試。
- `project_docs/http.py`、`project_assistant/service.py`、`store.py` 是共用接點，同時只給一個寫入者。

如後續明確採多代理：A1/A2、B1/B2/B4/B6 均不可無視相依平行施工；C2 UI 可在 B6 payload 凍結後與 C1 後端分工。驗證以完整不可變 SHA 為準，每次 push 使舊 verdict 失效；worker receipt 不代表 acceptance 或 merge 授權。

## 3. 共用資料契約

### 3.1 Profile、工具與工作範圍

`AgentProfile` 使用規格第 4 節欄位。`provider_config` 僅存 `{kind, base_url, api_key_env, model, effort}`；不存實際 key，不接受任意環境變數名稱讀取敏感資料。管理者選用部署端 `OPENBENCH_AGENT_KEY_ENVS` 逗號分隔白名單中的 credential reference；未設定白名單就禁止自訂 api_key_env。空 provider_config 繼承既有全域 provider；白名單本身不送模型。

`kind` 先支援既有 `openai_compat / responses / codex_cli`；不把相容端點稱為所有供應商原生 API。Responses 現有認證路徑維持原語意，不將新增 `base_url/api_key_env` 欄位假裝已接上；不適用組合回 400。指定 profile provider 失敗不能悄悄回退到別的供應商；舊預設助理的既有 fallback 可保留並顯示實際執行資訊。

`allowed_tools` 儲存具體工具名稱，種子中的 `report_*` 初始化時展開，未知名稱回 400。空清單代表零工具。每次工具呼叫重新核對 active member、profile enabled、有效 lease（若有）、write mode 及 scope，撤權後不得繼續寫提案。

scope 採有 discriminator 的兩種格式：

- sheet：既有 `{target_tab, table_id, base_revision, row_ids, column_ids, fingerprint, ...}`；新增 `kind:'sheet'`，相容舊缺省。伺服器生成 fingerprint／column_indices，最多 200 列；child scope 只能縮小。
- doc：`{kind:'doc', target_tab, base_revision, block_ids, fingerprint}`；伺服器依段落 bid 及內容建立。doc replace 僅能操作固定 block_ids；append 需明確 target 且核對插入錨點。段落已改／刪除必須重新核對。

一般對話未附 scope 可跨頁讀並提案；帶 scope 的任務只允許在此範圍寫。Task 保存 `input_snapshot`（來源 tab revisions、doc／values／必要媒體參照）及 `target_snapshot`；所有候選讀相同快照。新讀取未列入的參考頁要由後端固定該 revision；race 共用同一份新增快照，不能各讀各的最新版。採用既有 privacy sanitizer 後才能送模型；保存／顯示 trace 只記工具名與安全摘要。

### 3.2 Run、Task、Dispatch

保留規格的 run/task/dispatch/message/gate 與狀態名稱，另補下列必要欄位／約束：

- run：`max_parallel_dispatches=6`、`max_tasks_per_run=200`、`client_request_id`、`request_hash`；`UNIQUE(project_slug,created_by,client_request_id)` 支援送出重播。相同 id 不同 payload 回 409。
- task：`input_snapshot`、`target_snapshot`、`parent_dispatch_id`、`flow_task_id`（nullable、unique）、`max_attempts=2`。`depends_on` 必須同 run、無重複、自依賴或循環；凍結後不修改已派出的依賴圖。
- dispatch：`slot_key`、`attempt_no`、`superseded_by`、`profile_snapshot`、`output_digest`。每次失敗重試／租約重領建立新 dispatch、新 admission；舊列不回 queued 重用。`UNIQUE(task_id,slot_key,attempt_no)`，以部分唯一索引確保每槽只有一筆未被取代的有效 queued/running/awaiting_gate/succeeded attempt。
- admission counter 統一小寫 `orchestration_admission_seq`，交易內 `UPDATE ... RETURNING` 配發；保證已提交憑證依專案單調遞增，不要求無間隔。跨表 project/run/task 歸屬採 composite FK 或交易檢查，不能只驗 UUID 存在。
- proposal：`agent_key`、`dispatch_id`、`race_group_task_id`；以 proposal.dispatch_id 取得完整 `proposal_ids`，不只使用規格單一 `dispatch.proposal_id`。一般 task 可多提案，全部接受才完成；任一拒絕則 failed，下游不跑。
- gate：增加 `blocking_task_ids`（同 run）、`continuation`、`resolution_request_id`；同 dispatch／kind 的 open gate 唯一；worker_done 以 dispatch_id 的部分唯一索引去重。

run 另加 nullable `completion_message_id` 並以 row lock 保證唯一通知；task slot 的 `retry_count`／續跑原因放 dispatch 明確欄位，`attempt_no` 每次都增加。若原 coordinator 已有 active reply，通知等該回覆結束再排入，不能違反 A2 的唯一限制。profile snapshot 可保存設定參照與名稱，不保存已解析的 API key。

`DispatchHandle = dsp_<uuid>_<decimal admission>` 是識別資料，不是認證 token。Remote lease 回覆才包含一次性 `lease_token`；資料庫只存 hash，公共 API 不回 lease/hash／provider key。

統一鎖序：需要容量鎖時先依 agent_key 排序鎖 profile，再鎖 `flow_run（如有）→ orchestration_run → task → admission counter（如需）→ dispatch → gate → proposal（依 id）→ target tab`。只取所需鎖；不得在後段反向回鎖前段。任何模型／網路等待都在交易外。

### 3.3 生命週期

- `analysis_only` 成功且無 gate：dispatch succeeded、task completed；提案工具在此 mode 直接拒絕。
- `proposal` 有輸出：dispatch／task awaiting_gate；runtime 記錄 `worker_done`，payload 標記 `awaiting_review`；全部提案接受後才 completed。無輸出且非合法純分析結果應 failed，不宣稱完成。
- worker 提問：保存 continuation，退出模型回合、釋放執行緒及 lease，task awaiting_gate；worker_done outcome=`awaiting_gate`。選答後建立同槽新 dispatch／admission，將答案與已完成工具紀錄注入 prompt；不重做已成功副作用。
- retry：每槽最多 2 次一般失敗嘗試；Gate 回覆續跑不消耗一般失敗重試額度，但仍受 run deadline／task 數及深度限制。需保存 retry count 與 continuation 的差別。
- `fanout_rows`：固定 row_ids 各一槽；每槽一張提案，所有列通過才完成。A 列通過不得使仍待審的 B 列被跳過；因其他列接受造成 revision 上升時，只允許 `verify_source()` 證明本列輸入未改的 rebase。
- `race`：不同 agent 槽均有效；重試只取代失敗的該槽；選勝者後取消未完成槽、作廢其餘提案。選最快完成者不是預設行為。
- `spawn_agent(wait=true)` 最多等待 5 秒且不超過 caller deadline；遇 Gate／容量不足立即回 handle，不佔滿 worker pool 等下游。`wait=false` 立即回 handle。DB 操作先 commit。
- 模型主控可在 `check_delegation` 後自行繼續；背景 child 全部終結時，runtime 至多建立一則帶 run 摘要的 coordinator 回覆，綁原 conversation，不污染目前切換到的新對話；以 run 的唯一 completion-message 關聯去重。
- deadline 由伺服器取 `min(requested, parent)`，若未提供 requested 則使用 parent；根任務使用既有 worker timeout 形成 dispatch deadline。Run 可另設絕對 deadline，待審不佔執行容量，但不延長明定期限。
- sweeper 每次 worker poll 檢查逾時／取消、失效租約和未完成終態記錄；不用另建排程服務。取消阻止本地下一步及寫回，無法保證已送出的第三方模型立即停止計費。

### 3.4 HTTP 與工具回覆

沿用規格九個 `/agents`、`/orchestration/*` 路由及既有 assistant API，補充：

- `POST .../assistant/messages` 接受 `{text, attachments, scope?, agent_key?}`；明確 agent_key 與內文單一有效 agent mention 衝突回 400；兩個不同 agent mentions 回 400 並引導多代理入口。`@{member_uuid}`、email、引用／code 中的 @ 不觸發派發。未知／停用 agent 明示錯誤，不默默落回 coordinator。
- `POST .../orchestration/runs`：`{client_request_id, objective, scope?, target?, agent_key?, label_selector?, strategy, race_agents?, write_mode?, depends_on?}`。初始 task 的 depends_on 只能為空；既有 run 的依賴由受控 spawn 工具建立。
- `POST .../orchestration/gates/<id>/resolve`：`{client_request_id, resolution}`；question resolution 為選項 id（顯示文字另存），race resolution=`{proposal_id}`。同請求同決定重播回已保存結果，不同決定回 409。
- `POST .../orchestration/tasks/<id>/retry`：creator/admin，建立新 attempt；取消／失敗後由人明確重試，已接受的槽不重做。整 run 已取消則建立新 run，不能部分復活。
- `GET .../orchestration/board`：`{needs_you,working,done,idle,counts,cursor}`；row 包含穩定 `id/kind/run_id/task_id/agent_key/status/target/summary`，可決定項另有 `gate_id/proposal_ids`、可取消項包含 `dispatch_id/admission_no`。提案與其 gate 去重；已失敗／取消也列 done 並顯示真實狀態。
- 列表每頁 50，最大 200，以 cursor 續取；counts 是權限過濾後全量計數。關面板只取 counts 的輕量查詢，開面板才載完整資料。
- 認證後仍逐層驗 slug、run、task、dispatch、proposal 歸屬。無權查看回 404；已知資源的操作權不足回 403；非法輸入 400；過期 lease／版本／衝突 409。工具另回穩定 code：`POLICY_DENIED / STALE_DISPATCH / SOURCE_CHANGED / CAPACITY_EXCEEDED`。

---

## 4. M8-A：先交付可操作的多角色對話

### Task A1：代理設定、種子及受控工具清單

**Files:** Create `db/158_agent_profiles.sql`, `project_assistant/agent_registry.py`, `project_assistant/agent_policy.py`, `project_assistant/prompts/coordinator.md`, `project_assistant/prompts/doc_writer.md`, `project_assistant/prompts/sheet_ops.md`, `project_assistant/prompts/qa_critic.md`, `tests/test_agent_registry.py`. Modify `project_docs/repository.py`（SCHEMA_FILES）, `project_docs/service.py`（create_project）, `project_docs/http.py`（agent routes）, `project_assistant/tools.py`, `scripts/verify_wheel.py`.

**Interfaces:** `ensure_default_agents(conn, slug)->None`; `get_agent(conn,slug,key)->dict|None`; `list_agents(conn,slug,*,capability=None,labels=None)->list[dict]`; `save_agent(conn,me,slug,body)->dict`; `resolve_mention(conn,slug,text,explicit_key=None)->str`; `tool_specs_for(profile)->list[dict]`; `authorize_tool(ctx,conn,name,args)->None`（拒絕 raise ToolError）。A1 即在 `ToolContext` 加 `agent_key='coordinator'`，其餘 execution 欄位由 B1 補上。

- [ ] **1. 寫失敗測試。** `test_defaults_are_idempotent`：重跑 seed 恰好四個 key，自訂 prompt／停用狀態不被覆蓋；既有專案 migration backfill＋新專案 create 都有角色。`test_profile_validation`：observer、unknown tool、0/33 concurrency、跨專案 bound limb 被拒；editor 不存在，member 不可改設定。

  此處與後續範例使用各測試 setUp 建立的隔離 `self.conn/self.slug/self.me`；沿用現有 PostgreSQL fixture 方式，測試自己的 teardown 依 FK 順序清理。

  ```python
  def test_defaults_are_idempotent(self):
      agent_registry.ensure_default_agents(self.conn, self.slug)
      agent_registry.ensure_default_agents(self.conn, self.slug)
      self.assertEqual({p['agent_key'] for p in agent_registry.list_agents(self.conn, self.slug)},
                       {'coordinator', 'doc_writer', 'sheet_ops', 'qa_critic'})
  ```
- [ ] **2. 執行確認 red。** `python -m unittest discover -s tests -p test_agent_registry.py -v`；預期新模組／契約尚不存在而失敗，不接受缺 DB 造成 skip 作 red。
- [ ] **3. 實作 registry／migration／policy。** 158 只加 profile、message.agent_key、proposal.agent_key、種子所需欄位；依具體工具名產生種子、profile 管理留 audit。ensure_schema 完成 DDL 後對既有 project 呼叫 seed，create_project 同交易 seed；種子插入用 ON CONFLICT DO NOTHING，不重置舊訊息。舊訊息缺省 coordinator。讀取 GET 不靠稍後 rollback 的 seed 寫入初始化。
- [ ] **4. 執行 green 與行為負例。** 同命令通過；`test_qa_cannot_change_status` 斷言 QA `propose(action='改狀態')` 拒絕且 proposal count 不變，合法標註可建立；API payload／log 不含任何測試 secret。
- [ ] **5. 記錄並提交此 slice。** 僅 stage 此任務實際差異，建議 `feat: add project agent profiles and tool policy`。依當時工作區／使用者提交規則執行，勿攜帶他人未提交成果。

### Task A2：每角色 provider 與可靠的並行回覆

**Files:** Create `project_assistant/agent_runtime.py`, `tests/test_agent_runtime.py`. Modify `project_assistant/service.py`, `project_assistant/store.py`, `project_assistant/worker.py`, `project_assistant/prompting.py`, `project_assistant/providers.py`, `project_assistant/model_client.py`, `project_assistant/tool_host.py`, `project_assistant/mcp_stdio.py`, `project_assistant/codex_runner.py`, `project_assistant/tool_specs.py`, `db/158_agent_profiles.sql`（A 尚未交付前補齊唯一約束）, `tests/test_providers.py`, `docs/WORKERS.md`（credential 白名單）.

**Interfaces:** `open_reply(conn,slug,owner_id,agent_key=None)->dict|None`（None 保留任一角色查詢）；`add_user_message(conn,slug,owner_id,body,notes,request_scope=None,*,agent_key='coordinator')->tuple[int,int]`；`run_agent(*,profile,ctx,instructions,turn_text,timeout,on_text=None,on_tool=None,images=())->Outcome`。Outcome 將現有 worker dataclass 移至 agent_runtime，worker import，避免循環依賴。Provider/Responses 原 run 函式加 `tool_specs=None`，None 僅供舊 caller 相容；profile runtime 一律傳明確清單。

- [ ] **1. 寫失敗測試。** `test_two_roles_can_queue_same_owner` 斷言 doc_writer 與 sheet_ops 同時 200，同角色第二筆 409；`test_concurrent_same_role_has_one_reply` 用兩連線 barrier 送同角色，只產生一組 user/reply。`test_all_provider_paths_reject_disallowed_tool` 覆蓋 openai_compat、Responses、MCP 強行呼叫禁止工具。

  ```python
  def test_two_roles_can_queue_same_owner(self):
      self.assertEqual(service.send(self.conn, self.me, self.slug, {'text': '整理段落', 'agent_key': 'doc_writer'})[0], 200)
      self.assertEqual(service.send(self.conn, self.me, self.slug, {'text': '核對表格', 'agent_key': 'sheet_ops'})[0], 200)
      self.assertEqual(service.send(self.conn, self.me, self.slug, {'text': '再寫一段', 'agent_key': 'doc_writer'})[0], 409)
  ```
- [ ] **2. 跑 red。** `python -m unittest discover -s tests -p test_agent_runtime.py -v`，上述斷言在現況失敗。
- [ ] **3. 接線。** 以 owner row／交易鎖序列化 enqueue，配合 `(project_slug,owner_id,agent_key)` 在 assistant queued/running 的 partial unique index；歷史重複 active reply 先保留最早一筆，其餘標 failed 並記 migration audit。158 加 message.agent_snapshot JSONB 保存本次名稱／設定及工具清單（不含 secret），profile 設定變更不重寫歷史；仍即時檢查停用／撤權。訊息查詢／claim 都帶 agent_key。從 worker 提取模型呼叫至 run_agent，保留現有 streaming／附件／privacy，不複製第二份 tool loop。MCP tools/list 從經驗證的 ToolHost 取得該回合工具表。
- [ ] **4. 跑 green。** 新測試及 `test_providers.py` 通過；不同 profile endpoint/model 接到各自 fixture；指定 provider 失敗不偷偷換供應商；撤銷角色／成員後工具呼叫無副作用。歷史依原 reply_to 所在 conversation 讀取，不使用當下 active conversation。
- [ ] **5. 提交 slice。** 建議 `feat: route assistant turns through agent profiles`；A1/A2 尚未發佈時才可一起整理 158，發佈後修正須新 migration。

### Task A3：選角、點名與多角色 UI

**Files:** Create `ui/src/assistant/AgentSelector.jsx`, `ui/src/assistant/AgentSettings.jsx`, `ui/src/assistant/agentModel.js`, `ui/tests/agents.test.mjs`. Modify `ui/src/assistant/AssistantViews.jsx`, `ui/src/assistant/useAssistant.js`, `ui/src/assistant/text.js`, `ui/src/assistant/assistant.css`, `ui/src/WorkspaceSettings.jsx`.

**Interfaces:** `AgentSelector({agents,value,onChange,disabled})`；`resolveAgentTarget(text,explicitKey,agents)` 與後端 A1 使用相同 fixture 語意；`openReplies(thread)->Map<agent_key,message>`；hook 回傳 `selectedAgent,setSelectedAgent,busyForSelectedAgent,anyReplyBusy`，`send(text,{agentKey}={})`。

- [ ] **1. 寫失敗測試。** Node `test('other agent running does not block selected agent')`；mention fixture 覆蓋明確鍵、中文顯示名、底線、停用、重名、email、member token、code／quote、兩 agent 歧義。`test('failed send preserves draft scope and attachments')` 測實際送出狀態 reducer。

  ```js
  test('other agent running does not block selected agent', () => {
    const busy = openReplies([{id: 1, role: 'assistant', agent_key: 'doc_writer', status: 'running'}]);
    assert.equal(busy.has('doc_writer'), true);
    assert.equal(busy.has('sheet_ops'), false);
  });
  ```
- [ ] **2. 跑 red。** `node --test ui/tests/agents.test.mjs`；應因待新增純函式／語意失敗。
- [ ] **3. 實作。** 下拉與 @ autocomplete 共用 roster；訊息包括執行當時名稱／模型，profile 後來改名不回寫歷史。Composer busy 只管選定角色，conversation 控制用 anyReplyBusy。管理設定提供 prompt、具體工具清單、provider reference 及啟用開關，錯誤原位保留；非 admin 不顯示可修改 controls。
- [ ] **4. 跑 green／操作。** Node tests、`npm run build --prefix ui`；以 fixture worker 操作兩角色並行、中文 IME Enter 不誤送、切角色不丟草稿／範圍、失敗不清附件、停用後不能送出。1280×720 選單不遮住輸入與送出；記錄截圖。
- [ ] **5. 提交與 A 驗收。** 建議 `feat: add agent selection and profile settings`。全套後端／前端回歸成功且角色端到端走通，才標 M8-A 工程交付。

## 5. M8-B：編排核心與執行接合

### Task B1：資料模型、scope／snapshot 與 DAG

**Files:** Create `db/159_agent_orchestration.sql`, `project_assistant/orchestration_store.py`, `project_assistant/orchestrator.py`, `tests/test_orchestrator.py`. Modify `project_docs/repository.py`（SCHEMA_FILES）, `project_assistant/request_scope.py`, `project_assistant/tools.py`, `scripts/verify_wheel.py`.

**Interfaces:** `create_run(conn,me,slug,objective,*,client_request_id,limits=None,conversation_id=None,deadline_at=None)->dict`; `create_task(conn,me,slug,run_id,*,objective,agent_key=None,label_selector=None,scope=None,target=None,depends_on=(),strategy='single',write_mode='proposal',parent_dispatch_id=None)->dict`；`ready_tasks(conn,slug,run_id)->list[dict]`。`ToolContext` 新增 optional `agent_key,dispatch_id,admission_no,lease_token,scope,write_mode`（舊 caller 相容，dispatch context 只由 runtime 填）。

- [ ] **1. 寫失敗測試。** `test_same_request_id_creates_one_run`、`test_dependency_must_be_same_run_and_acyclic`、`test_child_scope_cannot_expand`、`test_snapshot_is_stable_after_tab_edit`、`test_analysis_only_cannot_propose`。新增/舊 schema 重跑兩次、刪除測試專案都驗證 FK 正確。
- [ ] **2. 跑 red。** `python -m unittest discover -s tests -p test_orchestrator.py -v`。
- [ ] **3. 實作。** 依 §3 建表及狀態約束；保留原五元組，不另加事件總線。scope 嚴格驗證原值／固定欄位 id，doc scope 覆蓋 annotation actions；target 與 input snapshot 同交易取得。200 上限計算持久 task，fanout slot 另限制 200、race 3，不准繞過上限產生無限 dispatch。
- [ ] **4. 跑 green。** 斷言 201st task 拒絕、200 accepted；跨專案／自依賴／cycle 不留下半成品；model 傳 actor/chain 被拒。test DB cleanup 更新為按 FK 順序清理，禁止以關閉 constraint 解決。
- [ ] **5. 提交 slice。** 建議 `feat: persist orchestration runs tasks and snapshots`。

### Task B2：Admission、租約、容量與恢復

**Files:** Modify `project_assistant/orchestrator.py`, `project_assistant/orchestration_store.py`, `project_assistant/limbs.py`, `tests/test_orchestrator.py`. Create `tests/test_orchestration_concurrency.py`.

**Interfaces:** `spawn_dispatch(conn,slug,task_id,*,agent_key,slot_key,caller_dispatch_id=None,requested_deadline=None)->dict`; `claim_dispatch(conn,worker_id,supported_agent_keys,*,allowed_projects,lease_seconds=120)->dict|None`; `renew_dispatch(conn,identity,handle,lease_token)->dict`; `complete_dispatch(conn,identity,handle,lease_token,*,outcome,output,proposal_ids)->dict`; `cancel_dispatch(conn,me,slug,handle,reason)->dict`; `sweep(conn)->int`。caller chain 從 DB 建構，沒有模型傳 chain 參數。

- [ ] **1. 寫失敗測試。** `test_stale_completion_after_retry`：取 attempt1→取消→重試 attempt2→回傳 attempt1，回 `STALE_DISPATCH`，attempt2、proposal、asset count 都不變。`test_claim_capacity_across_two_connections`：profile=2、run=6 不超額；`test_worker_done_is_written_once` 同 output 重播無第二事件，不同 output 回 409。
- [ ] **2. 跑 red。** `python -m unittest discover -s tests -p 'test_orchestrat*.py' -v`（同一 process 序列執行）。
- [ ] **3. 實作。** claim 使用 `FOR UPDATE SKIP LOCKED`，容量以 profile／run 鎖與 DB count 計算，不能只靠 Python pool。lease 完整核對 project、task、dispatch、admission、worker、token、expiry、superseded；progress／媒體／提案寫入同樣檢查。過期重派新 dispatch；retry budget 用 task slot 記錄，不重設。深度預設 1、循環、deadline clamp 皆在控制面。
- [ ] **4. 跑 green。** `test_parent_cancel_stops_descendants`、`test_crash_after_commit_before_reply_is_idempotent`、`test_expired_lease_requeues_with_new_admission`、`test_second_failure_is_terminal`、`test_child_deadline_cannot_exceed_parent` 及 worker 無 spawn 權限測試通過；終結消息不因 finally＋sweeper 重複。
- [ ] **5. 提交 slice。** 建議 `feat: enforce orchestration admission and lease fencing`。

### Task B3：共用 runtime、六工具、問題 Gate 與背景回覆

**Files:** Modify `project_assistant/worker.py`, `project_assistant/agent_runtime.py`, `project_assistant/tools.py`, `project_assistant/tool_specs.py`, `project_assistant/tool_host.py`, `project_assistant/orchestrator.py`, `project_assistant/orchestration_store.py`, `project_assistant/store.py`. Create `tests/test_delegation_tools.py`, `tests/test_orchestration_worker.py`.

**Interfaces:** 六工具參數沿用規格 §3.3（`scope.tab_key` 僅在外層正規化為 `target_tab`）；內部 `open_gate(conn,ctx,*,question,options,blocking_task_ids=())->dict`；`resolve_gate(conn,me,slug,gate_id,*,resolution,client_request_id)->dict`；`execute_dispatch(connection_factory,claim,settings,worker_id)->str`；`finish_run_notice(conn,run_id)->int|None`。

- [ ] **1. 寫失敗測試。** `test_tool_spawn_survives_connection_close`；`test_gate_resume_uses_new_admission`；`test_wait_with_full_pool_returns_handle`；`test_coordinator_receives_one_summary_in_original_conversation`。主控建立兩獨立子任務與一 join，只有子任務完成／已接受才解鎖 join。
- [ ] **2. 跑 red。** `python -m unittest discover -s tests -p test_delegation_tools.py -v` 與 `python -m unittest discover -s tests -p test_orchestration_worker.py -v`。
- [ ] **3. 實作。** 明確列出 mutating tools，先提交再 bounded wait。A 的種子只含當時已實作的工具；B 首次啟用時，僅對 allowed_tools 仍等於 A 原始種子的內建角色補入委派／提問權限，自訂過的 profile 保留原清單並在管理 UI 提示可選新工具。測試 `test_upgrade_preserves_custom_tool_policy`。worker 輪詢 chat 與 dispatch 輪流取件，共用同一 concurrency budget；排隊公平，不讓長隊餓死另一類。runtime 注入固定 profile／snapshot／scope；finally 記成功／失敗／提問收據，程序被殺由 sweeper 接手。只消費有權限的 run messages；ack 只作用於自身收件目標。
- [ ] **4. 跑 green。** 問題 1/6 個選項拒絕、2/5 個接受；同 gate 重播不續跑兩次；已取消 gate 不復活；annotation／dispatch output 中注入角色變更無效。`wait=true` 使用 mock clock 驗證至多 5 秒，等候期間沒有未提交 DB transaction。
- [ ] **5. 提交 slice。** 建議 `feat: execute delegated tasks and resumable decision gates`。此任務先提供受測工具／service，完整使用者路由在 B6 接入。

### Task B4：提案產出、核對與下游一致性

**Files:** Create `project_assistant/proposal_output.py`, `tests/test_orchestration_proposals.py`. Modify `project_assistant/flow_runner.py`（既有 `_snapshot/_result_target` 共用化）, `project_assistant/service.py`（`_own_pending/apply_proposal/dismiss_proposal`）, `project_assistant/tools.py`, `project_assistant/store.py`, `project_assistant/table_edits.py`, `project_assistant/proposal_review.py`, `project_assistant/orchestrator.py`.

**Interfaces:** `snapshot_target(conn,slug,target)->dict`; `prepare_output(target,snapshot,output)->tuple[dict,str]`（沿用現有 doc/table ops 及 CAS）；`on_proposal_decided(conn,proposal_id,applied)->None`；`attach_proposal(conn,ctx,proposal_id)->None`。所有關聯與寫入使用呼叫者交易，不自行 commit。

- [ ] **1. 寫失敗測試。** `test_apply_advances_task_in_same_transaction`；`test_dismiss_blocks_join`；`test_multi_proposal_requires_all_applied`；`test_orchestration_proposal_rejects_partial_groups`；`test_doc_output_uses_original_block_bases`；`test_canceled_dispatch_cannot_create_proposal_via_tool_host`。
- [ ] **2. 跑 red。** `python -m unittest discover -s tests -p test_orchestration_proposals.py -v`。
- [ ] **3. 實作。** 工具產出的所有 proposal 綁有效 dispatch，不信模型上報任意 proposal id；檢查 owner/project/scope。整合 `_own_pending` 依 §3 鎖序先鎖 run/task，再鎖 proposal/tab。apply、dismiss、失敗都同步通知兩引擎；source conflict 回 409 保留 pending，不能吞成 200 成功。
- [ ] **4. 跑 green。** 以失敗注入證明寫回後通知出錯時整筆 rollback；target lock／來源 fingerprint 改動不寫入；非 race 一般聊天局部核對仍成功；`test_request_review*.py`、`test_table_proposals.py`、`test_execution.py` 回歸通過。
- [ ] **5. 提交 slice。** 建議 `feat: advance orchestration only after proposal acceptance`。

### Task B5：Flow profile 節點、逐列任務與遠端手腳

**Files:** Modify `project_assistant/flow_runner.py`, `project_assistant/orchestrator.py`, `project_assistant/orchestration_store.py`, `project_assistant/limbs.py`, `project_assistant/limb_worker.py`, `project_docs/http.py`, `project_docs/media.py`, `ui/src/FlowPanels.jsx`, `ui/src/FlowSurface.jsx`, `ui/src/flowModel.js`, `examples/worker.example.json`, `docs/EXECUTION_API.md`, `docs/WORKERS.md`. Create `tests/test_orchestration_flow.py`, `tests/test_orchestration_limbs.py`.

**Interfaces:** `attach_flow_task(conn,flow_run,limb_task,node)->dict`（以 task.flow_task_id 唯一映射）；`finish_profile_task(conn,flow_task_id,dispatch_result)->None`；遠端新增 `POST /projects/api/limbs/orchestration/{claim,renew,complete,fail,upload-cell-asset}`，使用既有 limb Bearer 認證與 adapter input/output 結構，附 `{dispatch_handle,task_id,lease_token}`。

- [ ] **1. 寫失敗測試。** `test_profile_node_claimed_once`、`test_profile_node_preserves_single_step_source_check`、`test_fanout_selected_rows_only`、`test_limb_late_upload_does_not_create_asset`、`test_old_limb_worker_protocol_unchanged`。兩列修改審核後 join 執行一次；部分通過不得提早 join。
- [ ] **2. 跑 red。** `python -m unittest discover -s tests -p test_orchestration_flow.py -v` 與 `python -m unittest discover -s tests -p test_orchestration_limbs.py -v`。
- [ ] **3. 實作 Flow 轉接。** node 增 optional agent_key；與明確 limb_id 同時填入時拒絕歧義，角色能力須符合節點；新 profile 節點拒絕 direct，舊非 profile 節點行為不改。Flow 繼續產生原 limb_task、管理 DAG；有 agent_key 的 task 僅由編排橋接建立 dispatch，legacy claim 排除此類節點。編排不再複製另一份 Flow DAG。回報映射回同一 flow task，既有 proposal hook 推進 Flow；取消／重試雙向同步。`trigger_flow_run` 經既有 preflight/start；新增明確 `execution_mode`，single_step 使用 `node_id`，不得把 start_node_id 當單步。若目前固定 scope 無法容納 flow 的寫入範圍，或含未被這次使用者確認的 direct 節點，先建立 scope/approval gate，核准後以已固定的 definition_revision 啟動，未核准不排工。
- [ ] **4. 實作 remote 入口。** 新 worker 設定 `orchestration_enabled` 明示加入新隊列；輪替 polling，既有 claim 路徑保持相容。Remote dispatch 直接在 orchestration 表，不製造假的 Flow。重用 adapter 執行、認證及 lease helper；上傳先驗 admission，再存 asset、產候選，絕不直接寫格。失去 lease 停止輪詢／本地子程序；外部已發工作取消限制如實回報。
- [ ] **5. 跑 green。** 新測試、`test_flow_scopes.py`、`test_flow_single_step.py`、`test_limb_worker.py` 及 `node --test ui/tests/flow.test.mjs`；flowModel serialize/deserialize 保留 agent_key。控制面中斷重啟後同 flow_task_id 不重複建立 dispatch 槽。
- [ ] **6. 提交 slice。** 建議 `feat: connect agent dispatches to flows and remote limbs`。

### Task B6：HTTP 權限、看板查詢與端到端 API

**Files:** Create `project_assistant/orchestration_service.py`, `tests/test_orchestration_http.py`. Modify `project_docs/http.py`, `project_assistant/service.py`, `project_assistant/orchestration_store.py`, `docs/EXECUTION_API.md`.

**Interfaces:** `board(conn,me,slug,*,cursor=None,limit=50,counts_only=False)->tuple[int,dict]`；`run_detail(conn,me,slug,run_id,*,cursor=None)->tuple[int,dict]`；其餘 create/cancel/retry/resolve service 依 §3.4 接受 body，回 `(status,payload)`。assistant state 增 `agents,active_runs,open_gates`，沿用原欄位。

- [ ] **1. 寫失敗 HTTP 測試。** `test_routes_accept_underscore_agent_key`；`test_other_owner_cannot_read_private_run`；`test_wrong_project_dispatch_is_not_found`；`test_viewer_cannot_resolve_gate`；`test_board_deduplicates_gate_and_proposal`；`test_post_replay_is_idempotent`。
- [ ] **2. 跑 red。** `python -m unittest discover -s tests -p test_orchestration_http.py -v`。
- [ ] **3. 接路由與查詢。** 所有 writes 登錄現有 `WRITES`、CSRF／Origin 檢查；遠端 endpoints 走 limb 認證而非瀏覽器 owner。board 組合既有 owner pending proposals、可見 Flow 與新 run，穩定 id 去重；只讀 projection，不另建快取庫。body 嚴格檢查非 dict、bool 當整數、無效 UUID、NaN、超長字串與 foreign id；請求 objective 1～4000 字，output 沿用 2 MiB 上限。
- [ ] **4. 跑 green。** 完成 creator 建 run→claim→提問→回答→提案→接受→join→完成的 HTTP fixture；member／viewer／admin／其他 owner 權限矩陣與 expired token 負例。counts 全量、分頁不漏不重；序列化 payload 不包含 secret、lease hash、他人訊息。
- [ ] **5. 提交與 B 驗收。** 建議 `feat: expose orchestration controls and board API`。M8-B 全部測試與真實 DB 交易驗證通過後才進 C。

## 6. M8-C：候選選用與集中操作

### Task C1：競速原子選用

**Files:** Create `db/160_agent_races.sql`, `tests/test_orchestration_races.py`. Modify `project_docs/repository.py`（SCHEMA_FILES）, `project_assistant/orchestrator.py`, `project_assistant/orchestration_store.py`, `project_assistant/service.py`, `project_assistant/tools.py`, `scripts/verify_wheel.py`.

**Interfaces:** `start_race(conn,me,slug,task_id,agent_keys)->list[dict]`；`select_race_winner(conn,me,slug,gate_id,proposal_id,*,client_request_id)->dict`。160 新增 winner FK／同 task 歸屬約束及每有效 race dispatch 至多一張 pending candidate 的限制。

- [ ] **1. 寫失敗測試。** `test_two_active_race_admissions_are_both_valid`；`test_retry_only_supersedes_same_agent_slot`；`test_concurrent_winners_apply_once`；`test_regular_apply_cannot_bypass_race_selection`；`test_changed_snapshot_rolls_back_winner_and_loser_dismissals`。
- [ ] **2. 跑 red。** `python -m unittest discover -s tests -p test_orchestration_races.py -v`。
- [ ] **3. 實作。** 只接受 2～3 個不同、enabled、可產生該 target 提案的 agent；不接受 observer／analysis-only。所有槽用同 snapshot。每候選只有一張整組提案，第二張被工具邊界拒絕；多次草稿不能默默成多張候選。至少一張候選就能核對，UI 顯示其餘仍執行；一位失敗可選其他候選；全失敗時 task failed。
- [ ] **4. 完成原子交易。** 鎖 gate/task/有效 dispatch/proposals/target，經既有寫回與 CAS 套用勝出者，記 winning_dispatch_id，作廢落選 proposal、取消未完成 dispatch、關 gate 並推進下游；任一寫回失敗全部 rollback。所有舊 apply/dismiss 入口統一導向 race 規則，不能選落選版本或繞過 winner。重複同選用回原結果，選不同版本回 409。
- [ ] **5. 跑 green／提交。** 新 race 測試及 B4 回歸通過，確認遲到輸出／上傳不復活落選者。建議 `feat: atomically select and apply racing proposals`。

### Task C2：看板、並排比對與畫布交辦

**Files:** Create `ui/src/assistant/AgentBoard.jsx`, `ui/src/assistant/ProposalRaceView.jsx`, `ui/src/assistant/orchestrationModel.js`, `ui/tests/orchestration.test.mjs`. Modify `ui/src/assistant/AssistantViews.jsx`, `ui/src/assistant/useAssistant.js`, `ui/src/assistant/TableProposalReview.jsx`, `ui/src/assistant/assistant.css`, `ui/src/assistant/review.css`, `ui/src/App.jsx`, `ui/src/SheetWorkspace.jsx`, `ui/src/DocSurface.jsx`, `ui/src/Annotations.jsx`, `ui/src/Talk.jsx`, `ui/src/mentions.js`.

**Interfaces:** `AgentBoard({board,onResolve,onCancel,onRetry,onOpenTarget})`；`ProposalRaceView({gate,candidates,onSelect,onClose})`；`onAskAgent(text,scope,{agentKey,strategy,raceAgents}={})` 保持原兩參數呼叫相容；`onOpenTarget({tab_key,row_id?,block_id?})`。`groupBoardItems(items)`、`raceSelectionPayload(gate,proposalId,requestId)`、`reconcileBoard(previous,next)` 都由實際元件使用。

- [ ] **1. 寫失敗 Node 測試。** `test('deduplicate gate and proposal')`、`test('poll retains selected candidate and draft answer')`、`test('race payload uses proposal id, not visible index')`、`test('selected hidden rows retain stable scope')`、`test('late response from previous project is ignored')`。

  ```js
  test('race payload uses proposal id, not visible index', () => {
    assert.deepEqual(raceSelectionPayload({id: 'gate-1'}, 402, 'choose-1'),
                     {client_request_id: 'choose-1', resolution: {proposal_id: 402}});
  });
  ```
- [ ] **2. 跑 red。** `node --test ui/tests/orchestration.test.mjs`。
- [ ] **3. 實作看板。** 預設只留待你裁決／執行中計數；點開才展開四分組。窄 sidebar 垂直分組，競速使用寬版 Dialog，不強塞四欄。Working 顯示工具摘要／取消；Done 包含失敗／取消與重試、來源定位；Idle 區分可用、忙碌與離線，不能把已註冊等同在線。沿用 1 秒活動／30 秒閒置 polling，避免重疊；關閉面板仍以輕量 counts 更新。
- [ ] **4. 實作交辦與比對。** 表格勾選後選代理／2～3 位競速，確認 objective 與固定列欄再送出，單列同路徑。段落標註新增「交給代理」：帶 doc scope 與明示 agent token；人類 `@{uuid}` 不變。若留言直接點名代理，只有使用者實際按送出時建立一次帶 source comment id 的需求，不在載入／編輯／背景掃描時自動派發。race 使用既有 before/after review 呈現，選用錯誤保留候選與上下文。
- [ ] **5. 跑 green／瀏覽器走查。** Node、build 成功；1280×720 操作 2 代理→待核對→並排→選勝者→跳回原列，確認落選已略過。鍵盤可開關 Dialog／選候選，焦點返回觸發處；輪詢不重設選取；正在審核時不自動滾走。純函式測試不充當實際 React 互動驗證。
- [ ] **6. 提交與 C 驗收。** 建議 `feat: add agent board and proposal race review`；補可重現 fixture 操作步驟與截圖。

## 7. E1：整體驗證與接手證據

**Files:** Create `docs/AGENT_ORCHESTRATION_ACCEPTANCE.md`; modify `docs/AGENT_ORCHESTRATION_SPEC.md`, `docs/ARCHITECTURE_AND_HANDOFF.md`, `docs/EXECUTION_API.md`, `docs/WORKERS.md`, `README.md`, `scripts/verify_wheel.py`（僅如前任務尚未覆蓋）與 `AGENTS.md` 最新交付摘要。

- [ ] **1. 開工基線。** 保存 `git status --short`／HEAD、runtime 版本、實際測試 DB 位置；確認 DB 為可清理的專用測試庫後才執行。不可直接沿用文件裡 55433，該 DB 可能還承載展示內容。先跑現有 suite，記錄 pass/fail/skip，不將舊數字複製成此次結果。
- [ ] **2. 三條工作路徑。** 辦公：固定兩列→sheet_ops→QA→核對→週報匯總；美術：固定素材列→遠端 fixture 產資產→候選核對→只寫回選用結果；自由工作流：profile 節點→問題 Gate→兩分支→接受→join。全程使用合成專案，不修改使用者工作資料。
- [ ] **3. 故障恢復。** 在 claim 後、proposal 建立後、completion commit 後但 HTTP response 前各中斷一次；重啟後驗證不重複寫回／計數，舊 admission 無效，沒有永遠卡住的 working 狀態。取消後再重試也跑同一套。
- [ ] **4. 跑完整工程 gate。** 在已配置的隔離測試 DB 上依序執行：

```powershell
python -m unittest discover -s tests -q
npm test --prefix ui
npm run build --prefix ui
python -m build
$m8Wheel = Get-ChildItem -LiteralPath 'dist' -Filter 'openbench-*.whl' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
python scripts/verify_wheel.py $m8Wheel.FullName
git diff --check
```

  期待：測試零失敗，必需 DB tests 零 skip；build 退出 0；wheel 包含 158～160 SQL、四份新 prompt、新 runtime 模組與當次 JS/CSS。新增乾淨環境「離開 checkout」載入 schema／prompt 的檢查；不要只驗原始碼目錄可執行。FFmpeg 或容器不可用須明列未驗證範圍。

- [ ] **5. UI 證據。** 1280×720 及能實際確認的 125% 縮放各走查：選角、固定範圍、Gate、race、取消、返回焦點。記錄前後資料、run/task/dispatch/proposal id、截圖、失敗修正；真實 IME 未測就寫未測。外部付費模型品質／實際 ACP／Docker／遠端 CI／使用者長期試用各自標示，不由 mock 替代。
- [ ] **6. 最終審查／交接。** 用固定完整 SHA 檢查權限、交易、scope、競速與 migration；更新規格裁定及新入口。開工前 checklist 與實際證據分開；只把已達標階段標完成。建議提交 `docs: record M8 verification and operating limits`；本計畫不自行授權 push、merge 或部署。

## 8. M8-D：ACP 選配，不阻塞核心交付

### Task D1：一個明確 adapter 的 ACP 契約與橋接

**Files:** Create `project_assistant/acp_bridge.py`, `tests/fixtures/mock_acp_agent.py`, `tests/test_acp_bridge.py`. Modify `project_assistant/limb_worker.py`, `project_assistant/tool_host.py`, `project_assistant/mcp_stdio.py`, `project_assistant/limbs.py`, `examples/worker.example.json`, `docs/WORKERS.md`；若新增 capability 需另建下一號 migration，不改既有已交付 constraint。

**Interfaces:** `run_acp(*,command:list[str],cwd:str,env:dict,prompt:str,tool_proxy,deadline_at,cancel_event)->dict`。command 只能來自部署設定，不接受 prompt／HTTP payload 變成 shell；返回沿用 runtime structured output。

- [ ] **1. 相容性確認。** 在此階段開始時核對實際可用 CLI／ACP adapter 的官方協定與版本，選一個完成真實 handshake；記錄支援的 protocol version、session、MCP 掛載方式與 cancellation。原規格列的 CLI 命令僅是示例，不預先宣稱都支援 ACP。未有可用 adapter 則 D 保持未交付，A～C 不回退。
- [ ] **2. 寫 red fixture。** Mock stdio 覆蓋 handshake、分片訊息、亂序 response id、通知、未知 method、EOF、無效 JSON、timeout、工具拒絕、lease 遺失；測試綁定前一步確認的協定資料，不只測自訂 echo 協定。
- [ ] **3. 跑 red。** `python -m unittest discover -s tests -p test_acp_bridge.py -v`。
- [ ] **4. 實作最小橋接。** 子程序 argv／`shell=False`，乾淨 cwd，環境變數白名單。CLI 不拿 Head Bearer／DB／其他 provider keys；MCP 代理在 parent 保留 lease credentials，只向 child 暴露本次 session 的受控能力。保留 Windows 必需的系統環境但不繼承整份 environ；取消／逾時終止整個子程序樹且 worker_done 一次。
- [ ] **5. 跑 green／交付。** fixture 通過後對所選單一 adapter 做真實讀頁→提案→核對 smoke；產物標清工具版本、OS 與是否實際呼叫模型。建議 `feat: add optional ACP stdio limb adapter`。其他 CLI 未實測只列候選，不標支援。

## 9. 計畫自檢與開始位置

| 規格段落 | 對應任務 |
| --- | --- |
| §3.1 registry、角色、roster、獨立 prompt/model | A1、A2、A3 |
| §3.2 五元組、admission、chain、deadline、race | B1、B2、B3、B4、C1 |
| §3.3 六工具、強制 worker_done | B3、B5 |
| §3.4 對話／段落／表格／Flow 多入口 | A3、B5、C2 |
| §3.5 看板、Needs You、成果定位及設定 | A3、B6、C2 |
| §4 SQL／升級及 §5 API／模組 | A1、B1、B6、C1、E1 |
| §6 各階段驗收及選配 ACP | A3、B6、C2、E1、D1 |

自檢已對照規格與目前呼叫鏈，五項 Review Focus 均指定到測試任務。本文中的檔案／函式分為現有接點與計畫新增，不代表新增程式已存在。開工順序是 **E1.1 基線 → A1**；完成 A 的角色對話閉環後，再進入 B 的持久化編排。

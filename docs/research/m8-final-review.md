# M8 本機最終審查與裁定

## 權限與範圍

- 目標：完成使用者核准計畫的 A～D（含 ACP）與 E1 本機證據；不宣稱日常使用驗收。
- IN SCOPE：本分支相對起點的全部變更、直接 caller/consumer、權限與資料損壞、交易／租約／scope／race、schema 升級、前端交辦核對與 ACP／封裝。
- FOLLOW-UP：不影響此交付的既有鄰接問題、推測性重構、其他 ACP CLI、外部付費模型品質、真 IME／125% 與未執行部署環境。
- 外部操作：沒有 issue/comment/push/PR/merge/deploy 授權，本次只本地 commits；不得另建協調服務或新遠端。
- 主控為唯一寫入者；final reviewer 唯讀，不修改 repo/index/HEAD、不派生代理。審查後主控以測試重現及單次修正回應。
- 工具／lane：主控在 C:/ai_project/OpenBench 與 .superpowers/m8-venv；verifier 只讀此 checkout；新增針對性實驗限既有 .superpowers/sdd/2026-10-18-agent-orchestration，不建其他 worktree，不重跑已有完整 gate 或與主控共享 DB 的測試。
- stop：完整範圍一次審查、重要問題單次 TDD 修正與回歸後交付。沒有提交到遠端，CI 為未執行，不能冒充綠燈。

## Gate 收據

基準：72670290a9c60737478f2becc89c77110948a031。程式已凍結，提交 SHA 由下方審查 handoff 記錄。

- RAN：Python3.12.14／PG16，專用127.0.0.1:55583/openbench_m8_test，unittest227/227（0 fail/skip），184.253s。
- RAN：Node75/75、Vite300 modules build；後續 Python-only fix 未改 UI，重用相同 JS/CSS blob。
- RAN：python -m build、verify_wheel；新 venv 安裝11 packages；checkout 外 SQL10/prompts7/ACP import/真 MCP list+call。
- RAN：官方 ACP2.2.2 真 handshake、MCP read→proposal→UI accept；模型為本機合成 Responses SSE。
- RAN：合成辦公、美術、Gate 雙分支三路徑；詳見 acceptance 及 JSON 收據。
- READ：舊 A/B/C 階段證據與本分支 commits；不把舊116/63當成本輪結果。
- 未執行：遠端 CI、Docker、外部付費模型、真 IME／125%、使用者長期協作。沒有消除或掩蓋必需 DB skip。
- Cost：多次階段回歸與真實 fixture；精確 token／總 elapsed 未提供。診斷重跑原因及修正已記錄，無無理由全套重跑。

## 執行中裁定（依發生順序）

- Ruling: use the existing checkout on a feature branch rather than a new worktree — AGENTS requires development inside C:/ai_project/OpenBench and the plan/spec are untracked inputs here. Cost: no separate checkout isolation; no concurrent writers will be used.
- Ruling: adapt bash-only skill bookkeeping scripts to this durable ledger on Windows; preserve per-task briefs, red/green evidence and commits without requiring a shell/runtime installation. Cost: manual bookkeeping must remain current.
- Ruling: do not use the initial .superpowers/m8-pg directory, whose sandbox initdb never finished; initialized .superpowers/m8-pg-ready through approved process execution. Cost: one unused scratch directory, no user database touched.
- Ruling: serialize short orchestration control transactions per project with PostgreSQL advisory transaction lock before row locks — reduces the cancellation/lease/gate deadlock surface without serializing model execution. Cost: one metadata transaction at a time per project; measured throughput would justify finer locking later.
- Ruling: completion notices are deterministic runtime summaries, not an extra paid LLM turn — satisfies reliable one-summary delivery and avoids duplicate billing. Cost: summaries report task outcomes without editorial synthesis.
- Ruling: root chat decision gates resume with the original write_mode and scope rather than forcing analysis_only — otherwise a question would silently revoke an authorized edit. Cost: scope/lease checks must remain authoritative on resume.
- Ruling: put Flow bridging and remote queue envelopes in focused orchestration_flow.py / orchestration_limb.py and existing runtime_http.py instead of expanding the already large http.py/flow_runner.py further. Cost: two focused modules to navigate; one scheduler/one runtime remain authoritative.
- Ruling: preserve Flow's existing mandatory single-step definition_revision/source_revisions in new tests instead of weakening preflight. Cost: callers must send the reviewed version contract.
- Ruling: structured LLM output uses the same output authority as tools; custom remote LLM fixtures/profiles explicitly grant propose_table_edit for table writes. Media adapters keep their narrow artifact contract. Cost: existing custom remote LLM profiles without a write grant must be configured before canvas output.
- Ruling: validate winning dispatch belongs to the locked task transactionally, with a simple winner FK; avoids imposing a newer PostgreSQL floor for composite SET NULL syntax. Cost: all winner writes must stay behind select_race_winner.
- Ruling: human-comment routing is an atomic comment+chat enqueue, not a second queue; later complex work can delegate from that chat. Cost: a second same-persona comment while its chat is running returns 409 with draft retained.
- Ruling: new source_ref migration 161 is separate from delivered 160; generic profile safety prompt replaces legacy business prompt inheritance. Cost: custom business knowledge must be put explicitly in that profile knowledge_pack; legacy UI criteria file remains available.
- Ruling: ACP uses llm capability and acp_stdio runtime profile, avoiding unsupported legacy task capability/schema changes. Only one official adapter2.2.2 is verified; other CLIs not claimed. Cost: deployers install/pin adapter and supply its own explicit provider key; arbitrary executables are not OS sandboxed.
- Ruling: follow existing profile online preflight for both start paths, not generic same-capability remote presence. Cost: tests/deployments must report the actual builtin worker heartbeat; unrelated remote workers no longer mask an offline chosen profile.

## 唯讀審查

獨立 reviewer（gpt-6-astra）已完整唯讀審查 `231f45512d9b5d63d74c14a9ab9a50078beb4d23` 相對基準，未改 repo／DB，READ 完整 gate，RAN 記憶體探針。結論：7 項 Important，0 Critical／Minor；未接受此 SHA。主控依實際使用影響維持七項均須修正，進入一次 TDD 修正批次。

| ID | 問題 | 修正與驗證 |
| --- | --- | --- |
| R1 | 接受同任務 A 提案時，B 的已變更來源被重新計算 fingerprint 而放行 | 已修復：fanout 來源變更 RED→GREEN；另測跨頁 source_revision 不被放行。service 保存已鎖定的寫回前 tab/values，先驗證再 rebase。 |
| R2 | 單一停用 profile 的相依工作讓 schedule_ready 拋錯，阻擋其他工作領取 | 已修復：停用相依 profile RED→GREEN；per-task savepoint 回滾不完整派發，標失敗、更新 run 並繼續其他工作。 |
| R3 | 相依 race 未 ready 時沒有保存候選名單，永遠不派發 | 已修復：相依 race 候選名單 RED→GREEN；建立時即 start_race 註冊，pending 不派發，ready 後兩槽各派一次。 |
| R4 | 相依任務在上游之前固定 snapshot，後續仍讀舊資料 | 已修復：讀取已接受上游值 RED→GREEN；無關人工來源變更也 RED→GREEN 拒絕。pending 後代只承認已驗證的 ancestor write，ready 邊界再核對並固定。 |
| R5 | chat 轉問題 Gate 沒帶已完成工具 journal，續跑會重複建立子工作 | 已修復：chat→Gate→續跑重複 spawn RED→GREEN；讀私有 tool_journal，連同原回合 context 移交，公開 message projection 不擴權。 |
| R6 | 全部候選待審後 UI 沒有拒絕整批／取消入口 | 已修復：取消路由 Node RED→GREEN；實際 UI Escape 保留候選並還原焦點，明確取消後兩提案 dismissed，原格未改。 |
| R7 | PROJECT_ASSISTANT_ENGINE=codex 被新 runtime 錯送 Responses | 已修復：舊 codex 設定錯走 Responses RED→GREEN；provider_for 正規化為 codex_cli，無網路探針證明 CLI 被呼叫。 |

審查者未判為已通過的界線：Docker／遠端 CI／付費模型品質／真 IME／125%／日常協作仍未測；240 秒含核對期限是本計畫的明定限制；可信 ACP 執行檔並非 OS sandbox；生成 vendor bundle 以來源與 build／package 收據檢查，沒有另行 vendor audit。主控維持上述界線與限制，不冒充驗證成功。


## 修正批次的最終結果

七項 Important 均由主控在同一修正批次重現並修復；最終後端 **235/235**、0 fail/skip（153.662 秒），前端 **76/76**、Vite300 modules 與 wheel 通過。沒有第二次獨立審查；原審查拒絕231f455的紀錄保留，新版本以作者 TDD 與完整回歸證據回應，不能說成 reviewer 已批准新的 SHA。

UI 取消證據：[收據](m8-cancel-receipt.json)、[畫面](screenshots/m8-final-race-canceled.png)。關閉比較只返回看板，取消按鈕明確標示整批工作。

### 對 reviewer 未判定項目的裁定

- Final: Ruling: Docker／遠端 CI／付費模型品質／真 IME／125%／日常使用維持未驗證，沒有以 fixture 充當 — cost: 部署與真實使用驗收仍需在對應環境進行。
- Final: Ruling: 保留計畫明定的240秒含核對期限，API可明定更長deadline；未新增UI延長 — cost: 逾期需重新交辦，這是已明列的操作限制。
- Final: Ruling: ACP command仍是可信部署程式，工具與憑證隔離不等同OS sandbox — cost: 不可信程式需受限帳號／容器另行隔離。
- Final: Ruling: 生成vendor bundle依來源與build/package核對，不另作vendor內部稽核 — cost: 供應鏈與第三方庫風險未由本輪獨立排除。

Deferred minors: none（獨立審查沒有 Minor）。

最終 wheel SHA256：`25bc98869ea8a0c01d5f5ff47d4e33428a0397b5982852e2f347bdfce3161ead`。

修正程式 SHA：`eab82fc7e898a8a2b9b2fa86e8bbc49100c77c1a`。完整 gate 摘要與原輸出檔 hash 見 [m8-final-gates.txt](m8-final-gates.txt)。後續若只有交接文字或清理紀錄提交，程式／bundle 不變，不冒稱新一次獨立審查。

清理完成：本輪3038／3039／3040／3041臨時服務與55583專用測試庫已停止，驗收分頁關閉且viewport還原。僅移除已封存證據的本計畫scratch目錄（含本機fixture token設定）；保留程式分支、隔離runtime、測試庫資料及dist產物。使用者其他服務未停止。

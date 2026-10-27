# 資料修改與檔案交接實作紀錄

日期：2026-10-16。依據 `PRODUCT_UX_REPLAN.md` 的已授權實作。使用現有未提交工作區，不重設、提交或推送，不變更部署及外部模型設定。

## 已完成契約

| 範圍 | 行為與主要位置 |
| --- | --- |
| 原子儲存格修改 | `project_assistant/table_edits.py`、`project_docs/http.py`：每列傳 `cells`、`expected_cells` 與索引對應的 `column_ids`。核對目前可見文字／field 值後一次寫入；任一格衝突則全批拒絕。跨分頁版本可重套不相關的修改，不能覆蓋同格後續變更。 |
| 撤銷與重做 | 回傳 `cell_patches` 的 before／after；前端以反向操作使用相同 CAS 檢查。撤銷不把整張表還原成舊快照，也不移除其他人的修改。 |
| 穩定欄位身分 | `project_docs/doc_schema.py::column_ids` 以 table ID／欄索引提供可重現的舊資料 fallback，驗證存檔後保存在 attrs.column_ids。改名與移動保留 ID。 |
| 欄位設定 | `project_docs/table_schema.py`：新增、刪除、改名、調序、型態、自訂狀態選項；configure 合併改名／型態／選項為一次原子操作。操作要求版本與完整欄位 ID 序列。結構 restore 另有整張表的 expected_table 條件。 |
| 引用安全 | 會移動／刪除既有列欄的結構操作先檢查公式與流程定義／執行中的綁定，不能安全保留時拒絕，不默默改變引用位置。 |
| Field 寫入 | fill／status 的目前值納入 CAS 與型態檢查，寫入留下 activity 和版本。沒有把 placeholder 當成使用者已填的值。 |
| 代理範圍及局部接受 | `request_scope.py`、`proposal_review.py`、assistant service：明確空範圍拒絕；來源指紋在接受時再驗證。僅接受部分群組後，剩餘提案依本次已接受修改更新基準；原使用者訊息的範圍不變。review_version 防止重送群組索引接受下一筆。 |
| 單步流程寫回 | `table_edits.apply` 在同一交易按固定順序鎖定來源與目標分頁，確認 source_revisions 裡的參考分頁沒有變更或刪除後才寫入。提案自己的目標分頁不再整頁比對版本（SPEC_20 R17）：只比對要寫的格與所在列，其他列或同列其他格的修改會自動對齊；目標格被改過或目標列被刪，提案失敗並寫出是哪一格。流程 runner 與單步執行實作由流程代理負責。 |
| 來源與輸出方式 | 安全的 source_meta 提供交接能力資訊，不回傳原檔 blob／baseline。下載原檔、原檔 Patch、另存新工作簿分開；XLSX 結構修改先要求明確選擇 new_workbook，不延後到交付才第一次報錯。 |

## 匯入及重新匯入

`POST /projects/api/{slug}/tabs/import-preview` 接收原始檔案與 `X-File-Name`。可帶 `tab_key`、`base_revision`、`header_row`、`worksheet`、`delivery_mode`。

- worksheets.rows 永遠是來源前 20 列，因此選表頭時來源列號不會漂移。XLSX 選定工作表使用指定表頭，其他工作表目前使用第一列。
- 既有分頁的 replacement 以目前 field 值具現化後比較，提供新增／移除／修改／未變數量、最多 50 項 before／after、總差異數與截斷標示、列身分歧義警告及目前版本。
- 更新既有分頁必須送出 `confirm_replace=true`，並在鎖定分頁後再驗版本及他人的編輯鎖。這是明示的整檔取代，不是自動三方合併。
- 列身分只由唯一完整列內容或唯一非空首欄辨識沿用，表頭與資料列分開匹配。絕不以位置為資料列對位。重複列名且內容也改變時使用新 ID，原留言保留為未附著；可唯一辨識的重排保留列 ID。
- 取代造成既有公式／流程引用不安全時，寫入前拒絕並提示先解除引用或匯入新分頁。
- XLSX 的選定表頭及資料起始列保存在來源座標映射中，原檔 Patch 寫到正確位置；來源 blob 保留供原檔下載。

前後端只讀覆核確認 ImportPreview／importModel 的 query、replacement response、固定 target revision 及確認旗標一致。切換表頭／工作表／交付方式會使既有確認失效；重新讀取完成前不能提交舊差異。已修正重點選同一表頭會永久載入，以及確認前等待 flush 期間仍可變更選項的問題。

## 驗證

最終串行後端驗證由整合代理執行：**116 tests，34.422 秒，OK**。本資料代理前一輪完整驗證為 115 tests，31.707 秒，OK；其後流程代理增加來源標籤快照測試，整合代理再跑上述最終套件。測試期間曾因兩個套件並行執行 schema／teardown 造成 DDL deadlock，停止重疊後串行全部通過；未將 deadlock 算成行為測試通過。

```powershell
$env:PYTHONPATH='C:/ai_project/openbench/.openbench_runtime/packaging-venv/Lib/site-packages'
$env:OPENBENCH_TEST_DB_URI='postgresql://postgres@127.0.0.1:55433/postgres'
& 'C:/Users/ART-Kai.Chen/AppData/Local/Programs/Python/Python312/python.exe' -m unittest discover -s tests -q
```

涵蓋的回歸包括隱藏列不受貼上影響、混合文字／field 衝突的全批拒絕、反向操作保留他人修改、欄位身分與引用阻擋、XLSX 非第一列表頭及新工作簿交付、原檔 bytes 保留、局部接受與重送保護、持久化範圍、重複／重排列身分及舊留言未附著。

新增 source_context 的只讀覆核：來源由領取時已 sanitize 的輸入取得，僅保留匹配來源列前兩格及 tab／table／row ID、名稱與版本；沒有暴露 target_snapshot／lease_hash。Worker 仍受 allowed_projects 限制，發起人必須保持有效可寫成員。現有產品權限模型是有效成員可讀專案分頁，沒有新增跨專案讀取路徑。

## 合成操作資料

`scripts/seed_media_ux_fixture.py` 只建立 `ux-usability-1016/media-review-60`「素材審核60筆」。已存在即保留，交易內建立，不做 schema DDL。包含 60 列、8 空圖、橫／直／方形本機 QA PNG、12 筆長文、15 個本機靜音 WAV 附件及三種狀態。第一列 `b_qa_media_001` 有藍色 V1 → 橘色 V2 圖片版本與標示為合成資料的留言。所有圖片在記憶體中產生，不使用使用者圖片、不連外、不呼叫模型。操作走查及其後狀態／留言由整合代理記錄。

## 明確界線

- 採資料表模型和保守 Office Patch；不宣稱完整 Excel 工作簿引擎、公式引用自動改寫、任意選區或無表頭匯入。
- 欄位／列依賴檢查刻意保守。遇到公式時可能拒絕實際上可以人工處理的結構變更；不嘗試猜測並重寫引用。
- 儲存格的撤銷／重做已串接。前端結構操作目前清除儲存格撤銷堆疊，使用版本紀錄；不宣稱所有結構操作具有相同快捷撤銷。
- 重新匯入只有明確整檔取代與身分保護，未實作完整三方合併。
- 測試及合成走查不替代長期多人使用、真實中文輸入法、外部付費 provider、容器部署或大型工作簿相容性驗收。

# Sheet Views Implementation Plan

> **已暫停，非目前施工順序。** 使用者要求先多代理研究與整合可用性規劃；依 [d-001](../../research/2026-10-16-research-brief.md) 執行。三視圖已開始的程式只保留為未驗收草稿，不算 U1 完成。最終優先序由研究整合文件重新決定。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 本輪依使用者授權在既有 checkout 逐項實作，不啟動子代理、不提交原有混合變更。

**Goal:** 同一張表可切換表格、圖庫與看板，保留搜尋、選列、詳情與版本寫回。

**Architecture:** `tablesOf` 仍是資料來源；新增純函式產生卡片／分組與瀏覽器偏好，獨立 React 元件呈現卡片，`SheetSurface` 負責共用狀態與現有寫入 API。U2～U4 的相依與驗收列在 Spec，本計畫只交付 U1。

**Tech Stack:** React 19.2.0、Node 原生 test runner、既有 Vite、Python HTTP／PostgreSQL。

**Spec:** [通用工作台下一階段設計](../specs/2026-10-16-general-workbench.md)

## Global Constraints

- 開發限 C:\ai_project\openbench，不讀取原生產環境或公司私有資料。
- 文件／表格／工作流為通用能力，領域範本不新增專用主流程。
- 影片僅作附件與下載，不顯示播放器。
- 視圖切換不複製資料、不新增分頁、不改工作流、不呼叫模型。
- 沿用 React 19.2.0、現有 API、角色檢查、列鎖與版本紀錄；新增依賴先核對套件授權與穩定發布版本。
- 克隆參考庫只作查閱，排除在 Git、Docker 與 Python 封裝；不可直接執行參考庫腳本。
- 所有新增能力分開標示規劃、實作及驗收狀態，不把 mock 模型結果當作真實供應商驗收。

## 檔案分工

| 檔案 | 責任 |
| --- | --- |
| 新增 `ui/src/sheetViews.js` | 圖片／狀態欄發現、卡片與分組、偏好還原、單列狀態更新 payload |
| 新增 `ui/src/SheetCards.jsx` | 共用卡片、圖庫與看板，透過 callback 呼叫詳情／預覽／狀態變更 |
| 修改 `ui/src/SheetSurface.jsx` | 視圖工具列與偏好、共用篩選／選列、既有 API 寫回與重新讀取 |
| 修改 `ui/src/styles.css` | 卡片、看板、空狀態、焦點與窄視窗排版 |
| 新增 `ui/tests/sheetViews.test.mjs` | 視圖資料一致性、空／未知狀態、不變性、過期設定與精確更新範圍 |
| 修改 `docs/WORKSPACE_UX.md` | 實際驗收結果與界線 |

## Task 1：共用視圖模型與寫入範圍

**Consumes:** `tablesOf(doc, values)` 所產生的 parsed、visibleRows 原始 row 物件。

**Produces:** `sheetViewModel(parsed, visibleRows, preferences)` → `{statusColumns, coverColumns, groupColumn, coverColumn, cards, groups}`；card 為 `{row, index, title, cover, summary}`，groups 為 `{value, label, cards}`。`restoreViewPreferences(raw, parsed)` 正規化瀏覽器資料；`statusMovePayload(parsed, rowId, column, value)` 只產生一格的 table-edit payload。

- [ ] 新增測試：篩選只剩第三列時更新仍使用第三列 row ID；未知狀態與空值分組均保留；公式不依卡片順序重算；不存在的 row／非狀態欄拒絕。

```js
const change = statusMovePayload(parsed, 'r3', 2, '已完成');
assert.deepEqual(change, {table_id: 't1', row_edits: [
  {row_id: 'r3', cells: {'2': '已完成'}}
], new_rows: []});
assert.deepEqual(sheetViewModel(parsed, [parsed.rows[2]], {}).cards.map(c => c.index), [2]);
```

- [ ] 執行 `node --test ui/tests/sheetViews.test.mjs`，先確認缺少新模型而失敗。
- [ ] 實作欄位發現與 group Map；明確使用原始 rows 的索引，保留未知／空狀態，不修改輸入。

```js
const indexById = new Map(parsed.rows.map((row, index) => [row.rid, index]));
const index = indexById.get(row.rid);
const title = String(row.cells[0]?.value || `第 ${index + 1} 列`);
```

- [ ] 補上損壞 JSON、欄位名稱／型態變更後偏好失效、沒有圖片、沒有狀態欄測試，執行同一測試檔通過。

## Task 2：三視圖與共用互動

**Consumes:** Task 1 的模型及 payload；現有 `MediaCell`、`setRowOpen`、`setSelected`、`api.post`。

**Produces:** `SheetCards({model, mode, selected, onSelect, onOpen, onPreview, onStatus, writable, busy, parsed})`。封面與分組選單位於 SheetSurface；狀態變更只呼叫既有 table-edit，再重新讀取資料。

- [ ] 新增模式、封面及分組設定。偏好 key 包含 slug、tab.key、tableId；localStorage 讀寫 catch，不含表格內容。
- [ ] 卡片以 row.rid 作 React key，按鈕和 checkbox 皆有可讀名稱；狀態選單讀取當前欄值，空值不自動填入預設。封面沿用 MediaCell，無圖顯示文字摘要。
- [ ] 使用狀態變更的精確 payload；不可用可見序號直接寫回。

```js
await api.post(`/projects/api/${slug}/tabs/${tab.key}/table-edit`, {
  ...statusMovePayload(parsed, rowId, column, value), base_revision: tab.revision,
});
await onReloadTab();
```

- [ ] 當 busy 或唯讀停用變更；失敗交給 onError，資料不預先搬動；看板無狀態欄引導欄位設定。
- [ ] 增加響應式 CSS，圖庫卡片自動換列、看板橫向捲動；焦點可見，圖片 contain，文字不覆蓋操作。
- [ ] 執行 `npm test --prefix ui` 與 `npm run build --prefix ui`，確認既有鍵盤／貼上／媒體測試通過。

## Task 3：瀏覽器驗收與文件

**Consumes:** 建置後 3022 驗收服務、`workspace-basics` 通用示範及 `roadmap-acceptance` 圖片／狀態示範。

**Produces:** WORKSPACE_UX 中的實際結果；Roadmap 的 U1 狀態及其支持界線。

- [ ] 三視圖切換並重載，搜尋及選列保留；模式偏好依表隔離；比較畫面列數與 API 原始列數。
- [ ] 圖庫點圖預覽／列詳情；看板改一列狀態後切回表格及重新載入，檢查只改目標欄、版本可查。
- [ ] 搜尋只顯示非第一列後更改狀態，證明不會寫錯第一列。驗證無圖片、無狀態、無結果、空狀態、唯讀、失敗回應的 UI；DOM 沒有 video 元素。
- [ ] 檢查 `git diff --check`、七個參考庫 HEAD／乾淨狀態及排除規則。記錄本輪未跑付費模型、未完成 U2～U4；保留既有未提交工作。

## 自我審查

Spec U1 的七項契約分別由 Task 1（資料／欄位／偏好）、Task 2（互動／寫回／權限）、Task 3（實際體驗）覆蓋。介面名稱在任務間一致；計畫不把 U2～U4 塞入第一版，避免三視圖交付同時變動儲存格式及引擎。

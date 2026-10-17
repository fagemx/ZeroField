# 開源參考庫與採用決策

查核日期：2026-10-16。七個公開專案已以 shallow / partial / sparse checkout 克隆到 `.reference-repos/`；完整 commit、來源與取出目錄見 [版本鎖定清單](references/open-source-lock.json)。沒有安裝或執行這些專案。參考庫不進 Git、Docker build context 或 Python 發行封裝。

## 原始碼對照

| 參考庫／版本 | 本輪查閱與可借鏡設計 | 採用邊界 |
| --- | --- | --- |
| [baserow](https://github.com/baserow/baserow) · `0d332bec4934` | [來源](https://github.com/baserow/baserow/blob/0d332bec4934573693ac49397480b9ecd561a761/web-frontend/modules/database/components/view/gallery/GalleryView.vue)：Gallery 以相同 row、欄位與封面設定顯示卡片；保留列詳情與權限檢查。 | 借鏡互動與分層；不搬整套 Vue / Django。根 LICENSE 的 MIT 有 premium、enterprise、文件等例外；assistant 工具位於 enterprise 路徑，不能把 Kuma 當作已確認可直接複用的 MIT 程式碼。 [授權](https://github.com/baserow/baserow/blob/0d332bec4934573693ac49397480b9ecd561a761/LICENSE) |
| [teable](https://github.com/teableio/teable) · `b91d88eeb0e9` | [來源](https://github.com/teableio/teable/blob/b91d88eeb0e923263db24b7f8d29ddb4f50a544e/packages/core/src/models/view/derivate/kanban-view-option.schema.ts)：看板分組欄與封面欄是獨立設定；Gallery 同樣透過 coverFieldId 指定封面。 | apps 為 AGPL-3.0，packages 為 MIT，另列品牌條款；不能說整庫每一行都是 AGPL。此次只據此獨立設計，不複製程式碼。 [授權](https://github.com/teableio/teable/blob/b91d88eeb0e923263db24b7f8d29ddb4f50a544e/LICENSE) |
| [activepieces](https://github.com/activepieces/activepieces) · `82300fe80293` | [來源](https://github.com/activepieces/activepieces/blob/82300fe8029390e614f63eeac079ccc6db60eba6/packages/web/src/app/builder/data-selector/test-step-section.tsx)：沒有樣本資料時引導單步測試；waitpoints 文件描述持久化暫停、續跑與信號。 | MIT 核心／EE 分目錄。借鏡樣本、輸入輸出核對及暫停語意；不加入另一套執行引擎。發布流程審批與執行中的人工審核是不同功能。 [授權](https://github.com/activepieces/activepieces/blob/82300fe8029390e614f63eeac079ccc6db60eba6/LICENSE) |
| [affine](https://github.com/toeverything/AFFiNE) · `0b69a6da21e8` | [來源](https://github.com/toeverything/AFFiNE/blob/0b69a6da21e8fd35beb85667bb8496d9b3852238/blocksuite/affine/blocks/database/src/views/index.ts)：資料庫畫布以 view presets 切換 table / kanban / calendar。 | 根 LICENSE 把 backend 與 common/native 指向 EE；其他部分 MIT。借鏡簡潔閱讀、按需展開；不替換現有 Tiptap／資料儲存。 [授權](https://github.com/toeverything/AFFiNE/blob/0b69a6da21e8fd35beb85667bb8496d9b3852238/LICENSE) |
| [windmill](https://github.com/windmill-labs/windmill) · `33d4049db029` | [來源](https://github.com/windmill-labs/windmill/blob/33d4049db029e1dc478b1251c562232f0127fc8a/backend/windmill-common/src/worker.rs)：Worker 生命週期、工作分組與 worker_ping 身分等，適合檢查服務可用性設計。 | backend / frontend 主要為 AGPL，enterprise 條件有商業碼；客戶端／OpenFlow 另有 Apache。官方完整二進位的授權與可自行編譯的 OSS 不相同。只作架構參考。 [授權](https://github.com/windmill-labs/windmill/blob/33d4049db029e1dc478b1251c562232f0127fc8a/LICENSE) |
| [xyflow](https://github.com/xyflow/xyflow) · `654ba5a5e04f` | [來源](https://github.com/xyflow/xyflow/blob/654ba5a5e04f3404bc4db2eee88bfa15866d203d/examples/react/src/examples/SaveRestore/index.tsx)：React Flow 接收 nodes / edges、位置及 onNodesChange / onEdgesChange。 | MIT；優先採用候選。只換 Flow 視圖及互動，使用 adapter 保留 OpenBench DAG、節點設定、版本與 Worker 協定。鎖定原始碼的 package.json 為 12.12.0，安裝前仍需確認 npm 發布版。 [授權](https://github.com/xyflow/xyflow/blob/654ba5a5e04f3404bc4db2eee88bfa15866d203d/LICENSE) |
| [univer](https://github.com/dream-num/univer) · `7e73a4d83edb` | [來源](https://github.com/dream-num/univer/blob/7e73a4d83edbb2c5b1996dc93bb32cb9a5c951f6/README.md)：完整 Office SDK 的命令／插件與繪製模型；比較是否符合現有資料交接需求。 | 核心 Apache-2.0；功能逐項看 Pro 邊界。保留為工作簿方案候選，資料映射、自訂互動及檔案交接需比較驗證；不以 Canvas 實作方式直接排除。 [授權](https://github.com/dream-num/univer/blob/7e73a4d83edbb2c5b1996dc93bb32cb9a5c951f6/LICENSE) |

## 對另一位代理建議的採納與修正

- 保留為需求候選：同一份 sheet 的表格／圖庫／看板、代理提出 schema 變更、真正單步試跑、人工審核、漸進展開。依使用者最新指示，辦公、美術與自由組裝流程均納入操作設計，不能用兩條功能演示代替可用性。
- React Flow 是優先畫布候選，須驗證互動及既有資料轉接，再決定替換；核心 MIT 與 Pro 範例／模板的條件分開核對。
- [TanStack Table](https://tanstack.com/table/latest/docs/overview) 是 headless 表格引擎，並不自帶完整 Excel 編輯、Gallery 或代理核對 UI。與成熟 grid／workbook 候選按相同編輯、選取、貼上及復原任務比較；先前三視圖草稿已暫停，不作採用決策依據。
- [Univer 官方匯入匯出文件](https://docs.univer.ai/guides/sheets/features/import-export) 使用 Pro 套件；依功能與部署模式核對條件，不能簡化為所有功能都必須付費。這是候選排序決策，不是宣布 Univer 不適合所有媒體場景。
- openpyxl 並不保證任意 Excel 都能無損往返。OpenBench 已用 source_blob + OOXML 局部 Patch，支持界線及拒絕不安全結構修改的行為仍以 [ACCEPTANCE](ACCEPTANCE.md) 與 `test_file_handoff.py` 為準。
- 欄位級與逐筆提案核對不可只改按鈕：stable column IDs、過期檢查、關聯變更原子性及重匯入映射要一起設計。
- 現有 `start_node_id` 會帶動下游，不等於「只試這一步」。現有 awaiting_approval 是提案審核，不等於任意流程位置的獨立審核節點。兩者分別列入後續里程碑。
- 授權按目錄、檔案與使用方式判讀；此記錄是工程依賴選擇，不用「污染」描述開源授權。此次未將第三方程式碼複製到產品。

## 本地查閱與再現

```powershell
git -C .reference-repos/teable rev-parse HEAD
git -C .reference-repos/teable sparse-checkout list
git -C .reference-repos/teable status --short
```

重新取出時使用 lock 中 URL 與 commit（不要以日後的 HEAD 代替）：

```powershell
git init .reference-repos/teable
git -C .reference-repos/teable remote add origin https://github.com/teableio/teable.git
git -C .reference-repos/teable -c core.longpaths=true fetch --depth 1 --filter=blob:none origin b91d88eeb0e923263db24b7f8d29ddb4f50a544e
git -C .reference-repos/teable sparse-checkout set packages/core/src/models/view packages/sdk/src/components packages/sdk/src/views
git -C .reference-repos/teable -c core.longpaths=true checkout --detach FETCH_HEAD
```

後續產品設計及分期以 [可用性設計重整](PRODUCT_UX_REPLAN.md) 為準；[先前方案](superpowers/specs/2026-10-16-general-workbench.md) 保留作決策追溯，已停止依該方案施工。

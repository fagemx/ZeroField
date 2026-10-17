-- 專案文件的系統紀錄：誰、什麼時候、做了什麼（含內文每次存檔改了哪幾段）。
-- 只給工程查（python -m project_docs.history），畫面上不顯示；程式只新增、不改、不刪。
-- 執行期由 project_docs.repository.ensure_schema 在 151 之後套用；全部 IF NOT EXISTS，重跑不會改到既有資料。
-- 沒有外鍵：分頁或標註刪掉之後，紀錄還要留著。

CREATE TABLE IF NOT EXISTS projectops.audit_log (
  id BIGSERIAL PRIMARY KEY,
  project_slug TEXT NOT NULL,
  tab_key TEXT,
  actor_id UUID,
  action TEXT NOT NULL,
  target TEXT,
  detail JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS audit_log_project_time_idx ON projectops.audit_log (project_slug, created_at);

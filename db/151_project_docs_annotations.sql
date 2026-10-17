-- 專案文件 v2（/projects/）：文字標註、整列對話、編輯鎖。
-- 執行期由 project_docs.repository.ensure_schema 在 149 之後套用；全部 IF NOT EXISTS，重跑不會改到既有資料。

ALTER TABLE projectops.activity ADD COLUMN IF NOT EXISTS annotation_id BIGINT;
CREATE INDEX IF NOT EXISTS activity_annotation_idx
  ON projectops.activity (annotation_id) WHERE annotation_id IS NOT NULL;

-- 一則標註：選到的一段字（kind=text）或表格的一列（kind=row）。
-- 留言在 activity（annotation_id）；螢光筆／劃線是 style＋color；標籤是 label。
CREATE TABLE IF NOT EXISTS projectops.annotation (
  id BIGSERIAL PRIMARY KEY,
  project_slug TEXT NOT NULL,
  tab_key TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('text', 'row')),
  anchor JSONB NOT NULL,
  style TEXT CHECK (style IN ('hl', 'ul')),
  color TEXT CHECK (color IN ('y', 'g', 'b', 'p')),
  label TEXT CHECK (label IN ('q', 'fix', 'ok')),
  label_by UUID,
  label_at TIMESTAMPTZ,
  created_by UUID NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved_by UUID,
  resolved_at TIMESTAMPTZ,
  orphaned_at TIMESTAMPTZ,
  moved JSONB,
  reconfirm JSONB,
  deleted_at TIMESTAMPTZ,
  FOREIGN KEY (project_slug, tab_key)
    REFERENCES projectops.tab(project_slug, tab_key) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS annotation_tab_idx
  ON projectops.annotation (project_slug, tab_key) WHERE deleted_at IS NULL;
-- 一列只有一串整列對話
CREATE UNIQUE INDEX IF NOT EXISTS annotation_row_once
  ON projectops.annotation (project_slug, tab_key, (anchor->>'rid'))
  WHERE kind = 'row' AND deleted_at IS NULL;

-- 編輯鎖：某一塊（區塊 bid 或表格列 rid）正在被誰改；90 秒沒續約就過期。
CREATE TABLE IF NOT EXISTS projectops.block_lock (
  project_slug TEXT NOT NULL,
  tab_key TEXT NOT NULL,
  unit_id TEXT NOT NULL CHECK (unit_id ~ '^[A-Za-z0-9_-]{4,40}$'),
  actor_id UUID NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (project_slug, tab_key, unit_id)
);

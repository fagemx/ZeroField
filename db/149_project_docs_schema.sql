-- OpenBench 專案工作台基礎結構（/projects/）。
-- 執行期由 project_docs.repository.ensure_schema 套用：全部 IF NOT EXISTS，重跑不會改到既有資料。

CREATE SCHEMA IF NOT EXISTS projectops;

CREATE TABLE IF NOT EXISTS projectops.member (
  actor_id UUID PRIMARY KEY,
  display_name TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'member',
  email TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS projectops.project (
  slug TEXT PRIMARY KEY CHECK (slug ~ '^[a-z0-9][a-z0-9-]{0,40}$'),
  title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('planning', 'active', 'recurring', 'blocked', 'archived')),
  summary TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE projectops.project ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE projectops.project ADD COLUMN IF NOT EXISTS summary TEXT NOT NULL DEFAULT '';
ALTER TABLE projectops.project ADD COLUMN IF NOT EXISTS privacy_mode TEXT NOT NULL DEFAULT 'full_access'
  CHECK (privacy_mode IN ('full_access', 'mask_numbers'));

-- 一個分頁一份畫布資料（surface_type: doc | sheet | flow | board）。刪除只標 deleted_at，可以復原。
CREATE TABLE IF NOT EXISTS projectops.tab (
  project_slug TEXT NOT NULL REFERENCES projectops.project(slug) ON DELETE CASCADE,
  tab_key TEXT NOT NULL CHECK (tab_key ~ '^[a-z0-9][a-z0-9-]{0,40}$'),
  parent_key TEXT,
  title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
  surface_type TEXT NOT NULL DEFAULT 'doc'
    CHECK (surface_type IN ('doc', 'sheet', 'flow', 'board')),
  position INTEGER NOT NULL DEFAULT 0,
  doc JSONB NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  updated_by UUID,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at TIMESTAMPTZ,
  PRIMARY KEY (project_slug, tab_key)
);

ALTER TABLE projectops.tab ADD COLUMN IF NOT EXISTS surface_type TEXT NOT NULL DEFAULT 'doc';
ALTER TABLE projectops.tab ADD COLUMN IF NOT EXISTS source_filename TEXT;
ALTER TABLE projectops.tab ADD COLUMN IF NOT EXISTS source_mime TEXT;
ALTER TABLE projectops.tab ADD COLUMN IF NOT EXISTS source_blob BYTEA;
ALTER TABLE projectops.tab ADD COLUMN IF NOT EXISTS source_meta JSONB;
ALTER TABLE projectops.tab ADD COLUMN IF NOT EXISTS linked_path TEXT;

-- 一次編輯（同一個 session）一個版本：自動儲存在同一個 session 裡覆寫同一列。
CREATE TABLE IF NOT EXISTS projectops.tab_revision (
  id BIGSERIAL PRIMARY KEY,
  project_slug TEXT NOT NULL,
  tab_key TEXT NOT NULL,
  revision INTEGER NOT NULL,
  title TEXT NOT NULL,
  doc JSONB NOT NULL,
  session_id TEXT NOT NULL DEFAULT '',
  saved_by UUID,
  saved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (project_slug, tab_key, revision),
  FOREIGN KEY (project_slug, tab_key)
    REFERENCES projectops.tab(project_slug, tab_key) ON DELETE CASCADE
);

-- 狀態、大家可填的格子、勾選清單的目前值。沒有列＝畫布裡的預設值。
CREATE TABLE IF NOT EXISTS projectops.field_value (
  project_slug TEXT NOT NULL,
  tab_key TEXT NOT NULL,
  field_id TEXT NOT NULL CHECK (field_id ~ '^[A-Za-z0-9_-]{4,40}$'),
  kind TEXT NOT NULL CHECK (kind IN ('status', 'fill', 'check')),
  value TEXT NOT NULL,
  updated_by UUID NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (project_slug, tab_key, field_id),
  FOREIGN KEY (project_slug, tab_key)
    REFERENCES projectops.tab(project_slug, tab_key) ON DELETE CASCADE
);

-- 對話串：留言與欄位變更都掛在 (tab_key, anchor_id)。mentions 只放名單上的 actor_id。
CREATE TABLE IF NOT EXISTS projectops.activity (
  id BIGSERIAL PRIMARY KEY,
  project_slug TEXT NOT NULL,
  tab_key TEXT NOT NULL,
  anchor_id TEXT NOT NULL CHECK (anchor_id ~ '^[A-Za-z0-9_-]{1,40}$'),
  kind TEXT NOT NULL CHECK (kind IN ('comment', 'status', 'fill', 'check')),
  body TEXT NOT NULL DEFAULT '',
  mentions UUID[] NOT NULL DEFAULT '{}',
  field_id TEXT,
  field_label TEXT,
  old_value TEXT,
  new_value TEXT,
  actor_id UUID NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at TIMESTAMPTZ,
  FOREIGN KEY (project_slug, tab_key)
    REFERENCES projectops.tab(project_slug, tab_key) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS activity_anchor_idx
  ON projectops.activity (project_slug, tab_key, anchor_id, created_at);
CREATE INDEX IF NOT EXISTS activity_mentions_idx
  ON projectops.activity USING GIN (mentions);

-- 「提及我」的已讀時間，一人一專案一列。
CREATE TABLE IF NOT EXISTS projectops.reader_state (
  project_slug TEXT NOT NULL REFERENCES projectops.project(slug) ON DELETE CASCADE,
  actor_id UUID NOT NULL,
  mentions_seen_at TIMESTAMPTZ NOT NULL DEFAULT 'epoch',
  PRIMARY KEY (project_slug, actor_id)
);

-- 文件裡的圖片。id 是內容雜湊，同一張圖只存一次；只有登入的人拿得到。
CREATE TABLE IF NOT EXISTS projectops.asset (
  project_slug TEXT NOT NULL REFERENCES projectops.project(slug) ON DELETE CASCADE,
  asset_id TEXT NOT NULL CHECK (asset_id ~ '^pa_[0-9a-f]{32}$'),
  content_type TEXT NOT NULL
    CHECK (content_type IN ('image/png', 'image/jpeg', 'image/gif', 'image/webp', 'video/mp4', 'video/webm',
                           'audio/mpeg', 'audio/mp4', 'audio/webm', 'audio/wav', 'audio/ogg', 'audio/flac')),
  data BYTEA NOT NULL,
  byte_size INTEGER NOT NULL,
  uploaded_by UUID NOT NULL,
  uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (project_slug, asset_id)
);

-- Upgrade existing image-only workspaces without rewriting any stored assets.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='projectops.asset'::regclass
             AND conname='asset_content_type_check' AND pg_get_constraintdef(oid) NOT LIKE '%video/mp4%') THEN
    ALTER TABLE projectops.asset DROP CONSTRAINT asset_content_type_check;
    ALTER TABLE projectops.asset ADD CONSTRAINT asset_content_type_check
      CHECK (content_type IN ('image/png', 'image/jpeg', 'image/gif', 'image/webp', 'video/mp4', 'video/webm',
                             'audio/mpeg', 'audio/mp4', 'audio/webm', 'audio/wav', 'audio/ogg', 'audio/flac'));
  END IF;
END $$;

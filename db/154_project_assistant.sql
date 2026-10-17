-- 專案助理：成員、對話（同時是任務佇列）、提案、負責人交代、私下轉問、設定。
-- 執行期由 project_docs.repository.ensure_schema 在 153 之後套用；全部 IF NOT EXISTS，重跑不會改到既有資料。
-- 身分欄位是 projectops.member 的 actor_id。對話存的是遮過數字和權杖的文字。

CREATE TABLE IF NOT EXISTS projectops.assistant_member (
  project_slug TEXT NOT NULL,
  actor_id UUID NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT FALSE,
  updated_by UUID,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (project_slug, actor_id)
);

CREATE TABLE IF NOT EXISTS projectops.assistant_message (
  id BIGSERIAL PRIMARY KEY,
  project_slug TEXT NOT NULL,
  owner_id UUID NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'lead')),
  body TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'done' CHECK (status IN ('done', 'queued', 'running', 'failed')),
  reply_to BIGINT,
  attempts INTEGER NOT NULL DEFAULT 0,
  lease_owner TEXT,
  lease_until TIMESTAMPTZ,
  error_kind TEXT,
  seconds NUMERIC(7, 1),
  tools JSONB NOT NULL DEFAULT '[]'::jsonb,
  notes JSONB NOT NULL DEFAULT '[]'::jsonb,
  model TEXT,
  codex_version TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS assistant_message_thread_idx
  ON projectops.assistant_message (project_slug, owner_id, id);
ALTER TABLE projectops.assistant_message ADD COLUMN IF NOT EXISTS request_scope JSONB;
CREATE INDEX IF NOT EXISTS assistant_message_work_idx
  ON projectops.assistant_message (id) WHERE status IN ('queued', 'running');

-- Upgrade older installations to the neutral manager role name.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'projectops.assistant_message'::regclass
      AND conname = 'assistant_message_role_check'
      AND pg_get_constraintdef(oid) LIKE '%lead%'
  ) THEN
    ALTER TABLE projectops.assistant_message DROP CONSTRAINT IF EXISTS assistant_message_role_check;
    UPDATE projectops.assistant_message SET role = 'lead' WHERE role NOT IN ('user', 'assistant', 'lead');
    ALTER TABLE projectops.assistant_message ADD CONSTRAINT assistant_message_role_check CHECK (role IN ('user', 'assistant', 'lead'));
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS projectops.assistant_proposal (
  id BIGSERIAL PRIMARY KEY,
  project_slug TEXT NOT NULL,
  owner_id UUID NOT NULL,
  message_id BIGINT,
  action TEXT NOT NULL,
  target JSONB NOT NULL DEFAULT '{}'::jsonb,
  content TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'applied', 'dismissed', 'failed')),
  result JSONB,
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  decided_at TIMESTAMPTZ,
  decided_by UUID
);
CREATE INDEX IF NOT EXISTS assistant_proposal_owner_idx
  ON projectops.assistant_proposal (project_slug, owner_id, id);

CREATE TABLE IF NOT EXISTS projectops.assistant_note (
  id BIGSERIAL PRIMARY KEY,
  project_slug TEXT NOT NULL,
  author_id UUID NOT NULL,
  target_id UUID,  -- 交代給誰；NULL＝所有開放的人
  body TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  done_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS projectops.assistant_forward (
  id BIGSERIAL PRIMARY KEY,
  project_slug TEXT NOT NULL,
  owner_id UUID NOT NULL,
  proposal_id BIGINT,
  question TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'answered')),
  answer TEXT,
  answered_by UUID,
  answered_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS projectops.assistant_setting (
  project_slug TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (project_slug, key)
);

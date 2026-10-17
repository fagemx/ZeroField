-- Project-scoped personas. Credential values are never stored here.
CREATE TABLE IF NOT EXISTS projectops.agent_profile (
  project_slug TEXT NOT NULL REFERENCES projectops.project(slug) ON DELETE CASCADE,
  agent_key TEXT NOT NULL CHECK (agent_key ~ '^[a-z][a-z0-9_-]{0,63}$'),
  display_name TEXT NOT NULL,
  icon TEXT NOT NULL DEFAULT '🤖',
  role_kind TEXT NOT NULL DEFAULT 'worker' CHECK (role_kind IN ('primary','worker','observer')),
  runtime_kind TEXT NOT NULL DEFAULT 'builtin_llm' CHECK (runtime_kind IN ('builtin_llm','acp_stdio','remote_limb')),
  description TEXT NOT NULL DEFAULT '',
  system_prompt TEXT NOT NULL DEFAULT '',
  knowledge_pack TEXT NOT NULL DEFAULT '',
  capabilities JSONB NOT NULL DEFAULT '["llm"]',
  labels JSONB NOT NULL DEFAULT '{}',
  allowed_tools JSONB NOT NULL DEFAULT '[]',
  provider_config JSONB NOT NULL DEFAULT '{}',
  bound_limb_id UUID REFERENCES projectops.agent_limb(id) ON DELETE SET NULL,
  max_concurrency INTEGER NOT NULL DEFAULT 2 CHECK (max_concurrency BETWEEN 1 AND 32),
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY(project_slug,agent_key)
);
ALTER TABLE projectops.assistant_message
  ADD COLUMN IF NOT EXISTS agent_key TEXT NOT NULL DEFAULT 'coordinator',
  ADD COLUMN IF NOT EXISTS agent_snapshot JSONB;
ALTER TABLE projectops.assistant_proposal
  ADD COLUMN IF NOT EXISTS agent_key TEXT;
-- Preserve one active answer per persona when upgrading an older database.
WITH duplicate AS (
 SELECT id, row_number() OVER(PARTITION BY project_slug,owner_id,agent_key ORDER BY id) AS n
 FROM projectops.assistant_message WHERE role='assistant' AND status IN ('queued','running')
)
UPDATE projectops.assistant_message SET status='failed',error_kind='migration_duplicate',
       body='此角色已有較早的回答正在處理，請稍後重新送出。',
       lease_owner=NULL,lease_until=NULL,finished_at=NOW()
WHERE id IN (SELECT id FROM duplicate WHERE n>1);
CREATE UNIQUE INDEX IF NOT EXISTS assistant_one_active_agent_reply
 ON projectops.assistant_message(project_slug,owner_id,agent_key)
 WHERE role='assistant' AND status IN ('queued','running');

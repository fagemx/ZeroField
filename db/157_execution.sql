-- Durable, project-scoped remote execution. Tokens are stored only as SHA-256 hashes.
CREATE TABLE IF NOT EXISTS projectops.agent_limb (
  id UUID PRIMARY KEY,
  name TEXT NOT NULL,
  capabilities JSONB NOT NULL,
  allowed_projects JSONB NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_by UUID NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_seen_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS projectops.flow_definition (
  project_slug TEXT NOT NULL REFERENCES projectops.project(slug),
  tab_key TEXT NOT NULL,
  definition JSONB NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  updated_by UUID NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY(project_slug, tab_key)
);
CREATE TABLE IF NOT EXISTS projectops.flow_run (
  id UUID PRIMARY KEY,
  project_slug TEXT NOT NULL REFERENCES projectops.project(slug),
  tab_key TEXT NOT NULL,
  definition JSONB NOT NULL,
  definition_revision INTEGER NOT NULL,
  created_by UUID NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','awaiting_approval','succeeded','failed','canceled')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS flow_run_project_idx ON projectops.flow_run(project_slug,tab_key,created_at DESC);
-- Expansion bookkeeping is separate from the immutable definition snapshot.
ALTER TABLE projectops.flow_run ADD COLUMN IF NOT EXISTS execution JSONB NOT NULL DEFAULT '{}'::jsonb;
CREATE TABLE IF NOT EXISTS projectops.limb_task (
  id UUID PRIMARY KEY,
  run_id UUID NOT NULL REFERENCES projectops.flow_run(id),
  project_slug TEXT NOT NULL,
  node_id TEXT NOT NULL,
  row_id TEXT NOT NULL DEFAULT '',
  capability TEXT NOT NULL CHECK(capability IN ('llm','image_gen','video_gen','media_assemble')),
  assigned_limb UUID REFERENCES projectops.agent_limb(id),
  status TEXT NOT NULL CHECK(status IN ('blocked','queued','running','awaiting_approval','succeeded','failed','canceled')),
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  limb_id UUID REFERENCES projectops.agent_limb(id),
  lease_hash TEXT,
  lease_until TIMESTAMPTZ,
  target JSONB NOT NULL DEFAULT '{}'::jsonb,
  target_snapshot JSONB,
  output JSONB,
  proposal_id BIGINT REFERENCES projectops.assistant_proposal(id),
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(run_id,node_id,row_id)
);
CREATE INDEX IF NOT EXISTS limb_task_claim_idx ON projectops.limb_task(run_id,status,created_at);

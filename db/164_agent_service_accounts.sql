-- SPEC_20 R31: service-account tokens for external agents (zerofield-mcp, R30).
-- The account row stays the versioned Console resource from 163 (its revision snapshots never carry a
-- secret); the token's SHA-256 lives in agent_service_token, which has no revision trigger, and the
-- plaintext token is returned once at creation. A token is scoped to one production, a tool list and a
-- write mode, always expires and can be revoked. Applied by repository.ensure_schema after 163; re-running
-- changes nothing.

ALTER TABLE projectops.agent_service_account ALTER COLUMN limb_id DROP NOT NULL;
ALTER TABLE projectops.agent_service_account
  ADD COLUMN IF NOT EXISTS tools JSONB NOT NULL DEFAULT '[]',
  ADD COLUMN IF NOT EXISTS write_mode TEXT NOT NULL DEFAULT 'propose_only' CHECK (write_mode IN ('propose_only','generate')),
  ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS created_by UUID,
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS revoked_by UUID;

CREATE TABLE IF NOT EXISTS projectops.agent_service_token (
  token_hash TEXT PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
  project_slug TEXT NOT NULL,
  account_key TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_used_at TIMESTAMPTZ,
  FOREIGN KEY (project_slug, account_key)
    REFERENCES projectops.agent_service_account(project_slug, account_key) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS agent_service_token_account_idx
  ON projectops.agent_service_token(project_slug, account_key);

-- Idempotent external requests (request_generation's requestId): the first result is replayed.
CREATE TABLE IF NOT EXISTS projectops.agent_service_request (
  project_slug TEXT NOT NULL,
  account_key TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  request_id TEXT NOT NULL CHECK (length(request_id) BETWEEN 1 AND 128),
  args_digest TEXT NOT NULL,
  result JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (project_slug, account_key, tool_name, request_id),
  FOREIGN KEY (project_slug, account_key)
    REFERENCES projectops.agent_service_account(project_slug, account_key) ON DELETE CASCADE
);

-- Console resources only; existing M8 and Story authorities are unchanged.
ALTER TABLE projectops.agent_profile
  ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS effort TEXT NOT NULL DEFAULT 'medium' CHECK (effort IN ('low','medium','high')),
  ADD COLUMN IF NOT EXISTS skill_keys JSONB NOT NULL DEFAULT '[]',
  ADD COLUMN IF NOT EXISTS tool_policies JSONB NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS multiagent_config JSONB NOT NULL DEFAULT '{"allow_subagents":false,"allow_workflows":false,"advisor_agent_key":null}',
  ADD COLUMN IF NOT EXISTS outcome_grader JSONB NOT NULL DEFAULT '{"enabled":false,"criteria":"","grader_agent_key":"qa_critic","max_revisions":1}',
  ADD COLUMN IF NOT EXISTS memory_mounts JSONB NOT NULL DEFAULT '[]',
  ADD COLUMN IF NOT EXISTS default_environment_key TEXT NOT NULL DEFAULT 'env_local_4090';

-- 1. Versioned Skills Registry (Built-in + Custom per project)
CREATE TABLE IF NOT EXISTS projectops.agent_skill (
  project_slug TEXT NOT NULL REFERENCES projectops.project(slug) ON DELETE CASCADE,
  skill_key TEXT NOT NULL CHECK (skill_key ~ '^[a-z][a-z0-9_-]{0,63}$'),
  display_name TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'cinema' CHECK (category IN ('cinema','document','data','custom')),
  version INTEGER NOT NULL DEFAULT 1,
  built_in BOOLEAN NOT NULL DEFAULT FALSE,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  summary TEXT NOT NULL DEFAULT '',
  instructions_md TEXT NOT NULL DEFAULT '',
  recommended_tools JSONB NOT NULL DEFAULT '[]',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (project_slug, skill_key)
);

-- 2. Execution Environments (Local 4090 Sandbox, Hybrid Cloud Pool, Local ACP CLI)
CREATE TABLE IF NOT EXISTS projectops.agent_environment (
  project_slug TEXT NOT NULL REFERENCES projectops.project(slug) ON DELETE CASCADE,
  env_key TEXT NOT NULL CHECK (env_key ~ '^[a-z][a-z0-9_-]{0,63}$'),
  display_name TEXT NOT NULL,
  env_kind TEXT NOT NULL CHECK (env_kind IN ('local_sandbox','hybrid_cloud','acp_cli','remote_worker')),
  config JSONB NOT NULL DEFAULT '{}',
  network_access TEXT NOT NULL DEFAULT 'restricted' CHECK (network_access IN ('offline','restricted','allowlist','full')),
  allowed_hosts JSONB NOT NULL DEFAULT '[]',
  packages JSONB NOT NULL DEFAULT '[]',
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (project_slug, env_key)
);

-- 3. Persistent Cross-Session Memory Stores & Versioned Entries
CREATE TABLE IF NOT EXISTS projectops.agent_memory_store (
  project_slug TEXT NOT NULL REFERENCES projectops.project(slug) ON DELETE CASCADE,
  store_key TEXT NOT NULL CHECK (store_key ~ '^[a-z][a-z0-9_-]{0,63}$'),
  display_name TEXT NOT NULL,
  scope_kind TEXT NOT NULL DEFAULT 'project' CHECK (scope_kind IN ('project','episode','user')),
  description TEXT NOT NULL DEFAULT '',
  version INTEGER NOT NULL DEFAULT 1,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  scope_id TEXT NOT NULL DEFAULT '',
  CHECK ((scope_kind='project' AND scope_id='') OR (scope_kind<>'project' AND length(scope_id) BETWEEN 1 AND 160)),
  PRIMARY KEY (project_slug, store_key)
);

CREATE TABLE IF NOT EXISTS projectops.agent_memory_entry (
  id UUID PRIMARY KEY,
  project_slug TEXT NOT NULL,
  store_key TEXT NOT NULL,
  entry_key TEXT NOT NULL,
  title TEXT NOT NULL,
  content_md TEXT NOT NULL,
  tags JSONB NOT NULL DEFAULT '[]',
  version INTEGER NOT NULL DEFAULT 1,
  updated_by TEXT NOT NULL DEFAULT 'system',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  FOREIGN KEY (project_slug, store_key) REFERENCES projectops.agent_memory_store(project_slug, store_key) ON DELETE CASCADE,
  UNIQUE (project_slug, store_key, entry_key)
);

-- 4. Managed Deployments (Manual 1-Click & Scheduled Cron Triggers)
CREATE TABLE IF NOT EXISTS projectops.agent_deployment (
  id UUID PRIMARY KEY,
  project_slug TEXT NOT NULL REFERENCES projectops.project(slug) ON DELETE CASCADE,
  deployment_key TEXT NOT NULL CHECK (deployment_key ~ '^[a-z][a-z0-9_-]{0,63}$'),
  display_name TEXT NOT NULL,
  agent_key TEXT NOT NULL,
  env_key TEXT NOT NULL DEFAULT 'env_local_4090',
  template_key TEXT,
  initial_prompt TEXT NOT NULL DEFAULT '',
  target_scope JSONB NOT NULL DEFAULT '{}',
  schedule_kind TEXT NOT NULL DEFAULT 'manual' CHECK (schedule_kind IN ('manual','cron','event')),
  cron_expr TEXT NOT NULL DEFAULT '',
  timezone TEXT NOT NULL DEFAULT 'Asia/Taipei',
  budget_cap_usd NUMERIC(10,2) NOT NULL DEFAULT 5.00 CHECK (budget_cap_usd >= 0 AND budget_cap_usd < 1000000),
  on_budget_exceeded TEXT NOT NULL DEFAULT 'downgrade_open_weights' CHECK (on_budget_exceeded IN ('pause','downgrade_open_weights')),
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  last_run_id UUID REFERENCES projectops.orchestration_run(id) ON DELETE SET NULL,
  last_run_at TIMESTAMPTZ,
  created_by UUID,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (project_slug, deployment_key)
);

-- 5. Async Batch Jobs (Bulk Messages / Storyboard Extraction)
CREATE TABLE IF NOT EXISTS projectops.agent_batch_job (
  id UUID PRIMARY KEY,
  project_slug TEXT NOT NULL REFERENCES projectops.project(slug) ON DELETE CASCADE,
  title TEXT NOT NULL,
  agent_key TEXT NOT NULL,
  batch_kind TEXT NOT NULL CHECK (batch_kind IN ('script_scenes','shot_prompts','subtitle_i18n','continuity_audit')),
  status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','completed','failed','canceled')),
  total_items INTEGER NOT NULL DEFAULT 0,
  completed_items INTEGER NOT NULL DEFAULT 0,
  input_payload JSONB NOT NULL DEFAULT '[]',
  results_json JSONB NOT NULL DEFAULT '[]',
  estimated_discount_pct INTEGER NOT NULL DEFAULT 50,
  created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ,
  CHECK (total_items BETWEEN 0 AND 100000 AND completed_items BETWEEN 0 AND total_items),
  CHECK (estimated_discount_pct BETWEEN 0 AND 100)
);

-- 6. Usage, Cache & Cost Ledger + Project Spend Limits & Webhooks
CREATE TABLE IF NOT EXISTS projectops.agent_usage_ledger (
  id BIGSERIAL PRIMARY KEY,
  event_key TEXT NOT NULL CHECK (length(event_key) BETWEEN 1 AND 160),
  episode_id TEXT,
  owner_id UUID,
  project_slug TEXT NOT NULL REFERENCES projectops.project(slug) ON DELETE CASCADE,
  -- Historical identity survives run retention; append_usage validates project ownership.
  run_id UUID,
  agent_key TEXT NOT NULL,
  provider_name TEXT NOT NULL DEFAULT 'local',
  model_name TEXT NOT NULL DEFAULT 'default',
  usage_kind TEXT NOT NULL CHECK (usage_kind IN ('llm_turn','image_gen','video_gen','frame_prep','grader_check')),
  tier TEXT NOT NULL DEFAULT 'open_weights' CHECK (tier IN ('open_weights','closed_flagship','cloud_comfy')),
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cached_tokens INTEGER NOT NULL DEFAULT 0,
  cache_hit BOOLEAN NOT NULL DEFAULT FALSE,
  fingerprint TEXT,
  duration_ms INTEGER NOT NULL DEFAULT 0,
  estimated_cost_usd NUMERIC(10,4) NOT NULL DEFAULT 0.0000,
  estimated_saved_usd NUMERIC(10,4) NOT NULL DEFAULT 0.0000,
  meta JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(project_slug,event_key),
  CHECK (input_tokens >= 0 AND output_tokens >= 0 AND cached_tokens BETWEEN 0 AND input_tokens AND duration_ms >= 0),
  CHECK (estimated_cost_usd >= 0 AND estimated_cost_usd < 1000000 AND estimated_saved_usd >= 0 AND estimated_saved_usd < 1000000)
);

CREATE TABLE IF NOT EXISTS projectops.agent_console_settings (
  project_slug TEXT PRIMARY KEY REFERENCES projectops.project(slug) ON DELETE CASCADE,
  spend_limit_monthly_usd NUMERIC(10,2) NOT NULL DEFAULT 100.00,
  spend_limit_session_usd NUMERIC(10,2) NOT NULL DEFAULT 5.00,
  spend_limit_episode_usd NUMERIC(10,2) NOT NULL DEFAULT 15.00,
  on_spend_limit TEXT NOT NULL DEFAULT 'downgrade_open_weights' CHECK (on_spend_limit IN ('pause','downgrade_open_weights')),
  rate_limits JSONB NOT NULL DEFAULT '{"rpm_per_agent":30,"max_concurrent_renders":2,"max_concurrent_llm":4}',
  retention_policy JSONB NOT NULL DEFAULT '{"session_logs_days":90,"temp_media_days":14,"zero_data_retention_notice":true}',
  otel_config JSONB NOT NULL DEFAULT '{"enabled":false,"endpoint":"","service_name":"zerofield-studio"}',
  webhooks JSONB NOT NULL DEFAULT '[]',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (spend_limit_monthly_usd >= 0 AND spend_limit_monthly_usd < 1000000),
  CHECK (spend_limit_session_usd >= 0 AND spend_limit_session_usd < 1000000),
  CHECK (spend_limit_episode_usd >= 0 AND spend_limit_episode_usd < 1000000)
);

-- Bind existing identities/delivery implementations; these references grant no authority.
CREATE TABLE IF NOT EXISTS projectops.agent_vault_reference (
 project_slug TEXT NOT NULL REFERENCES projectops.project(slug) ON DELETE CASCADE,
 vault_key TEXT NOT NULL CHECK (vault_key ~ '^[a-z][a-z0-9_-]{0,63}$'),
 display_name TEXT NOT NULL,
 provider_config JSONB NOT NULL DEFAULT '{}',
 allowed_agent_keys JSONB NOT NULL DEFAULT '[]',
 enabled BOOLEAN NOT NULL DEFAULT TRUE,
 PRIMARY KEY(project_slug,vault_key)
);
CREATE TABLE IF NOT EXISTS projectops.agent_service_account (
 project_slug TEXT NOT NULL REFERENCES projectops.project(slug) ON DELETE CASCADE,
 account_key TEXT NOT NULL CHECK (account_key ~ '^[a-z][a-z0-9_-]{0,63}$'),
 display_name TEXT NOT NULL,
 limb_id UUID NOT NULL REFERENCES projectops.agent_limb(id) ON DELETE CASCADE,
 enabled BOOLEAN NOT NULL DEFAULT TRUE,
 PRIMARY KEY(project_slug,account_key)
);
CREATE TABLE IF NOT EXISTS projectops.agent_resource_revision (
 project_slug TEXT NOT NULL REFERENCES projectops.project(slug) ON DELETE CASCADE,
 resource_kind TEXT NOT NULL,
 resource_key TEXT NOT NULL,
 version INTEGER NOT NULL CHECK (version > 0),
 snapshot JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 PRIMARY KEY(project_slug,resource_kind,resource_key,version)
);
CREATE OR REPLACE FUNCTION projectops.console_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' AND NOT EXISTS(SELECT 1 FROM projectops.project WHERE slug=OLD.project_slug) THEN
   RETURN OLD;
 END IF;
 RAISE EXCEPTION 'Console history and ledger events are immutable';
END $$;
DROP TRIGGER IF EXISTS console_immutable ON projectops.agent_resource_revision;
CREATE TRIGGER console_immutable BEFORE UPDATE OR DELETE ON projectops.agent_resource_revision
 FOR EACH ROW EXECUTE FUNCTION projectops.console_immutable();
DROP TRIGGER IF EXISTS console_immutable ON projectops.agent_usage_ledger;
CREATE TRIGGER console_immutable BEFORE UPDATE OR DELETE ON projectops.agent_usage_ledger
 FOR EACH ROW EXECUTE FUNCTION projectops.console_immutable();
CREATE OR REPLACE FUNCTION projectops.console_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' THEN
   NEW.version := OLD.version+1;
   NEW.updated_at := NOW();
 END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION projectops.console_revision() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 INSERT INTO projectops.agent_resource_revision(project_slug,resource_kind,resource_key,version,snapshot)
 VALUES(NEW.project_slug,TG_ARGV[0],to_jsonb(NEW)->>TG_ARGV[1],NEW.version,to_jsonb(NEW));
 RETURN NEW;
END $$;
-- Snapshots and automatic versions cover legacy profile writes too. No runtime-kind relaxation.
DO $$
DECLARE item text[];
BEGIN
 FOREACH item SLICE 1 IN ARRAY ARRAY[
  ['profile','agent_profile','agent_key'],['skill','agent_skill','skill_key'],
  ['environment','agent_environment','env_key'],['memory_store','agent_memory_store','store_key'],
  ['memory_entry','agent_memory_entry','id'],['deployment','agent_deployment','deployment_key'],
  ['batch','agent_batch_job','id'],['settings','agent_console_settings','project_slug'],
  ['vault','agent_vault_reference','vault_key'],['service_account','agent_service_account','account_key']
 ] LOOP
  EXECUTE format('ALTER TABLE projectops.%I ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1, ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()',item[2]);
  EXECUTE format('DROP TRIGGER IF EXISTS console_version ON projectops.%I',item[2]);
  EXECUTE format('CREATE TRIGGER console_version BEFORE UPDATE ON projectops.%I FOR EACH ROW EXECUTE FUNCTION projectops.console_version()',item[2]);
  EXECUTE format('DROP TRIGGER IF EXISTS console_revision ON projectops.%I',item[2]);
  EXECUTE format('CREATE TRIGGER console_revision AFTER INSERT OR UPDATE ON projectops.%I FOR EACH ROW EXECUTE FUNCTION projectops.console_revision(%L,%L)',item[2],item[1],item[3]);
  EXECUTE format('INSERT INTO projectops.agent_resource_revision(project_slug,resource_kind,resource_key,version,snapshot) SELECT project_slug,%L,%I::text,version,to_jsonb(t) FROM projectops.%I t ON CONFLICT DO NOTHING',item[1],item[3],item[2]);
 END LOOP;
END $$;
CREATE INDEX IF NOT EXISTS agent_usage_project_date_idx ON projectops.agent_usage_ledger(project_slug,created_at);

-- Short-lived outbound capacity, retained uncertain spend, immutable settlement.
-- Nullable money is unknown pricing, never evidence of a free local/provider call.
ALTER TABLE projectops.agent_usage_ledger
 ALTER COLUMN estimated_cost_usd DROP NOT NULL,
 ADD COLUMN IF NOT EXISTS observed_cost_usd NUMERIC(10,4) CHECK (observed_cost_usd>=0 AND observed_cost_usd<1000000),
 ADD COLUMN IF NOT EXISTS pricing_provenance TEXT NOT NULL DEFAULT 'legacy_estimate',
 ADD COLUMN IF NOT EXISTS session_key TEXT;
ALTER TABLE projectops.agent_console_settings ADD COLUMN IF NOT EXISTS model_pricing JSONB NOT NULL DEFAULT '{}';
CREATE TABLE IF NOT EXISTS projectops.agent_usage_reservation (
 project_slug TEXT NOT NULL REFERENCES projectops.project(slug) ON DELETE CASCADE,
 request_key TEXT NOT NULL CHECK(length(request_key) BETWEEN 1 AND 160),
 session_key TEXT NOT NULL CHECK(length(session_key) BETWEEN 1 AND 160),
 episode_id TEXT, run_id UUID, owner_id UUID NOT NULL,
 agent_key TEXT NOT NULL, usage_kind TEXT NOT NULL,
 category TEXT NOT NULL CHECK(category IN ('llm','render')),
 provider_name TEXT NOT NULL, model_name TEXT NOT NULL, tier TEXT NOT NULL,
 ceiling_cost_usd NUMERIC(10,4) CHECK(ceiling_cost_usd>=0 AND ceiling_cost_usd<1000000),
 accounted_cost_usd NUMERIC(10,4) CHECK(accounted_cost_usd>=0 AND accounted_cost_usd<1000000),
 pricing_provenance TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'reserved' CHECK(state IN ('reserved','dispatched','finalized','released','uncertain')),
 lease_until TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 PRIMARY KEY(project_slug,request_key)
);
CREATE INDEX IF NOT EXISTS agent_reservation_admission_idx ON projectops.agent_usage_reservation(project_slug,state,created_at);

ALTER TABLE projectops.agent_console_settings
 ADD COLUMN IF NOT EXISTS judge_trial_mode BOOLEAN NOT NULL DEFAULT FALSE,
 ADD COLUMN IF NOT EXISTS judge_trial_cap_runs INTEGER NOT NULL DEFAULT 10 CHECK(judge_trial_cap_runs BETWEEN 1 AND 1000),
 ADD COLUMN IF NOT EXISTS judge_trial_used_runs INTEGER NOT NULL DEFAULT 0 CHECK(judge_trial_used_runs>=0);
ALTER TABLE projectops.agent_usage_reservation
 ADD COLUMN IF NOT EXISTS operation_digest TEXT,
 ADD COLUMN IF NOT EXISTS quote_expires_at TIMESTAMPTZ;
-- Queued batches reserve currency and judge admissions, not execution concurrency.
ALTER TABLE projectops.agent_usage_reservation DROP CONSTRAINT IF EXISTS agent_usage_reservation_state_check;
ALTER TABLE projectops.agent_usage_reservation ADD CONSTRAINT agent_usage_reservation_state_check
 CHECK(state IN ('queued','reserved','dispatched','finalized','released','uncertain'));
CREATE TABLE IF NOT EXISTS projectops.agent_generation_admission (
 project_slug TEXT NOT NULL REFERENCES projectops.project(slug) ON DELETE CASCADE,
 operation_key TEXT NOT NULL CHECK(length(operation_key) BETWEEN 1 AND 160),
 owner_id UUID NOT NULL, operation_digest TEXT NOT NULL,
 protected BOOLEAN NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 PRIMARY KEY(project_slug,operation_key)
);
-- Fence duplicate remote completion requests before any server-side grading call.
ALTER TABLE projectops.orchestration_dispatch
 ADD COLUMN IF NOT EXISTS outcome_grading_started BOOLEAN NOT NULL DEFAULT FALSE,
 ADD COLUMN IF NOT EXISTS outcome_candidate_digest TEXT;
ALTER TABLE projectops.agent_usage_reservation ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
ALTER TABLE projectops.agent_usage_ledger
 ALTER COLUMN estimated_cost_usd SET DEFAULT NULL,
 ALTER COLUMN estimated_saved_usd DROP NOT NULL,
 ALTER COLUMN estimated_saved_usd SET DEFAULT NULL;
ALTER TABLE projectops.agent_usage_reservation ADD COLUMN IF NOT EXISTS session_cap_usd NUMERIC(10,4) CHECK(session_cap_usd>=0 AND session_cap_usd<1000000);

-- Official Router estimates are not price locks; opt-in is project/admin-only.
ALTER TABLE projectops.agent_console_settings ADD COLUMN IF NOT EXISTS comfy_router_budget_mode TEXT NOT NULL DEFAULT 'hard' CHECK(comfy_router_budget_mode IN ('hard','estimate_soft'));
ALTER TABLE projectops.agent_usage_reservation
 ADD COLUMN IF NOT EXISTS provider_input_digest TEXT,
 ADD COLUMN IF NOT EXISTS quote_hard_bound BOOLEAN NOT NULL DEFAULT TRUE,
 ADD COLUMN IF NOT EXISTS reported_cost_usd NUMERIC(18,8) CHECK(reported_cost_usd>=0);
ALTER TABLE projectops.agent_usage_reservation ADD COLUMN IF NOT EXISTS provider_submitted_at TIMESTAMPTZ;
ALTER TABLE projectops.agent_usage_ledger ADD COLUMN IF NOT EXISTS reported_cost_usd NUMERIC(18,8) CHECK(reported_cost_usd>=0);

-- Thin Console producer: claims create existing M8 tasks, never another executor.
ALTER TABLE projectops.agent_deployment
 ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1,
 ADD COLUMN IF NOT EXISTS playbook TEXT NOT NULL DEFAULT '';
DROP TRIGGER IF EXISTS console_version ON projectops.agent_deployment;
CREATE TRIGGER console_version BEFORE UPDATE ON projectops.agent_deployment
 FOR EACH ROW EXECUTE FUNCTION projectops.console_version();
CREATE TABLE IF NOT EXISTS projectops.agent_deployment_trigger (
 project_slug TEXT NOT NULL REFERENCES projectops.project(slug) ON DELETE CASCADE,
 deployment_id UUID NOT NULL REFERENCES projectops.agent_deployment(id) ON DELETE CASCADE,
 slot_key TEXT NOT NULL,
 request_digest TEXT NOT NULL,
 run_id UUID REFERENCES projectops.orchestration_run(id) ON DELETE SET NULL,
 state TEXT NOT NULL CHECK(state IN ('queued','blocked')),
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 PRIMARY KEY(deployment_id,slot_key)
);

-- Explicit user archive preserves private scope and immutable history for restore.
ALTER TABLE projectops.agent_memory_store ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE projectops.agent_memory_entry ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT FALSE;

-- SQL's historical medium default is not opt-in to a new provider wire parameter.
ALTER TABLE projectops.agent_profile ADD COLUMN IF NOT EXISTS effort_configured BOOLEAN NOT NULL DEFAULT FALSE;

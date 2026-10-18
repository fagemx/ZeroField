-- Durable orchestration. Every runtime attempt has a distinct fenced admission.
CREATE TABLE IF NOT EXISTS projectops.orchestration_admission_seq (
 project_slug TEXT PRIMARY KEY REFERENCES projectops.project(slug) ON DELETE CASCADE,
 last_admission BIGINT NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS projectops.orchestration_run (
 id UUID PRIMARY KEY,
 project_slug TEXT NOT NULL REFERENCES projectops.project(slug) ON DELETE CASCADE,
 created_by UUID NOT NULL,
 conversation_id BIGINT REFERENCES projectops.assistant_conversation(id) ON DELETE SET NULL,
 trigger_message_id BIGINT REFERENCES projectops.assistant_message(id) ON DELETE SET NULL,
 completion_message_id BIGINT REFERENCES projectops.assistant_message(id) ON DELETE SET NULL,
 flow_run_id UUID REFERENCES projectops.flow_run(id) ON DELETE SET NULL,
 client_request_id TEXT NOT NULL,
 request_hash TEXT NOT NULL,
 coordinator_key TEXT NOT NULL DEFAULT 'coordinator',
 objective TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','awaiting_gate','succeeded','failed','canceled')),
 max_depth INTEGER NOT NULL DEFAULT 1 CHECK(max_depth BETWEEN 1 AND 2),
 max_parallel_dispatches INTEGER NOT NULL DEFAULT 6 CHECK(max_parallel_dispatches BETWEEN 1 AND 6),
 max_tasks_per_run INTEGER NOT NULL DEFAULT 200 CHECK(max_tasks_per_run BETWEEN 1 AND 200),
 summary TEXT NOT NULL DEFAULT '',
 deadline_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 finished_at TIMESTAMPTZ,
 UNIQUE(project_slug,created_by,client_request_id), UNIQUE(id,project_slug)
);
CREATE TABLE IF NOT EXISTS projectops.orchestration_task (
 id UUID PRIMARY KEY,
 run_id UUID NOT NULL,
 project_slug TEXT NOT NULL,
 title TEXT NOT NULL,
 spec TEXT NOT NULL,
 strategy TEXT NOT NULL DEFAULT 'single' CHECK(strategy IN ('single','race','fanout_rows')),
 target_agent_key TEXT,
 label_selector JSONB NOT NULL DEFAULT '{}',
 request_scope JSONB,
 target JSONB NOT NULL DEFAULT '{}',
 depends_on JSONB NOT NULL DEFAULT '[]',
 input_snapshot JSONB NOT NULL DEFAULT '{}',
 target_snapshot JSONB,
 parent_dispatch_id UUID,
 flow_task_id UUID UNIQUE REFERENCES projectops.limb_task(id) ON DELETE SET NULL,
 write_mode TEXT NOT NULL DEFAULT 'proposal' CHECK(write_mode IN ('proposal','analysis_only')),
 max_attempts INTEGER NOT NULL DEFAULT 2 CHECK(max_attempts BETWEEN 1 AND 5),
 winning_dispatch_id UUID,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','ready','dispatched','awaiting_gate','completed','failed','canceled')),
 result_summary TEXT NOT NULL DEFAULT '',
 error TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 FOREIGN KEY(run_id,project_slug) REFERENCES projectops.orchestration_run(id,project_slug) ON DELETE CASCADE,
 UNIQUE(id,run_id,project_slug)
);
CREATE TABLE IF NOT EXISTS projectops.orchestration_dispatch (
 id UUID PRIMARY KEY,
 run_id UUID NOT NULL,
 task_id UUID NOT NULL,
 project_slug TEXT NOT NULL,
 admission_no BIGINT NOT NULL,
 agent_key TEXT NOT NULL,
 slot_key TEXT NOT NULL,
 attempt_no INTEGER NOT NULL DEFAULT 1,
 retry_count INTEGER NOT NULL DEFAULT 0,
 continuation JSONB,
 superseded_by UUID REFERENCES projectops.orchestration_dispatch(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED,
 profile_snapshot JSONB NOT NULL,
 limb_id UUID REFERENCES projectops.agent_limb(id) ON DELETE SET NULL,
 row_id TEXT NOT NULL DEFAULT '',
 chain JSONB NOT NULL DEFAULT '[]',
 status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','awaiting_gate','succeeded','failed','timeout','canceled')),
 max_attempts INTEGER NOT NULL DEFAULT 2,
 lease_owner TEXT, lease_hash TEXT, lease_until TIMESTAMPTZ,
 deadline_at TIMESTAMPTZ NOT NULL,
 tools_trace JSONB NOT NULL DEFAULT '[]',
 partial_text TEXT NOT NULL DEFAULT '',
 output_json JSONB, output_digest TEXT,
 proposal_id BIGINT REFERENCES projectops.assistant_proposal(id) ON DELETE SET NULL,
 error TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), finished_at TIMESTAMPTZ,
 FOREIGN KEY(task_id,run_id,project_slug) REFERENCES projectops.orchestration_task(id,run_id,project_slug) ON DELETE CASCADE,
 UNIQUE(project_slug,admission_no), UNIQUE(task_id,slot_key,attempt_no)
);
CREATE UNIQUE INDEX IF NOT EXISTS orchestration_current_slot ON projectops.orchestration_dispatch(task_id,slot_key)
 WHERE superseded_by IS NULL AND status IN ('queued','running','awaiting_gate','succeeded');
CREATE INDEX IF NOT EXISTS orchestration_dispatch_claim_idx ON projectops.orchestration_dispatch(project_slug,status,created_at);
CREATE TABLE IF NOT EXISTS projectops.orchestration_message (
 id BIGSERIAL PRIMARY KEY,
 run_id UUID NOT NULL REFERENCES projectops.orchestration_run(id) ON DELETE CASCADE,
 task_id UUID REFERENCES projectops.orchestration_task(id) ON DELETE CASCADE,
 dispatch_id UUID REFERENCES projectops.orchestration_dispatch(id) ON DELETE CASCADE,
 admission_no BIGINT,
 project_slug TEXT NOT NULL,
 sender TEXT NOT NULL, recipient TEXT NOT NULL,
 msg_type TEXT NOT NULL CHECK(msg_type IN ('dispatch','progress','heartbeat','question','escalation','worker_done','system')),
 subject TEXT NOT NULL DEFAULT '', body TEXT NOT NULL DEFAULT '', payload JSONB NOT NULL DEFAULT '{}',
 acked_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS orchestration_done_once ON projectops.orchestration_message(dispatch_id) WHERE msg_type='worker_done';
CREATE INDEX IF NOT EXISTS orchestration_inbox_idx ON projectops.orchestration_message(run_id,id);
CREATE TABLE IF NOT EXISTS projectops.orchestration_gate (
 id UUID PRIMARY KEY,
 run_id UUID NOT NULL REFERENCES projectops.orchestration_run(id) ON DELETE CASCADE,
 task_id UUID NOT NULL REFERENCES projectops.orchestration_task(id) ON DELETE CASCADE,
 dispatch_id UUID REFERENCES projectops.orchestration_dispatch(id) ON DELETE SET NULL,
 project_slug TEXT NOT NULL,
 gate_kind TEXT NOT NULL DEFAULT 'question' CHECK(gate_kind IN ('question','proposal_review','race_select','escalation')),
 question TEXT NOT NULL, options JSONB NOT NULL DEFAULT '[]',
 blocking_task_ids JSONB NOT NULL DEFAULT '[]', continuation JSONB,
 status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','resolved','dismissed')),
 resolution JSONB, resolution_request_id TEXT,
 resolved_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), resolved_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS orchestration_open_gate_once ON projectops.orchestration_gate(dispatch_id,gate_kind) WHERE status='open';
CREATE INDEX IF NOT EXISTS orchestration_gate_open_idx ON projectops.orchestration_gate(project_slug,status,created_at);
ALTER TABLE projectops.assistant_message ADD COLUMN IF NOT EXISTS run_id UUID REFERENCES projectops.orchestration_run(id) ON DELETE SET NULL;
ALTER TABLE projectops.assistant_message ADD COLUMN IF NOT EXISTS tool_journal JSONB NOT NULL DEFAULT '{}';
ALTER TABLE projectops.assistant_proposal
 ADD COLUMN IF NOT EXISTS dispatch_id UUID REFERENCES projectops.orchestration_dispatch(id) ON DELETE SET NULL,
 ADD COLUMN IF NOT EXISTS race_group_task_id UUID REFERENCES projectops.orchestration_task(id) ON DELETE SET NULL;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='orchestration_task_parent_fk' AND conrelid='projectops.orchestration_task'::regclass) THEN
  ALTER TABLE projectops.orchestration_task ADD CONSTRAINT orchestration_task_parent_fk
   FOREIGN KEY(parent_dispatch_id) REFERENCES projectops.orchestration_dispatch(id) ON DELETE SET NULL;
 END IF;
END $$;

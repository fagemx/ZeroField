ALTER TABLE projectops.orchestration_task ADD COLUMN IF NOT EXISTS race_agents JSONB NOT NULL DEFAULT '[]';
ALTER TABLE projectops.orchestration_dispatch
 ADD COLUMN IF NOT EXISTS executed_model TEXT,
 ADD COLUMN IF NOT EXISTS executed_provider TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS orchestration_one_race_gate
 ON projectops.orchestration_gate(task_id) WHERE gate_kind='race_select' AND status='open';
CREATE UNIQUE INDEX IF NOT EXISTS orchestration_one_pending_candidate
 ON projectops.assistant_proposal(dispatch_id) WHERE race_group_task_id IS NOT NULL AND status='pending';
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='orchestration_winner_fk' AND conrelid='projectops.orchestration_task'::regclass) THEN
  ALTER TABLE projectops.orchestration_task ADD CONSTRAINT orchestration_winner_fk
   FOREIGN KEY(winning_dispatch_id) REFERENCES projectops.orchestration_dispatch(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;
 END IF;
END $$;

-- Only explicit human POSTs use this provenance key; reading or applying model comments never dispatches work.
ALTER TABLE projectops.assistant_message ADD COLUMN IF NOT EXISTS source_ref TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS assistant_comment_request_once
 ON projectops.assistant_message(project_slug,owner_id,source_ref) WHERE role='user' AND source_ref IS NOT NULL;

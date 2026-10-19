-- API-only metadata; scripts, assets and shots remain in the collaborative tabs.
CREATE TABLE IF NOT EXISTS projectops.story_record (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    project_slug TEXT REFERENCES projectops.project(slug) ON DELETE CASCADE,
    owner_id UUID REFERENCES projectops.member(actor_id),
    data JSONB NOT NULL,
    blob BYTEA,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE projectops.story_record ADD COLUMN IF NOT EXISTS blob BYTEA;
CREATE INDEX IF NOT EXISTS story_record_kind_idx ON projectops.story_record(kind, project_slug);
CREATE INDEX IF NOT EXISTS story_record_owner_idx ON projectops.story_record(owner_id, kind);

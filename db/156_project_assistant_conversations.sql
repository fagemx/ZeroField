-- 專案助理：一段一段的對話（新對話、對話歷史）和附件。
-- 執行期由 project_docs.repository.ensure_schema 在 154 之後套用；只新增表和欄位，重跑不會改到既有資料。

-- 每個人可以有很多段對話；「目前這段」是 active_at 最新的那段（開新對話、接著舊的聊都會更新它）。
CREATE TABLE IF NOT EXISTS projectops.assistant_conversation (
  id BIGSERIAL PRIMARY KEY,
  project_slug TEXT NOT NULL,
  owner_id UUID NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  active_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS assistant_conversation_owner_idx
  ON projectops.assistant_conversation (project_slug, owner_id, active_at DESC);

ALTER TABLE projectops.assistant_message ADD COLUMN IF NOT EXISTS conversation_id BIGINT;
CREATE INDEX IF NOT EXISTS assistant_message_conversation_idx
  ON projectops.assistant_message (conversation_id, id);

-- 這個功能上線前的對話：每個人歸成一段。退回舊版又裝回來時，舊版寫的那幾句接到那個人目前這段。
INSERT INTO projectops.assistant_conversation (project_slug, owner_id, created_at, active_at)
SELECT m.project_slug, m.owner_id, min(m.created_at), max(m.created_at)
  FROM projectops.assistant_message m
 WHERE m.conversation_id IS NULL
   AND NOT EXISTS (SELECT 1 FROM projectops.assistant_conversation c
                    WHERE c.project_slug = m.project_slug AND c.owner_id = m.owner_id)
 GROUP BY m.project_slug, m.owner_id;

UPDATE projectops.assistant_message m
   SET conversation_id = (SELECT c.id FROM projectops.assistant_conversation c
                           WHERE c.project_slug = m.project_slug AND c.owner_id = m.owner_id
                           ORDER BY c.active_at DESC, c.id DESC LIMIT 1)
 WHERE m.conversation_id IS NULL;

-- 附件：送出前先上傳（message_id 還是空的），送出時綁到那一句。只有上傳的人看得到。
-- 圖片存原檔＋縮圖（畫面用）＋預覽（點開看、交給助理）；其他檔只存交給助理的文字
-- （Excel 只有結構；Word、文字檔的數字和權杖跟打字一樣先遮掉）。
CREATE TABLE IF NOT EXISTS projectops.assistant_attachment (
  id BIGSERIAL PRIMARY KEY,
  project_slug TEXT NOT NULL,
  owner_id UUID NOT NULL,
  message_id BIGINT,
  kind TEXT NOT NULL CHECK (kind IN ('image', 'sheet', 'doc', 'text')),
  name TEXT NOT NULL,
  content_type TEXT NOT NULL,
  byte_size INTEGER NOT NULL,
  data BYTEA NOT NULL,
  thumb BYTEA,
  preview BYTEA,
  extracted TEXT NOT NULL DEFAULT '',
  notes JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS assistant_attachment_message_idx
  ON projectops.assistant_attachment (message_id);
CREATE INDEX IF NOT EXISTS assistant_attachment_owner_idx
  ON projectops.assistant_attachment (project_slug, owner_id, id);

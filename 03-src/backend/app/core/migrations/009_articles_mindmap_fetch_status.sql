-- Add mindmap cache + fetch status columns to articles (ORM expects these)

ALTER TABLE articles
    ADD COLUMN IF NOT EXISTS mindmap_data JSONB;

ALTER TABLE articles
    ADD COLUMN IF NOT EXISTS fetch_status VARCHAR(20) NOT NULL DEFAULT 'completed';

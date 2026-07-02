-- Ensure articles schema is compatible with current backend model.
-- Some deployments may have an older `articles` table created before
-- `chapters` / `embedding` columns were introduced.

ALTER TABLE articles
    ADD COLUMN IF NOT EXISTS chapters JSONB;

ALTER TABLE articles
    ADD COLUMN IF NOT EXISTS embedding vector(1024);

CREATE INDEX IF NOT EXISTS idx_articles_embedding
    ON articles USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

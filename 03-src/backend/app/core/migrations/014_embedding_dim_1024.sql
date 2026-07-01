-- Switch embeddings from local bge-small-zh-v1.5 (512-dim) to
-- SiliconFlow API bge-large-zh-v1.5 (1024-dim).
-- Idempotent: only fires when column is NOT already vector(1024).
-- Old 512-dim vectors are cleared; auto-backfill regenerates them via API.
DO $$
DECLARE
    cur_type text;
BEGIN
    SELECT format_type(atttypid, atttypmod) INTO cur_type
    FROM pg_attribute
    WHERE attrelid = 'articles'::regclass
      AND attname = 'embedding'
      AND NOT attisdropped;

    IF cur_type IS DISTINCT FROM 'vector(1024)' THEN
        DROP INDEX IF EXISTS idx_articles_embedding;
        ALTER TABLE articles ALTER COLUMN embedding TYPE vector(1024) USING NULL;
        CREATE INDEX idx_articles_embedding ON articles
            USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
        RAISE NOTICE 'embedding column migrated to vector(1024); old vectors cleared for re-backfill';
    END IF;
END $$;

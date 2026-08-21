-- 019: upload/paste 全量分流 —— 云端收件暂存路径
-- external 分流时 ingest_upload/ingest_text 把原始内容落盘 data/00_staging/{job_id}/...，
-- worker 认领后经 SFTP 拉取该文件完成 capture。
ALTER TABLE ingest_jobs ADD COLUMN IF NOT EXISTS staging_file_path TEXT;

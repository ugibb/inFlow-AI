-- 022: worker 处理结果直写 articles 表 —— 内容字段入库
-- 背景：worker 重构后 SFTP 仅回传卡片 PNG/HTML，raw/parsed/chapters/asr 文件
-- 不再上云；chapters/transcript/deep-read/media_url 由 worker 各阶段直接写库，
-- 云端接口改读 DB 字段（旧行为读云端磁盘文件已失效）。
-- media_urls[0] 为平台 CDN 签名链接（会过期），前端以 article.url 原生链接兜底。
ALTER TABLE articles ADD COLUMN IF NOT EXISTS transcript JSONB;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS deep_read_html TEXT;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS media_url TEXT;

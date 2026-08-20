"""Ingest layer — Step 1 of the content pipeline.

Responsibilities:
- Accept content from any supported source (URL, file, wechat bot, paste).
- Route to the correct platform Adapter.
- Capture raw content and serialise it as a RawCapture JSON file.
- Record state in ingest_jobs; emit IngestComplete event for the parse step.

The ingest layer NEVER calls an LLM or writes to the articles table.
"""

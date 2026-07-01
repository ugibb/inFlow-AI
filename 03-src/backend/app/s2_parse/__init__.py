"""Parse layer — Step 2 of the content pipeline.

Responsibilities:
- Listen for ingest_jobs with status='captured'.
- Load the RawCapture JSON from storage.
- Select the platform parse template.
- Call the LLM to produce structured ParsedContent.
- Write the ParsedContent JSON to storage.
- Build the Wiki index (embedding + knowledge edges).
- Advance ingest_jobs.status to 'parsed'.

The parse layer NEVER writes the final articles DB record (that is display's job).
"""

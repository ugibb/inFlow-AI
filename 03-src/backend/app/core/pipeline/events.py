"""Pipeline event definitions.

Events are plain dataclasses passed between pipeline steps.  They carry only
the identifiers needed to locate the relevant database record and file paths;
actual data lives on disk (storage layer) or in the database.

Event flow:
    IngestStarted  →  IngestComplete  →  ParseComplete  →  DisplayComplete
                                      (or PipelineFailed at any point)
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class IngestStarted:
    """Emitted when the orchestrator begins capturing a new job."""
    job_id: UUID
    user_id: UUID


@dataclass(frozen=True)
class IngestComplete:
    """Emitted when a raw-capture file has been written successfully.

    The parse step listens for this event to begin LLM processing.
    """
    job_id: UUID
    user_id: UUID
    raw_file_path: str
    source_platform: str


@dataclass(frozen=True)
class ParseComplete:
    """Emitted when a parsed-content file has been written successfully.

    The display step listens for this event to write the articles DB record.
    """
    job_id: UUID
    user_id: UUID
    parsed_file_path: str


@dataclass(frozen=True)
class DisplayComplete:
    """Emitted when the article DB record has been fully written and is ready."""
    job_id: UUID
    article_id: UUID


@dataclass(frozen=True)
class PipelineFailed:
    """Emitted when any pipeline step encounters an unrecoverable error."""
    job_id: UUID
    error_stage: str   # capturing | parsing | displaying
    error_message: str

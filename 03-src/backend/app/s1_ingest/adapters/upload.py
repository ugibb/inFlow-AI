"""File upload adapter — handles PDF, DOCX, EPUB, and other document files.

Unlike URL-based adapters, this adapter accepts pre-loaded bytes rather than
fetching from a remote URL.  The ingest orchestrator calls fetch_from_bytes()
directly when handling multipart/form-data uploads.

Conversion chain:
    PDF / DOCX / EPUB / TXT  →  MarkItDown  →  raw_text (Markdown)

MarkItDown handles: .pdf, .docx, .pptx, .xlsx, .epub, .html, .txt, .md
For other types we fall back to raw text extraction.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional
from uuid import UUID

from app.s1_ingest.adapters.base import AbstractAdapter, AdapterError
from app.s1_ingest.schema import RawCapture, RawMeta, RawContent

logger = logging.getLogger("inFlow.ingest.adapters.upload")

_SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".pptx", ".ppt",
    ".xlsx", ".xls", ".epub", ".html", ".htm",
    ".txt", ".md", ".markdown",
}


class UploadAdapter(AbstractAdapter):
    """Adapter for local file uploads — invoked directly, not via URL routing."""

    platform = "upload"
    version = "1.0.0"

    def can_handle(self, url: str) -> bool:
        # Upload adapter is invoked directly by the orchestrator, never by URL routing.
        return False

    async def fetch(
        self,
        url: str,
        *,
        user_id: UUID,
        capture_method: str = "upload",
        extra_context: Optional[dict] = None,
    ) -> RawCapture:
        raise AdapterError(
            "UploadAdapter.fetch() requires bytes — use fetch_from_bytes() instead.",
            platform=self.platform,
            url=url,
        )

    async def fetch_from_bytes(
        self,
        *,
        filename: str,
        content: bytes,
        user_id: UUID,
        mime_type: Optional[str] = None,
    ) -> RawCapture:
        """Convert an uploaded file to RawCapture.

        Args:
            filename:  Original filename (used for extension detection).
            content:   Raw file bytes.
            user_id:   ID of the uploading user.
            mime_type: Optional MIME type hint.

        Returns:
            RawCapture with content_type='document' and raw_text populated.
        """
        ext = Path(filename).suffix.lower()
        logger.info(
            "UploadAdapter: processing %s (%d bytes)", filename, len(content)
        )

        raw_text = await self._convert_to_text(content, ext, filename)

        meta = RawMeta(
            source_platform=self.platform,
            capture_method="upload",
            original_url=None,
            adapter_version=self.version,
            user_id=user_id,
        )

        raw = RawContent(
            title=Path(filename).stem,
            content_type="document",
            raw_text=raw_text,
            extra={"filename": filename, "mime_type": mime_type or "", "ext": ext},
        )

        return RawCapture(meta=meta, raw=raw)

    async def _convert_to_text(self, content: bytes, ext: str, filename: str) -> str:
        """Convert file bytes to Markdown text via MarkItDown, with fallbacks."""
        if ext not in _SUPPORTED_EXTENSIONS:
            logger.warning(
                "UploadAdapter: unsupported extension %s, returning raw UTF-8 decode",
                ext,
            )
            return content.decode("utf-8", errors="replace")

        # Write to a temp file so MarkItDown can use file-based APIs.
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            return await self._markitdown_convert(tmp_path)
        except Exception as exc:
            logger.warning(
                "UploadAdapter: MarkItDown failed for %s: %s — falling back to raw decode",
                filename,
                exc,
            )
            return content.decode("utf-8", errors="replace")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    @staticmethod
    async def _markitdown_convert(path: str) -> str:
        """Run MarkItDown conversion in a thread to avoid blocking the event loop."""
        import asyncio

        def _convert() -> str:
            from markitdown import MarkItDown
            md = MarkItDown()
            result = md.convert(path)
            return result.text_content or ""

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _convert)

    def get_parse_template_id(self) -> str:
        return "document"

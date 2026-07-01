"""Thin wrapper: ingest layer file storage helpers.

Re-exports default_storage for convenience; ingest-specific helpers go here.
"""
from app.core.shared.storage import default_storage

__all__ = ["default_storage"]

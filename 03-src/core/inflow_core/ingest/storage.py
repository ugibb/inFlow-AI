"""Thin wrapper: ingest layer file storage helpers.

Re-exports default_storage for convenience; ingest-specific helpers go here.
"""
from inflow_core.core.shared.storage import default_storage

__all__ = ["default_storage"]

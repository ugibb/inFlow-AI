"""In-memory progress store for long-running background tasks.

Keyed by a string ID (article_id). Single-process, no persistence.
"""
from __future__ import annotations

_store: dict[str, str] = {}


def set_progress(key: str, msg: str) -> None:
    _store[key] = msg


def get_progress(key: str) -> str | None:
    return _store.get(key)


def clear_progress(key: str) -> None:
    _store.pop(key, None)

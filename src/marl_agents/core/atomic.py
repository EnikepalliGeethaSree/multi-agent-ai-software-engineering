"""Atomic file writes that are safe when several threads or agents write the same entry."""

from __future__ import annotations

import os
import threading
from pathlib import Path


def write_atomic(path: Path, data: bytes) -> None:
    """Write `data` to `path` through a temporary file unique to this process and thread.

    Content-addressed caches (static analysis, LLM replies) can be written for the same key by two
    agents at once (the orchestrator runs them in parallel). Each writer gets its own temporary
    file. On Windows a rename onto a file another writer is replacing can be refused; the entry is
    then already there with the same content, so the late writer just discards its copy.
    """
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_bytes(data)
    try:
        tmp.replace(path)
    except PermissionError:
        tmp.unlink(missing_ok=True)
        if not path.exists():
            raise

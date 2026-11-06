"""Repository intake (ZIP / directory / snippet), safe extraction, filtering. Never runs code."""

from marl_agents.ingestion.loader import (
    IngestionError,
    load_directory,
    load_files,
    load_repository,
    load_snippet,
    load_zip,
)
from marl_agents.ingestion.models import FileKind, Repository, SourceFile
from marl_agents.ingestion.safe_zip import UnsafeArchiveError, safe_extract_zip

__all__ = [
    "FileKind",
    "IngestionError",
    "Repository",
    "SourceFile",
    "UnsafeArchiveError",
    "load_directory",
    "load_files",
    "load_repository",
    "load_snippet",
    "load_zip",
    "safe_extract_zip",
]

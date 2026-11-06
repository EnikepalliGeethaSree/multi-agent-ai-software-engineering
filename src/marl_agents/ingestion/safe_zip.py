"""Safe extraction of untrusted ZIP archives (zip-slip, symlinks, zip bombs)."""

from __future__ import annotations

import logging
import stat
import zipfile
from pathlib import Path, PurePosixPath

from marl_agents.config import IngestionSettings

logger = logging.getLogger(__name__)

# A compression ratio above this for a single member is treated as a zip bomb.
MAX_COMPRESSION_RATIO = 200
_CHUNK = 1024 * 1024


class UnsafeArchiveError(ValueError):
    """The archive violates a safety rule and was not (fully) extracted."""


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def _safe_member_path(name: str) -> PurePosixPath | None:
    """Return a safe relative path for a member name, or None if it must be rejected."""
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
        return None
    parts = [p for p in PurePosixPath(normalized).parts if p not in ("", ".")]
    if any(p == ".." for p in parts) or not parts:
        return None
    return PurePosixPath(*parts)


def safe_extract_zip(zip_path: Path, dest: Path, limits: IngestionSettings) -> Path:
    """Extract `zip_path` into `dest` enforcing all safety limits.

    Returns the directory that should be treated as the repository root: if the archive
    contains a single top-level folder (the usual GitHub download layout) that folder is returned.
    """
    if zip_path.stat().st_size > limits.max_zip_bytes:
        raise UnsafeArchiveError(
            f"Archive is {zip_path.stat().st_size} bytes; limit is {limits.max_zip_bytes}"
        )
    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()

    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise UnsafeArchiveError(f"Not a valid ZIP archive: {exc}") from exc

    with archive:
        members = archive.infolist()
        file_members = [m for m in members if not m.is_dir()]
        if len(file_members) > limits.max_files:
            raise UnsafeArchiveError(
                f"Archive has {len(file_members)} files; limit is {limits.max_files}"
            )
        declared_total = sum(m.file_size for m in file_members)
        if declared_total > limits.max_uncompressed_bytes:
            raise UnsafeArchiveError(
                f"Archive expands to {declared_total} bytes; limit is "
                f"{limits.max_uncompressed_bytes}"
            )

        written_total = 0
        for member in file_members:
            rel = _safe_member_path(member.filename)
            if rel is None:
                raise UnsafeArchiveError(f"Unsafe path in archive: {member.filename!r}")
            if _is_symlink(member):
                logger.warning("Skipping symlink in archive: %s", member.filename)
                continue
            if member.file_size > limits.max_file_bytes:
                # Oversized files are skipped, not fatal: a large data file shouldn't block review.
                logger.info("Skipping oversized member %s (%d bytes)", rel, member.file_size)
                continue
            if (
                member.compress_size > 0
                and member.file_size / member.compress_size > MAX_COMPRESSION_RATIO
            ):
                raise UnsafeArchiveError(f"Suspicious compression ratio for {member.filename!r}")

            target = (dest_resolved / Path(*rel.parts)).resolve()
            if not target.is_relative_to(dest_resolved):
                raise UnsafeArchiveError(f"Path escapes extraction dir: {member.filename!r}")
            target.parent.mkdir(parents=True, exist_ok=True)

            # Stream with a hard cap: declared sizes in the header can lie.
            written = 0
            with archive.open(member) as src, target.open("wb") as out:
                while chunk := src.read(_CHUNK):
                    written += len(chunk)
                    written_total += len(chunk)
                    if written > limits.max_file_bytes:
                        raise UnsafeArchiveError(f"{member.filename!r} exceeds its declared size")
                    if written_total > limits.max_uncompressed_bytes:
                        raise UnsafeArchiveError("Archive exceeds the uncompressed size limit")
                    out.write(chunk)

    top_level = [p for p in dest_resolved.iterdir()]
    if len(top_level) == 1 and top_level[0].is_dir():
        return top_level[0]
    return dest_resolved

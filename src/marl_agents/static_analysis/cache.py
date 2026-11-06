"""Results of deterministic analyzers, reused when neither the code nor the analyzer changed.

The key covers the repository's content hash, the analyzer's own source, the shared rule table, the
files and the diff scope. The secrets analyzer is never cached: its findings hold credentials before
redaction. Outputs with errors are not cached either, so a failed tool run is retried.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
from pathlib import Path

from pydantic import TypeAdapter

from marl_agents.core.schemas import Finding
from marl_agents.ingestion.models import Repository
from marl_agents.static_analysis import rules
from marl_agents.static_analysis.base import AnalyzerOutput, Scope, StaticAnalyzer

logger = logging.getLogger(__name__)

NEVER_CACHED = {"secrets"}
_FINDINGS = TypeAdapter(list[Finding])


def _source_hash(analyzer: StaticAnalyzer) -> str:
    digest = hashlib.sha256()
    for obj in (type(analyzer), rules):
        digest.update(Path(inspect.getfile(obj)).read_bytes())
    return digest.hexdigest()


class AnalysisCache:
    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)
        self.hits = 0

    @staticmethod
    def _key(
        repo: Repository, analyzer: StaticAnalyzer, files: list[str], scope: Scope | None
    ) -> str:
        parts = [repo.repo_id, analyzer.name, _source_hash(analyzer), sorted(files), scope]
        return hashlib.sha256(json.dumps(parts, sort_keys=True).encode("utf-8")).hexdigest()

    def get(
        self, repo: Repository, analyzer: StaticAnalyzer, files: list[str], scope: Scope | None
    ) -> AnalyzerOutput | None:
        if analyzer.name in NEVER_CACHED:
            return None
        path = self.dir / f"{self._key(repo, analyzer, files, scope)}.json"
        if not path.is_file():
            return None
        try:
            findings = _FINDINGS.validate_json(path.read_bytes())
        except (OSError, ValueError):
            logger.warning("Ignoring unreadable analysis cache entry %s", path.name)
            return None
        self.hits += 1
        return AnalyzerOutput(findings=findings)

    def put(
        self,
        repo: Repository,
        analyzer: StaticAnalyzer,
        files: list[str],
        scope: Scope | None,
        output: AnalyzerOutput,
    ) -> None:
        if analyzer.name in NEVER_CACHED or output.errors or output.skipped:
            return
        path = self.dir / f"{self._key(repo, analyzer, files, scope)}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(_FINDINGS.dump_json(output.findings))
        tmp.replace(path)

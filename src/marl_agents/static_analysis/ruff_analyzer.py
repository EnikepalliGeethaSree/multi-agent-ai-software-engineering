"""Ruff (pyflakes, bugbear, bandit rules, ...) run as a sandboxed subprocess on the files."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

from marl_agents.core.fixes import TextEdit, apply_edits, make_fix
from marl_agents.core.schemas import FindingSource, SuggestedFix
from marl_agents.ingestion.models import FileKind, Repository
from marl_agents.parsing.repo_index import RepoIndex
from marl_agents.static_analysis.base import (
    AnalyzerOutput,
    Scope,
    StaticAnalyzer,
    line_evidence,
    make_finding,
)
from marl_agents.static_analysis.rules import (
    RUFF_IGNORE,
    RUFF_SELECT,
    RUFF_TEST_IGNORE_PREFIXES,
    SYNTAX_ERROR,
    lookup,
)

logger = logging.getLogger(__name__)

_BATCH = 150  # keep the command line well under the Windows 32k-character limit


def find_ruff() -> str | None:
    try:
        from ruff.__main__ import find_ruff_bin

        return str(find_ruff_bin())
    except (ImportError, FileNotFoundError):
        return shutil.which("ruff")


class RuffAnalyzer(StaticAnalyzer):
    name = "ruff"

    def __init__(
        self,
        select: list[str] | None = None,
        ignore: list[str] | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.select = select or RUFF_SELECT
        self.ignore = ignore or RUFF_IGNORE
        self.timeout = timeout
        self.binary = find_ruff()

    def _command(self, files: list[str]) -> list[str]:
        assert self.binary is not None
        return [
            self.binary,
            "check",
            "--isolated",  # ignore any config in the analyzed repo
            "--no-cache",
            "--no-fix",
            "--exit-zero",
            "--output-format",
            "json",
            "--select",
            ",".join(self.select),
            "--ignore",
            ",".join(self.ignore),
            "--",
            *files,
        ]

    def analyze(
        self, repo: Repository, index: RepoIndex, files: list[str], scope: Scope | None = None
    ) -> AnalyzerOutput:
        out = AnalyzerOutput()
        py_files = [f for f in files if repo.has(f) and repo.by_path[f].language == "python"]
        if not py_files:
            return out
        if self.binary is None:
            out.skipped = True
            out.errors.append("ruff is not installed; skipping ruff analysis")
            return out

        for start in range(0, len(py_files), _BATCH):
            batch = py_files[start : start + _BATCH]
            try:
                proc = subprocess.run(  # noqa: S603 - fixed binary, argument list, no shell
                    self._command(batch),
                    cwd=repo.root,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=self.timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                out.errors.append(f"ruff timed out on batch starting at {batch[0]}")
                continue
            if proc.returncode not in (0, 1):
                out.errors.append(f"ruff failed ({proc.returncode}): {proc.stderr.strip()[:300]}")
                continue
            try:
                items = json.loads(proc.stdout or "[]")
            except json.JSONDecodeError:
                out.errors.append("ruff produced unparseable output")
                continue
            syntax_seen: set[str] = set()
            for item in items:
                finding = self._to_finding(repo, index, item)
                if finding is None:
                    continue
                if finding.rule_id == "E999":
                    # Only the first syntax error per file is real; later ones cascade from it.
                    if finding.file in syntax_seen:
                        continue
                    syntax_seen.add(finding.file)
                out.findings.append(finding)
        return out

    def _to_finding(self, repo: Repository, index: RepoIndex, item: dict[str, object]):  # type: ignore[no-untyped-def]
        filename = str(item.get("filename", ""))
        try:
            rel = Path(filename).resolve().relative_to(repo.root).as_posix()
        except ValueError:
            rel = filename.replace("\\", "/")
        if not repo.has(rel):
            return None
        code = item.get("code")
        message = str(item.get("message", ""))
        # Ruff reports syntax errors as code None (old), "E999" (older) or "invalid-syntax" (new).
        is_syntax = (
            code in (None, "invalid-syntax")
            or item.get("name") == "invalid-syntax"
            or str(code).startswith("E9")
            or "SyntaxError" in message
        )
        rule_id = "E999" if is_syntax else str(code)
        if is_syntax:
            message = f"Syntax error: {message.removeprefix('SyntaxError: ')}"
        if repo.by_path[rel].kind is FileKind.TEST and rule_id.startswith(
            RUFF_TEST_IGNORE_PREFIXES
        ):
            return None
        spec = SYNTAX_ERROR if is_syntax else lookup(rule_id)

        location = item.get("location") or {}
        end_location = item.get("end_location") or location
        start_line = int(location.get("row", 1)) if isinstance(location, dict) else 1
        end_line = (
            int(end_location.get("row", start_line))
            if isinstance(end_location, dict)
            else start_line
        )
        n_lines = max(repo.line_count(rel), 1)
        start_line = min(max(start_line, 1), n_lines)
        end_line = min(max(end_line, start_line), n_lines)

        module = index.modules.get(rel)
        sym = module.symbol_at(start_line) if module else None
        finding = make_finding(
            source=FindingSource.RUFF,
            file=rel,
            start_line=start_line,
            end_line=end_line,
            category=spec.category,
            severity=spec.severity,
            title=f"{rule_id}: {message}"[:200],
            description=message,
            confidence=spec.confidence,
            evidence=[line_evidence(repo, rel, start_line, end_line)],
            recommendation=spec.recommendation,
            test_recommendation=spec.test_recommendation,
            rule_id=rule_id,
            cwe=spec.cwe,
            symbol=sym.qualname if sym else None,
        )
        fix = self._autofix(repo, rel, item.get("fix"))
        return finding.model_copy(update={"suggested_fix": fix}) if fix else finding

    @staticmethod
    def _autofix(repo: Repository, rel: str, fix: object) -> SuggestedFix | None:
        """Ruff's own autofix as a suggested fix. 'safe' fixes are guaranteed by Ruff not to change
        behaviour, so they count as verified; 'unsafe' ones need human review."""
        if not isinstance(fix, dict) or fix.get("applicability") not in ("safe", "unsafe"):
            return None
        edits = []
        for e in fix.get("edits") or []:
            try:
                loc, end = e["location"], e["end_location"]
                edits.append(
                    TextEdit(loc["row"], loc["column"], end["row"], end["column"], e["content"])
                )
            except (KeyError, TypeError):
                return None
        if not edits:
            return None
        old = repo.read_text(rel)
        safe = fix["applicability"] == "safe"
        checks = [
            f"Ruff autofix: {fix.get('message') or 'suggested edit'}",
            "safe: behaviour-preserving" if safe else "unsafe: may change behaviour, review it",
        ]
        return make_fix(rel, old, apply_edits(old, edits), "ruff", verified=safe, checks=checks)

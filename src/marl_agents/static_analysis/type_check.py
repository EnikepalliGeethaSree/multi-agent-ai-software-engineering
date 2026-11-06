"""Cross-file type checking with mypy (subprocess, never executes the analyzed code).

Catches contract mismatches across files, e.g. a caller passing the wrong type, using an attribute
that the returned type does not have, or treating an Optional result as always present.

Safety: mypy only parses and type-checks. It runs with OUR empty config file, so plugins declared in
the analyzed repository's mypy/pyproject config (which would import code) are never loaded; the
cache goes to a temporary directory outside the repository.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
import tempfile
from importlib import util
from pathlib import Path

from marl_agents.core.schemas import Category, FindingSource, Severity
from marl_agents.ingestion.models import FileKind, Repository
from marl_agents.parsing.repo_index import RepoIndex
from marl_agents.static_analysis.base import (
    AnalyzerOutput,
    Scope,
    StaticAnalyzer,
    line_evidence,
    make_finding,
)

logger = logging.getLogger(__name__)

_LINE = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+):(?:(?P<col>\d+):)? error: (?P<msg>.*?)\s+\[(?P<code>[a-z-]+)\]$"
)
# Error codes worth a reviewer's attention (others are mostly noise on unannotated code).
CODES: dict[str, tuple[Severity, float, str]] = {
    "call-arg": (Severity.HIGH, 0.85, "Pass the arguments the function actually accepts."),
    "arg-type": (Severity.MEDIUM, 0.7, "Pass a value of the expected type, or convert it first."),
    "return-value": (Severity.MEDIUM, 0.7, "Return the declared type, or fix the annotation."),
    "union-attr": (
        Severity.MEDIUM,
        0.7,
        "Handle the None (or other union member) case before using the value.",
    ),
    "attr-defined": (Severity.MEDIUM, 0.55, "Use an attribute that exists on this type."),
    "index": (Severity.MEDIUM, 0.6, "Index the value with a supported key type."),
    "operator": (Severity.MEDIUM, 0.6, "Use operand types the operator supports."),
    "func-returns-value": (
        Severity.MEDIUM,
        0.75,
        "This function returns None; do not use its result.",
    ),
    "call-overload": (Severity.MEDIUM, 0.6, "Call with arguments matching one of the overloads."),
}


def mypy_available() -> bool:
    return util.find_spec("mypy") is not None


class TypeCheckAnalyzer(StaticAnalyzer):
    name = "mypy"

    def __init__(self, timeout: float = 120.0, extra_files: list[str] | None = None) -> None:
        self.timeout = timeout
        self.extra_files = extra_files or []

    def analyze(
        self, repo: Repository, index: RepoIndex, files: list[str], scope: Scope | None = None
    ) -> AnalyzerOutput:
        out = AnalyzerOutput()
        targets = sorted(
            {
                f
                for f in [*files, *self.extra_files]
                if repo.has(f) and f.endswith(".py") and repo.by_path[f].kind is FileKind.CODE
            }
        )
        if not targets:
            return out
        if not mypy_available():
            out.skipped = True
            out.errors.append("mypy is not installed; skipping type checking")
            return out
        with tempfile.TemporaryDirectory(prefix="marl_mypy_") as tmp:
            config = Path(tmp) / "mypy.ini"
            config.write_text("[mypy]\n", encoding="utf-8")
            cmd = [
                sys.executable,
                "-m",
                "mypy",
                "--config-file",
                str(config),
                "--cache-dir",
                str(Path(tmp) / "cache"),
                "--ignore-missing-imports",
                "--follow-imports=silent",
                "--check-untyped-defs",
                "--show-error-codes",
                "--no-error-summary",
                "--show-column-numbers",
                "--hide-error-context",
                "--no-pretty",
                "--explicit-package-bases",
                "--",
                *targets,
            ]
            try:
                proc = subprocess.run(  # noqa: S603 - our interpreter, argument list, no shell
                    cmd,
                    cwd=repo.root,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=self.timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                out.errors.append("mypy timed out")
                return out
        if proc.returncode not in (0, 1):
            out.errors.append(f"mypy failed ({proc.returncode}): {proc.stderr.strip()[:300]}")
            return out
        for raw in proc.stdout.splitlines():
            m = _LINE.match(raw.strip())
            if not m or m["code"] not in CODES:
                continue
            rel = m["file"].replace("\\", "/")
            if not repo.has(rel):
                continue
            line = min(max(int(m["line"]), 1), max(repo.line_count(rel), 1))
            severity, confidence, fix = CODES[m["code"]]
            module = index.modules.get(rel)
            sym = module.symbol_at(line) if module else None
            out.findings.append(
                make_finding(
                    source=FindingSource.MYPY,
                    file=rel,
                    start_line=line,
                    end_line=line,
                    category=Category.BUG,
                    severity=severity,
                    title=f"Type error: {m['msg']}"[:200],
                    description=f"mypy [{m['code']}]: {m['msg']}",
                    confidence=confidence,
                    evidence=[line_evidence(repo, rel, line, line)],
                    recommendation=fix,
                    rule_id=f"TYPE-{m['code']}",
                    symbol=sym.qualname if sym else None,
                )
            )
        return out

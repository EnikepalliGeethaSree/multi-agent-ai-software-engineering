"""LLM-written fixes, verified before they are shown.

For each important finding without a fix, the LLM proposes a replacement for a block of lines inside
the enclosing function. The patch is only attached when:

1. it stays inside the allowed region and the patched file still parses;
2. re-running the static analyzers on the patched file reports NO new issue in that region;
3. (for findings a static tool detected) the original issue is gone -> `verified = True`.

LLM-only findings cannot be re-detected mechanically, so their fixes are "checked" (1 + 2), not
"verified". Nothing is ever applied to the analyzed repository.
"""

from __future__ import annotations

import ast
import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, field_validator

from marl_agents.agents.code_review.prompts import load_prompt
from marl_agents.config import IngestionSettings
from marl_agents.core.fixes import make_fix, replace_lines
from marl_agents.core.schemas import Category, Finding, FindingSource, Severity
from marl_agents.findings.redaction import is_secret_finding
from marl_agents.ingestion import Repository, load_files
from marl_agents.llm.base import LLMError, LLMProvider, Message, Usage
from marl_agents.parsing.repo_index import RepoIndex
from marl_agents.static_analysis import AstChecksAnalyzer, RuffAnalyzer, SecretsAnalyzer

logger = logging.getLogger(__name__)

MAX_REGION_LINES = 80
REGION_PADDING = 10
SKIP_CATEGORIES = {Category.TESTING, Category.DOCUMENTATION}
TOOL_SOURCES = {FindingSource.RUFF, FindingSource.AST, FindingSource.RADON, FindingSource.MYPY}


class FixProposal(BaseModel):
    start_line: int
    end_line: int
    replacement: str
    explanation: str = ""

    @field_validator("replacement", mode="before")
    @classmethod
    def _strip_fence(cls, v: object) -> str:
        text = str(v)
        if text.lstrip().startswith("```"):
            lines = text.strip().splitlines()[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines)
        return text


@dataclass
class FixStats:
    attempted: int = 0
    attached: int = 0
    verified: int = 0
    rejected: Counter[str] = field(default_factory=Counter)

    def as_dict(self) -> dict[str, object]:
        return {
            "attempted": self.attempted,
            "attached": self.attached,
            "verified": self.verified,
            "rejected": dict(self.rejected),
        }


def _issue_keys(findings: list[Finding], start: int, end: int) -> Counter[str]:
    return Counter(
        f.rule_id or f.title for f in findings if f.start_line <= end and start <= f.end_line
    )


class FixGenerator:
    def __init__(
        self,
        llm: LLMProvider,
        repo: Repository,
        index: RepoIndex,
        ingestion: IngestionSettings,
        max_fixes: int = 8,
        usage: Usage | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self.llm = llm
        self.repo = repo
        self.index = index
        self.ingestion = ingestion
        self.max_fixes = max_fixes
        self.usage = usage
        self.progress = progress or (lambda _m: None)
        self.stats = FixStats()
        self._baseline: dict[str, list[Finding]] = {}

    # ---- static re-analysis of one file --------------------------------------------------------

    def _analyze_text(self, path: str, text: str) -> list[Finding]:
        tmp = load_files({path: text}, self.ingestion)
        try:
            idx = RepoIndex.build(tmp)
            out: list[Finding] = []
            for analyzer in (RuffAnalyzer(), AstChecksAnalyzer(), SecretsAnalyzer()):
                out.extend(analyzer.analyze(tmp, idx, [path]).findings)
            return out
        finally:
            tmp.cleanup()

    def _baseline_for(self, path: str) -> list[Finding]:
        if path not in self._baseline:
            self._baseline[path] = self._analyze_text(path, self.repo.read_text(path))
        return self._baseline[path]

    # ---- region & prompt -----------------------------------------------------------------------

    def _region(self, f: Finding) -> tuple[int, int]:
        n = self.repo.line_count(f.file)
        module = self.index.modules.get(f.file)
        sym = module.symbol_at(f.start_line) if module else None
        if sym is not None and sym.line_span <= MAX_REGION_LINES:
            return sym.start_line, min(sym.end_line, n)
        return max(1, f.start_line - REGION_PADDING), min(n, f.end_line + REGION_PADDING)

    def _numbered(self, path: str, start: int, end: int) -> str:
        lines = self.repo.lines(path)
        return "\n".join(f"{i:>5} | {lines[i - 1]}" for i in range(start, end + 1))

    # ---- main --------------------------------------------------------------------------------

    def candidates(self, findings: list[Finding]) -> list[Finding]:
        return [
            f
            for f in findings
            if f.suggested_fix is None
            and f.severity.rank >= Severity.MEDIUM.rank
            and f.category not in SKIP_CATEGORIES
            and not is_secret_finding(f)  # a diff would re-publish the secret
            and f.file.endswith(".py")
            and self.repo.has(f.file)
        ][: self.max_fixes]

    def run(self, findings: list[Finding]) -> list[Finding]:
        candidates = self.candidates(findings)
        chosen = {id(f) for f in candidates}
        if candidates:
            self.progress(f"suggesting fixes for {len(candidates)} finding(s)")
        out = []
        done = 0
        for f in findings:
            if id(f) not in chosen:
                out.append(f)
                continue
            fixed = self._fix_one(f)
            done += 1
            fix = fixed.suggested_fix
            verdict = "no fix" if fix is None else "verified" if fix.verified else "suggested"
            self.progress(f"fix {done}/{len(candidates)}: {f.file}:{f.start_line} -> {verdict}")
            out.append(fixed)
        return out

    def _fix_one(self, f: Finding) -> Finding:
        self.stats.attempted += 1
        start, end = self._region(f)
        prompt = load_prompt("fix").render(
            file=f.file,
            title=f.title,
            category=f.category.value,
            severity=f.severity.value,
            description=f.description,
            recommendation=f.recommendation or "(none)",
            start_line=start,
            end_line=end,
            numbered_code=self._numbered(f.file, start, end),
        )
        messages = [
            Message(role="system", content="You fix code review findings. Reply with JSON only."),
            Message(role="user", content=prompt),
        ]
        try:
            proposal = self.llm.generate_structured(messages, FixProposal, usage=self.usage)
        except LLMError as exc:
            self.stats.rejected["llm_error"] += 1
            logger.info("fix generation failed for %s: %s", f.title, exc)
            return f

        p_start, p_end = proposal.start_line, proposal.end_line
        if not (start <= p_start <= p_end + 1 and p_end <= end):
            self.stats.rejected["outside_region"] += 1
            return f
        old_text = self.repo.read_text(f.file)
        new_text = replace_lines(old_text, p_start, p_end, proposal.replacement)
        try:
            ast.parse(new_text)
        except SyntaxError:
            self.stats.rejected["does_not_parse"] += 1
            return f

        # Re-analyze: no new issue in the edited region; tool-detected issue must be gone.
        shift = len(proposal.replacement.splitlines()) - (p_end - p_start + 1)
        before = _issue_keys(self._baseline_for(f.file), start, end)
        after_findings = self._analyze_text(f.file, new_text)
        after = _issue_keys(after_findings, start, end + shift)
        introduced = after - before
        if introduced:
            self.stats.rejected["introduces_issues"] += 1
            logger.info("fix for %s rejected, introduces %s", f.title, dict(introduced))
            return f
        checks = ["patched file parses", "no new static-analysis issue in the edited code"]
        verified = False
        tool_found = (
            bool(set(f.sources) & TOOL_SOURCES)
            and f.rule_id
            and not f.rule_id.startswith(("IMPACT", "TEST-"))
        )
        if tool_found:
            if before.get(f.rule_id or "", 0) and not after.get(f.rule_id or "", 0):
                verified = True
                checks.append(f"original issue ({f.rule_id}) no longer detected")
            else:
                self.stats.rejected["issue_still_present"] += 1
                return f
        fix = make_fix(f.file, old_text, new_text, "llm", verified=verified, checks=checks)
        if fix is None:
            self.stats.rejected["no_change"] += 1
            return f
        if proposal.explanation:
            fix.checks.insert(0, proposal.explanation.strip())
        self.stats.attached += 1
        self.stats.verified += int(verified)
        return f.model_copy(update={"suggested_fix": fix})

"""Check every finding against the real repository before it can reach a report.

LLM findings must cite a real file, real lines, and evidence that literally appears in the file.
Mis-located findings whose evidence is found nearby are repaired; the rest are rejected.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import StrEnum

from marl_agents.core.schemas import Finding, FindingSource, Severity
from marl_agents.ingestion.models import Repository

logger = logging.getLogger(__name__)

_WS = re.compile(r"\s+")
REPAIR_WINDOW = 15  # lines: how far a mis-cited location may be moved to where the evidence is
MIN_EVIDENCE_CHARS = 6


class ValidationStatus(StrEnum):
    VALID = "valid"
    REPAIRED = "repaired"
    REJECTED = "rejected"


class RejectReason(StrEnum):
    UNKNOWN_FILE = "unknown_file"
    LINE_OUT_OF_RANGE = "line_out_of_range"
    NO_EVIDENCE = "no_evidence"
    EVIDENCE_NOT_FOUND = "evidence_not_found"
    OUTSIDE_SCOPE = "outside_scope"


@dataclass
class ValidationOutcome:
    status: ValidationStatus
    finding: Finding | None
    reason: RejectReason | None = None
    detail: str = ""


def normalize(text: str) -> str:
    return _WS.sub(" ", text).strip()


def _strip_line_numbers(snippet: str) -> str:
    """LLMs often copy the '  42 | ' gutter we show them; remove it before matching."""
    return "\n".join(re.sub(r"^\s*[>+*]?\s*\d+\s*[|:]\s?", "", ln) for ln in snippet.splitlines())


def _evidence_lines(snippet: str) -> list[str]:
    cleaned = _strip_line_numbers(snippet).strip().strip("`")
    if cleaned.startswith(("python\n", "py\n")):
        cleaned = cleaned.split("\n", 1)[1]
    lines = [normalize(ln) for ln in cleaned.splitlines()]
    return [ln for ln in lines if ln and ln not in {"...", "…"}]


def locate_evidence(file_lines: list[str], snippet: str) -> list[tuple[int, int]]:
    """All (start, end) 1-based line ranges where the snippet's lines appear consecutively.

    Matching is whitespace-normalized; the first/last snippet lines may be partial.
    """
    ev = _evidence_lines(snippet)
    if not ev or sum(len(x) for x in ev) < MIN_EVIDENCE_CHARS:
        return []
    norm = [normalize(ln) for ln in file_lines]
    hits: list[tuple[int, int]] = []
    n = len(ev)
    for i in range(len(norm) - n + 1):
        ok = True
        for j, piece in enumerate(ev):
            line = norm[i + j]
            if n == 1:
                ok = piece in line
            elif j == 0:
                ok = line.endswith(piece) or piece in line
            elif j == n - 1:
                ok = line.startswith(piece) or piece in line
            else:
                ok = piece == line
            if not ok:
                break
        if ok:
            hits.append((i + 1, i + n))
    return hits


class FindingValidator:
    """Validates findings for one repository.

    `scope` optionally restricts accepted findings to line ranges per file (PR / diff review).
    """

    def __init__(
        self,
        repo: Repository,
        require_llm_evidence: bool = True,
        scope: dict[str, list[tuple[int, int]]] | None = None,
        scope_slack: int = 3,
    ) -> None:
        self.repo = repo
        self.require_llm_evidence = require_llm_evidence
        self.scope = scope
        self.scope_slack = scope_slack

    def validate(self, finding: Finding) -> ValidationOutcome:
        notes = list(finding.notes)
        path = self.repo.resolve_path(finding.file)
        if path is None:
            return ValidationOutcome(
                ValidationStatus.REJECTED, None, RejectReason.UNKNOWN_FILE, finding.file
            )
        if path != finding.file:
            notes.append(f"path normalized from {finding.file!r}")

        lines = self.repo.lines(path)
        n_lines = max(len(lines), 1)
        start, end = finding.start_line, finding.end_line
        is_llm = FindingSource.LLM in finding.sources
        status = ValidationStatus.VALID if path == finding.file else ValidationStatus.REPAIRED

        if start > n_lines:
            if not (is_llm and finding.evidence):
                return ValidationOutcome(
                    ValidationStatus.REJECTED,
                    None,
                    RejectReason.LINE_OUT_OF_RANGE,
                    f"{path}:{start} > {n_lines}",
                )
            start = end = n_lines  # let evidence relocation below try to fix it
        if end > n_lines:
            end = n_lines
            notes.append("end_line clamped to file length")
            status = ValidationStatus.REPAIRED

        evidence = list(finding.evidence)
        if is_llm:
            verified: list[str] = []
            best_range: tuple[int, int] | None = None
            for snippet in finding.evidence:
                hits = locate_evidence(lines, snippet)
                if not hits:
                    continue
                verified.append(snippet)
                inside = [h for h in hits if h[0] <= end and start <= h[1]]
                if inside:
                    best_range = best_range or (start, end)
                    continue
                # Relocate only when unambiguous: exactly one match near the cited lines, or exactly
                # one match in the whole file. Several candidates = we would be guessing.
                near = [h for h in hits if abs(h[0] - start) <= REPAIR_WINDOW]
                if len(near) == 1:
                    candidate: tuple[int, int] | None = near[0]
                elif not near and len(hits) == 1:
                    candidate = hits[0]
                else:
                    candidate = None
                if candidate is not None and best_range is None:
                    best_range = candidate
            if not verified:
                reason = (
                    RejectReason.NO_EVIDENCE
                    if not finding.evidence
                    else RejectReason.EVIDENCE_NOT_FOUND
                )
                if self.require_llm_evidence:
                    return ValidationOutcome(ValidationStatus.REJECTED, None, reason, finding.title)
                notes.append("evidence could not be verified")
            elif best_range is None:
                if self.require_llm_evidence:
                    return ValidationOutcome(
                        ValidationStatus.REJECTED,
                        None,
                        RejectReason.EVIDENCE_NOT_FOUND,
                        "evidence exists in file but far from the cited lines",
                    )
            elif best_range != (start, end):
                if not (start <= best_range[0] and best_range[1] <= end):
                    notes.append(
                        f"lines moved from {start}-{end} to evidence at "
                        f"{best_range[0]}-{best_range[1]}"
                    )
                    start, end = best_range
                    status = ValidationStatus.REPAIRED
            dropped = len(finding.evidence) - len(verified)
            if dropped:
                notes.append(f"{dropped} unverifiable evidence snippet(s) dropped")
            evidence = verified or evidence

        if self.scope is not None and not self._in_scope(path, start, end):
            return ValidationOutcome(
                ValidationStatus.REJECTED, None, RejectReason.OUTSIDE_SCOPE, f"{path}:{start}"
            )

        if start > end:
            start, end = end, start
        validated = finding.model_copy(
            update={
                "file": path,
                "start_line": max(1, start),
                "end_line": max(1, end),
                "evidence": evidence,
                "notes": notes,
            }
        )
        if not evidence and validated.severity.rank > Severity.LOW.rank:
            validated = validated.model_copy(
                update={"severity": Severity.LOW, "notes": [*notes, "capped at low: no evidence"]}
            )
        return ValidationOutcome(status, validated)

    def _in_scope(self, path: str, start: int, end: int) -> bool:
        assert self.scope is not None
        ranges = self.scope.get(path)
        if not ranges:
            return False
        s = self.scope_slack
        return any(start <= r_end + s and r_start - s <= end for r_start, r_end in ranges)


@dataclass
class ValidationReport:
    accepted: list[Finding]
    rejected: list[ValidationOutcome]
    repaired: int

    @property
    def rejected_by_reason(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.rejected:
            key = str(r.reason)
            counts[key] = counts.get(key, 0) + 1
        return counts


def validate_all(validator: FindingValidator, findings: list[Finding]) -> ValidationReport:
    accepted: list[Finding] = []
    rejected: list[ValidationOutcome] = []
    repaired = 0
    for f in findings:
        outcome = validator.validate(f)
        if outcome.finding is None:
            rejected.append(outcome)
            logger.debug("Rejected finding %r: %s %s", f.title, outcome.reason, outcome.detail)
            continue
        if outcome.status is ValidationStatus.REPAIRED:
            repaired += 1
        accepted.append(outcome.finding)
    return ValidationReport(accepted=accepted, rejected=rejected, repaired=repaired)

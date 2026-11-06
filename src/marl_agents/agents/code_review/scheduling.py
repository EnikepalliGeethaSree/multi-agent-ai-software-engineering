"""Decide what actually goes to the LLM: nothing twice, the riskiest work first.

Free-tier quota is the scarce resource, so before any call the agent:
- reuses the saved reply of an identical earlier prompt (`UnitCache`), which is what makes a rerun
  after a quota stop repeat no finished work;
- reviews identical code once and maps the findings onto its other copies (`plan_units`);
- optionally orders units by the fine-tuned classifier's score, and in "gate" mode skips the low
  ones. A unit holding a critical/high or high-confidence static finding is never skipped, and
  static findings themselves are never removed by anything in this module.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from marl_agents.agents.code_review.units import ReviewUnit
from marl_agents.config import ClassifierSettings
from marl_agents.core.schemas import Finding, Severity
from marl_agents.ingestion.models import Repository
from marl_agents.llm.base import LLMProvider, Message
from marl_agents.llm.classifier import ChangeClassifier, change_text

logger = logging.getLogger(__name__)

HIGH_CONFIDENCE = 0.8
PROTECTED_SEVERITIES = {Severity.CRITICAL, Severity.HIGH}


class UnitCache:
    """LLM replies on disk, keyed by the exact request (prompt, model, generation settings)."""

    def __init__(self, directory: Path, ttl_hours: int = 168) -> None:
        self.dir = directory
        self.ttl_s = ttl_hours * 3600
        self.dir.mkdir(parents=True, exist_ok=True)
        self._prune()

    def _prune(self) -> None:
        cutoff = time.time() - self.ttl_s
        for f in self.dir.glob("*.json"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                logger.debug("Could not prune cache entry %s", f.name)

    @staticmethod
    def key(messages: list[Message], llm: LLMProvider) -> str:
        cfg = llm.config
        identity = [llm.name, llm.model, cfg.temperature, cfg.seed, cfg.max_tokens]
        payload = json.dumps([identity, [m.model_dump() for m in messages]], sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, key: str) -> str | None:
        path = self.dir / f"{key}.json"
        try:
            return path.read_text(encoding="utf-8") if path.is_file() else None
        except OSError:
            return None

    def put(self, key: str, reply_json: str) -> None:
        tmp = self.dir / f"{key}.tmp"
        tmp.write_text(reply_json, encoding="utf-8")
        tmp.replace(self.dir / f"{key}.json")


def static_in_unit(unit: ReviewUnit, static: list[Finding]) -> list[Finding]:
    return [
        f
        for f in static
        if f.file == unit.file and unit.start_line <= f.start_line <= unit.end_line
    ]


def is_protected(unit: ReviewUnit, static: list[Finding]) -> bool:
    """True when the classifier must not keep this unit away from the LLM."""
    return any(
        f.severity in PROTECTED_SEVERITIES or f.confidence >= HIGH_CONFIDENCE
        for f in static_in_unit(unit, static)
    )


def unit_fingerprint(repo: Repository, unit: ReviewUnit, static: list[Finding]) -> str:
    """Equal for two units only when the LLM would see the same code, marks and static findings.

    Everything is relative to the unit's first line, so a copy elsewhere in the repository matches.
    """
    base = unit.start_line
    code = "\n".join(repo.lines(unit.file)[base - 1 : unit.end_line])
    marks = [(s - base, e - base) for s, e in unit.changed]
    rules = [(f.rule_id, f.start_line - base, f.title) for f in static_in_unit(unit, static)]
    return hashlib.sha256(repr((code, marks, rules)).encode("utf-8")).hexdigest()


def patch_text(repo: Repository, unit: ReviewUnit, patches: dict[str, str] | None) -> str:
    """The change as the classifier saw it in training; added lines if no diff is available."""
    if patches and patches.get(unit.file):
        return patches[unit.file]
    lines = repo.lines(unit.file)
    added = [f"+{lines[n - 1]}" for s, e in unit.changed for n in range(s, e + 1)]
    return "\n".join(added)


@dataclass
class UnitPlan:
    order: list[int] = field(default_factory=list)  # indices to send, most important first
    duplicates: dict[int, int] = field(default_factory=dict)  # copy index -> reviewed index
    skipped: dict[int, float] = field(default_factory=dict)  # gated out, with its score
    scores: dict[int, float] = field(default_factory=dict)
    classifier: dict[str, object] = field(default_factory=dict)


def plan_units(
    repo: Repository,
    units: list[ReviewUnit],
    static: list[Finding],
    classifier: ChangeClassifier | None = None,
    settings: ClassifierSettings | None = None,
    patches: dict[str, str] | None = None,
) -> UnitPlan:
    plan = UnitPlan()
    first_seen: dict[str, int] = {}
    for i, unit in enumerate(units):
        fp = unit_fingerprint(repo, unit, static)
        if fp in first_seen:
            plan.duplicates[i] = first_seen[fp]
        else:
            first_seen[fp] = i
            plan.order.append(i)
    if classifier is None or settings is None:
        return plan

    # The classifier learned from diffs, so it only applies to change reviews.
    scorable = [i for i in plan.order if units[i].changed]
    if not scorable:
        plan.classifier = {
            "model": classifier.model_id,
            "applied": False,
            "scored": 0,
            "skipped": 0,
        }
        return plan
    texts = [change_text(patch_text(repo, units[i], patches)) for i in scorable]
    plan.scores = dict(zip(scorable, classifier.score(texts), strict=True))
    plan.order.sort(key=lambda i: -plan.scores.get(i, 1.0))  # unscored work is never pushed back
    protected = 0
    threshold = classifier.threshold if settings.threshold is None else settings.threshold
    if settings.mode == "gate":
        for i, score in plan.scores.items():
            if score >= threshold:
                continue
            if is_protected(units[i], static):
                protected += 1
            else:
                plan.skipped[i] = score
        plan.order = [i for i in plan.order if i not in plan.skipped]
    plan.classifier = {
        "model": classifier.model_id,
        "applied": True,
        "mode": settings.mode,
        "threshold": threshold,
        "scored": len(scorable),
        "skipped": len(plan.skipped),
        "protected": protected,
    }
    return plan

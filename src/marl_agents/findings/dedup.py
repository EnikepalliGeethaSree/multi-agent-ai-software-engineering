"""Merge findings that describe the same issue (e.g. Ruff and the LLM both flag a bare except)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from marl_agents.core.schemas import Category, Finding, FindingSource

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "in",
    "of",
    "to",
    "and",
    "or",
    "this",
    "that",
    "it",
    "be",
    "for",
    "on",
    "with",
    "as",
    "by",
    "not",
    "can",
    "may",
    "should",
    "which",
    "from",
    "at",
}

# Categories that frequently describe the same underlying problem from different angles.
_COMPATIBLE: list[set[Category]] = [
    {Category.BUG, Category.ERROR_HANDLING, Category.EDGE_CASE},
    {Category.QUALITY, Category.MAINTAINABILITY, Category.STANDARDS},
    {Category.SECURITY},
    {Category.PERFORMANCE},
    {Category.TESTING},
    {Category.DOCUMENTATION},
]


def tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def categories_compatible(a: Category, b: Category) -> bool:
    return a == b or any(a in group and b in group for group in _COMPATIBLE)


# Rules from different tools that detect the same underlying problem.
EQUIVALENT_RULES: list[set[str]] = [
    {"E722", "S110", "S112", "BLE001", "AST-SWALLOWED-EXCEPTION"},
    {"S105", "S106", "S107", "SECRET-HARD-CODED-CREDENTIAL"},
    {"RADON-CC", "AST-DEEP-NESTING", "AST-LONG-FUNCTION", "AST-TOO-MANY-PARAMS"},
    {"S301", "S302"},
    {"S602", "S604", "S605"},
]


def _rules(f: Finding) -> set[str]:
    """All rule ids a (possibly merged) finding stands for."""
    ids = {f.rule_id} if f.rule_id else set()
    ids.update(n.split("rule:", 1)[1] for n in f.notes if n.startswith("rule:"))
    return ids


def rules_equivalent(a: Finding, b: Finding) -> bool:
    ra, rb = _rules(a), _rules(b)
    if not ra or not rb:
        return False
    return bool(ra & rb) or any(ra & group and rb & group for group in EQUIVALENT_RULES)


_LOCATION = re.compile(r"^(?P<file>[^\s:]+):(?P<line>\d+)")


def points_at(a: Finding, b: Finding, slack: int = 2) -> bool:
    """`a.related` names a location inside `b` (e.g. an impact finding at a broken call site
    pointing at the changed definition the LLM also flagged)."""
    for rel in a.related:
        m = _LOCATION.match(rel)
        if (
            m
            and m["file"] == b.file
            and b.start_line - slack <= int(m["line"]) <= b.end_line + slack
        ):
            return True
    return False


def is_duplicate(a: Finding, b: Finding, text_threshold: float = 0.25) -> bool:
    if a.file != b.file:
        # Different files: only linked findings (one points at the other) can be the same issue.
        linked = points_at(a, b) or points_at(b, a)
        return linked and categories_compatible(a.category, b.category)
    if not a.overlaps(b, slack=1):
        return False
    if a.rule_id and b.rule_id and a.rule_id == b.rule_id:
        return (a.start_line, a.end_line) == (b.start_line, b.end_line)
    if rules_equivalent(a, b):
        return True
    if not categories_compatible(a.category, b.category):
        return False
    if a.cwe and a.cwe == b.cwe:
        return True
    cross_source = set(a.sources) != set(b.sources)
    llm_vs_tool = (FindingSource.LLM in a.sources) != (FindingSource.LLM in b.sources)
    # The LLM is shown the static findings and told not to repeat them; if it still reports a
    # compatible category (checked above) on overlapping lines, it is describing the same issue,
    # e.g. Ruff F401 "quality" vs the LLM's "Unused import" labelled "standards".
    if llm_vs_tool:
        return True
    same_span = (a.start_line, a.end_line) == (b.start_line, b.end_line)
    sim = jaccard(tokens(f"{a.title} {a.description}"), tokens(f"{b.title} {b.description}"))
    return sim >= text_threshold or (same_span and a.category == b.category and cross_source)


def combine_confidence(a: float, b: float) -> float:
    """Independent agreement raises confidence: 1 - (1-a)(1-b), capped at 0.99."""
    return min(0.99, 1 - (1 - a) * (1 - b))


def merge(primary: Finding, other: Finding) -> Finding:
    """Keep the richer description (LLM text is usually more explanatory), union everything else."""
    richer, poorer = (
        (primary, other) if len(primary.description) >= len(other.description) else (other, primary)
    )
    sources = list(dict.fromkeys([*primary.sources, *other.sources]))
    evidence = list(dict.fromkeys([*primary.evidence, *other.evidence]))
    cross_source = set(primary.sources) != set(other.sources)
    confidence = (
        combine_confidence(primary.confidence, other.confidence)
        if cross_source
        else max(primary.confidence, other.confidence)
    )
    worst = max((primary, other), key=lambda f: f.severity.rank)
    description = richer.description
    if poorer.title.strip() and poorer.title not in description and poorer.title != richer.title:
        description = f"{description}\nRelated: {poorer.title}"
    recommendation = richer.recommendation or poorer.recommendation
    if (
        richer.recommendation
        and poorer.recommendation
        and poorer.recommendation not in richer.recommendation
        and not _rules(richer) & _rules(poorer)
    ):
        recommendation = f"{richer.recommendation} Also: {poorer.recommendation}"
    rule_notes = [f"rule:{r}" for r in sorted(_rules(primary) | _rules(other))]
    if primary.file != other.file:
        # Keep the location of the finding that points at the other (the concrete broken site)
        # and record the other location as related.
        anchor, linked = (primary, other) if points_at(primary, other) else (other, primary)
        loc = {"file": anchor.file, "start_line": anchor.start_line, "end_line": anchor.end_line}
        related = list(
            dict.fromkeys(
                [
                    *anchor.related,
                    *linked.related,
                    f"{linked.file}:{linked.start_line} {linked.title}",
                ]
            )
        )
        evidence = list(dict.fromkeys([*anchor.evidence, *linked.evidence]))
    else:
        loc = {
            "file": primary.file,
            "start_line": min(primary.start_line, other.start_line),
            "end_line": max(primary.end_line, other.end_line),
        }
        related = list(dict.fromkeys([*primary.related, *other.related]))
    return richer.model_copy(
        update={
            "description": description,
            **loc,
            "related": related,
            "sources": sources,
            "context_refs": list(dict.fromkeys([*primary.context_refs, *other.context_refs])),
            "evidence": evidence,
            "confidence": confidence,
            "severity": worst.severity,
            "proposed_severity": worst.proposed_severity or worst.severity,
            "category": worst.category if worst.category != richer.category else richer.category,
            "rule_id": primary.rule_id or other.rule_id,
            "cwe": primary.cwe or other.cwe,
            "symbol": primary.symbol or other.symbol,
            "recommendation": recommendation,
            "test_recommendation": richer.test_recommendation or poorer.test_recommendation,
            "bug": richer.bug or poorer.bug,
            "notes": list(
                dict.fromkeys(
                    [*primary.notes, *other.notes, *rule_notes, f"merged with: {poorer.title[:80]}"]
                )
            ),
        }
    )


@dataclass
class DedupReport:
    findings: list[Finding]
    merged: int


def match_strength(existing: Finding, f: Finding) -> tuple[bool, bool, int, float]:
    """How closely two duplicates match, to pick the best cluster when several qualify: same
    category, then equivalent rules, then shared lines, then wording."""
    shared = min(existing.end_line, f.end_line) - max(existing.start_line, f.start_line) + 1
    sim = jaccard(
        tokens(f"{existing.title} {existing.description}"), tokens(f"{f.title} {f.description}")
    )
    return (existing.category == f.category, rules_equivalent(existing, f), shared, sim)


def deduplicate(findings: list[Finding], text_threshold: float = 0.25) -> DedupReport:
    """Greedy clustering: each finding merges into the existing cluster it duplicates most closely
    (an LLM "swallowed exception" joins the Ruff/AST one, not a resource leak on the line above)."""
    clusters: list[Finding] = []
    merged = 0
    ordered = sorted(findings, key=lambda f: (f.file, f.start_line, -f.severity.rank))
    for f in ordered:
        matches = [i for i, c in enumerate(clusters) if is_duplicate(c, f, text_threshold)]
        if matches:
            best = max(matches, key=lambda i: match_strength(clusters[i], f))
            clusters[best] = merge(clusters[best], f)
            merged += 1
        else:
            clusters.append(f)
    return DedupReport(findings=clusters, merged=merged)

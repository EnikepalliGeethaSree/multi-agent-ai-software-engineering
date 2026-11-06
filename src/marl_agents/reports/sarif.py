"""SARIF 2.1.0 export: the standard format CI systems and GitHub code scanning ingest.

Each finding becomes a `result` with its location, related locations and (when available) the
suggested fix as a SARIF `fix` (line replacement).
"""

from __future__ import annotations

import re
from typing import Any

from marl_agents.core.schemas import Finding, ReviewResult, Severity

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
_LEVEL = {
    Severity.CRITICAL: "error",
    Severity.HIGH: "error",
    Severity.MEDIUM: "warning",
    Severity.LOW: "note",
    Severity.INFO: "note",
}
_RELATED = re.compile(r"^(?P<file>[^\s:`]+)(?::(?P<line>\d+))?\s*(?P<text>.*)$")


def _rule_id(f: Finding) -> str:
    return f.rule_id or f"LLM-{f.category.value}"


def _location(file: str, start: int, end: int) -> dict[str, Any]:
    return {
        "physicalLocation": {
            "artifactLocation": {"uri": file, "uriBaseId": "SRCROOT"},
            "region": {"startLine": start, "endLine": end},
        }
    }


def _result(f: Finding) -> dict[str, Any]:
    res: dict[str, Any] = {
        "ruleId": _rule_id(f),
        "level": _LEVEL[f.severity],
        "message": {"text": f"{f.title}. {f.description}".strip()},
        "locations": [_location(f.file, f.start_line, f.end_line)],
        "properties": {
            "id": f.id,
            "severity": f.severity.value,
            "category": f.category.value,
            "confidence": f.confidence,
            "sources": [s.value for s in f.sources],
            **({"cwe": f.cwe} if f.cwe else {}),
            **({"recommendation": f.recommendation} if f.recommendation else {}),
        },
    }
    related = []
    for i, rel in enumerate(f.related):
        m = _RELATED.match(rel)
        if m and m["line"]:
            loc = _location(m["file"], int(m["line"]), int(m["line"]))
            related.append({"id": i, **loc, "message": {"text": m["text"] or rel}})
    if related:
        res["relatedLocations"] = related
    if f.suggested_fix:
        fx = f.suggested_fix
        res["fixes"] = [
            {
                "description": {
                    "text": f"{fx.source} fix ({'verified' if fx.verified else 'review'})"
                },
                "artifactChanges": [
                    {
                        "artifactLocation": {"uri": fx.file, "uriBaseId": "SRCROOT"},
                        "replacements": [
                            {
                                "deletedRegion": {
                                    "startLine": fx.start_line,
                                    "endLine": max(fx.end_line, fx.start_line),
                                }
                                if fx.end_line >= fx.start_line
                                else {"startLine": fx.start_line, "startColumn": 1, "endColumn": 1},
                                "insertedContent": {"text": fx.replacement + "\n"},
                            }
                        ],
                    }
                ],
            }
        ]
    return res


def to_sarif(result: ReviewResult) -> dict[str, Any]:
    rules: dict[str, dict[str, Any]] = {}
    for f in result.findings:
        rid = _rule_id(f)
        rules.setdefault(
            rid,
            {
                "id": rid,
                "shortDescription": {"text": f.title[:120]},
                "properties": {"category": f.category.value},
            },
        )
    return {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "marl-agents code review",
                        "informationUri": "https://sarifweb.azurewebsites.net/",
                        "rules": list(rules.values()),
                    }
                },
                "results": [_result(f) for f in result.findings],
            }
        ],
    }

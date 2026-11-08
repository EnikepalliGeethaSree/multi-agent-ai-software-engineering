"""Checks on bug claims, on top of the evidence validation every finding passes.

Validation proves the cited code exists. These prove the claim is about that code: a bug must say
what triggers it, and every name it depends on must appear in the code it cites.
"""

from __future__ import annotations

import re

from marl_agents.core.schemas import BugDetail, BugType, Category, Finding

NO_TRIGGER = "no_trigger"
UNKNOWN_NAME = "claim_names_unknown_identifier"

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Static rules that say which bug type they are; every other rule is left as "other".
_RULE_TYPES = {
    "BUG-NONE-DEREF": BugType.NULL_EXCEPTION,
    "BUG-NONE-DEFAULT": BugType.NULL_EXCEPTION,
    "BUG-MISSING-RETURN": BugType.LOGIC,
    "BUG-DIV-BY-LEN": BugType.BOUNDARY,
    "BUG-OFF-BY-ONE": BugType.BOUNDARY,
    "BUG-MUTATE-WHILE-ITERATING": BugType.LOGIC,
    "AST-RESOURCE-LEAK": BugType.RESOURCE_LEAK,
    "AST-SWALLOWED-EXCEPTION": BugType.NULL_EXCEPTION,
}


_CATEGORY_TYPES = {
    Category.SECURITY: BugType.SECURITY,
    Category.ERROR_HANDLING: BugType.NULL_EXCEPTION,
    Category.EDGE_CASE: BugType.BOUNDARY,
}


def claim_problem(finding: Finding, code: str, require_trigger: bool = True) -> str | None:
    """Why this LLM finding must be rejected, or None when its claim holds up."""
    bug = finding.bug
    if bug is None:
        return NO_TRIGGER if require_trigger else None
    if require_trigger and not bug.trigger.strip():
        return NO_TRIGGER
    known = set(_IDENT.findall(code))
    for name in bug.involved_names:
        # "self.items" or "items[0]" count by their identifiers; "None" and the like are not names.
        parts = [p for p in _IDENT.findall(name) if p not in {"None", "True", "False"}]
        if parts and not all(p in known for p in parts):
            return UNKNOWN_NAME
    return None


def static_detail(finding: Finding) -> BugDetail:
    """The bug detail of a tool finding: its rule decides the type, nothing is invented."""
    rule = finding.rule_id or ""
    fallback = _CATEGORY_TYPES.get(finding.category, BugType.OTHER)
    return BugDetail(
        bug_type=_RULE_TYPES.get(rule, fallback),
        root_cause=finding.description,
    )

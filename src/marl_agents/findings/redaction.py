"""Never re-publish secrets: mask string literals in the evidence of credential findings."""

from __future__ import annotations

import re

from marl_agents.core.schemas import Finding

_STRING = re.compile(r"""(?P<q>['"])(?P<body>[^'"\n]{6,})(?P=q)""")
_BARE_TOKEN = re.compile(r"(:\s*)([A-Za-z0-9/+_\-]{16,})\s*$")
SECRET_CWES = {"CWE-798", "CWE-259", "CWE-321"}


def mask_literals(text: str) -> str:
    text = _STRING.sub(lambda m: f"{m['q']}{m['body'][:2]}****{m['q']}", text)
    return _BARE_TOKEN.sub(lambda m: f"{m.group(1)}{m.group(2)[:4]}****", text)


def is_secret_finding(finding: Finding) -> bool:
    return (finding.cwe in SECRET_CWES) or bool(
        finding.rule_id and finding.rule_id.startswith("SECRET-")
    )


def redact_finding(finding: Finding) -> Finding:
    if not is_secret_finding(finding):
        return finding
    return finding.model_copy(update={"evidence": [mask_literals(e) for e in finding.evidence]})

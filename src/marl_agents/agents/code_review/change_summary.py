"""PR-style summary of a change: facts computed from the diff and the call graph, plus an optional
LLM-written narrative.

"Salient" change = the changed function that the other changed functions depend on most (it most
likely drove the rest of the change), following the salient-class idea from the code-review
automation literature; ties go to the function with more external callers.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from marl_agents.agents.code_review.prompts import load_prompt
from marl_agents.core.schemas import ChangedSymbol, ChangeSummary
from marl_agents.ingestion.changes import ChangeSet
from marl_agents.llm.base import LLMError, LLMProvider, Message, Usage
from marl_agents.parsing.repo_index import RepoIndex

logger = logging.getLogger(__name__)

MAX_DIFF_CHARS = 6000


class _Narrative(BaseModel):
    summary: str


def salient_symbol(symbols: list[ChangedSymbol], index: RepoIndex) -> str | None:
    changed = [s for s in symbols if s.kind != "removed"]
    if not changed:
        return None
    by_key = {(s.file, s.qualname): s for s in changed}
    depended_on: dict[tuple[str, str], int] = {key: 0 for key in by_key}
    for (file, qual), _sym in by_key.items():
        info = next((x for x in index.modules[file].symbols if x.qualname == qual), None)
        if info is None:
            continue
        for ref in index.callees(file, info):
            key = (ref.file, ref.symbol.qualname)
            if key in depended_on and key != (file, qual):
                depended_on[key] += 1
    best = max(
        changed, key=lambda s: (depended_on[(s.file, s.qualname)], s.callers, s.kind == "modified")
    )
    return f"{best.file}:{best.line} {best.qualname}"


def build_summary(
    change: ChangeSet,
    index: RepoIndex,
    symbols: list[ChangedSymbol],
    impacted_files: list[str],
    llm: LLMProvider | None = None,
    run_usage: Usage | None = None,
) -> tuple[ChangeSummary, list[str]]:
    errors: list[str] = []
    summary = ChangeSummary(
        base=change.base,
        head=change.head,
        files_changed=len(change.files),
        lines_added=sum(f.added for f in change.files),
        lines_deleted=sum(f.deleted for f in change.files),
        symbols=symbols,
        salient=salient_symbol(symbols, index),
        impacted_files=impacted_files,
    )
    if llm is None:
        return summary, errors

    diff = "\n".join(f.patch for f in change.files if f.patch)
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n... (truncated)"
    files = ", ".join(f"{f.path} ({f.status}, +{f.added}/-{f.deleted})" for f in change.files[:30])
    syms = ", ".join(f"{s.qualname} ({s.kind})" for s in symbols[:30]) or "none"
    prompt = load_prompt("summary").render(
        base=change.base,
        head=change.head,
        files=files,
        symbols=syms,
        impacted=", ".join(impacted_files[:20]) or "none",
        diff=diff,
    )
    try:
        out = llm.generate_structured(
            [
                Message(
                    role="system",
                    content="You summarize code changes for reviewers. Reply with JSON only.",
                ),
                Message(role="user", content=prompt),
            ],
            _Narrative,
            usage=run_usage,
        )
        summary.narrative = out.summary.strip() or None
    except LLMError as exc:
        errors.append(f"change summary failed: {exc}")
    return summary, errors

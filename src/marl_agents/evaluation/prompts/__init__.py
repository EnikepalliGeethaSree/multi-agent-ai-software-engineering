"""Versioned prompts used by evaluation (e.g. the LLM judge). Same file format as agent prompts."""

from __future__ import annotations

from functools import cache
from importlib import resources

from marl_agents.agents.code_review.prompts import PromptTemplate


@cache
def load_eval_prompt(name: str) -> PromptTemplate:
    raw = (resources.files(__package__) / f"{name}.md").read_text(encoding="utf-8")
    header, sep, body = raw.partition("\n---\n")
    if not sep or not header.startswith("version:"):
        raise ValueError(f"Prompt {name!r} must start with 'version: X' and a '---' line")
    return PromptTemplate(name=name, version=header.split(":", 1)[1].strip(), text=body.strip())

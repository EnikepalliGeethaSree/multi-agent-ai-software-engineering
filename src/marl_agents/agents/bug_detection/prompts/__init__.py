"""Versioned prompts of the Bug Detection Agent."""

from __future__ import annotations

from functools import cache

from marl_agents.agents.prompting import PromptTemplate, read_prompt


@cache
def load_prompt(name: str) -> PromptTemplate:
    return read_prompt(__package__, name)


def prompt_versions() -> dict[str, str]:
    return {f"bug_{n}": load_prompt(n).version for n in ("system", "review", "localize")}

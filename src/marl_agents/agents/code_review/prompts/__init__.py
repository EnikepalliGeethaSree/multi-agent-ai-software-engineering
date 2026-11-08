"""Versioned prompt templates. Each file starts with `version: X.Y` and a `---` separator."""

from __future__ import annotations

from functools import cache

from marl_agents.agents.prompting import PromptTemplate, read_prompt

__all__ = ["PromptTemplate", "load_prompt", "prompt_versions"]


@cache
def load_prompt(name: str) -> PromptTemplate:
    return read_prompt(__package__, name)


def prompt_versions() -> dict[str, str]:
    return {n: load_prompt(n).version for n in ("system", "review")}

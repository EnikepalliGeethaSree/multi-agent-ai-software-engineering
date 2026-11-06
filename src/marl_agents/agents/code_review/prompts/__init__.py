"""Versioned prompt templates. Each file starts with `version: X.Y` and a `---` separator."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from importlib import resources


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    version: str
    text: str

    def render(self, **values: object) -> str:
        return self.text.format(**values)


@cache
def load_prompt(name: str) -> PromptTemplate:
    raw = (resources.files(__package__) / f"{name}.md").read_text(encoding="utf-8")
    header, sep, body = raw.partition("\n---\n")
    if not sep or not header.startswith("version:"):
        raise ValueError(f"Prompt {name!r} must start with 'version: X' and a '---' line")
    return PromptTemplate(name=name, version=header.split(":", 1)[1].strip(), text=body.strip())


def prompt_versions() -> dict[str, str]:
    return {n: load_prompt(n).version for n in ("system", "review")}

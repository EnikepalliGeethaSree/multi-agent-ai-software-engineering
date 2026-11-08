"""Versioned prompt files, shared by all agents.

Each file starts with `version: X.Y` and a `---` separator, so a run can record what it used.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    version: str
    text: str

    def render(self, **values: object) -> str:
        return self.text.format(**values)


def read_prompt(package: str, name: str) -> PromptTemplate:
    """Read `<name>.md` from a prompts package."""
    raw = (resources.files(package) / f"{name}.md").read_text(encoding="utf-8")
    header, sep, body = raw.partition("\n---\n")
    if not sep or not header.startswith("version:"):
        raise ValueError(f"Prompt {name!r} must start with 'version: X' and a '---' line")
    return PromptTemplate(name=name, version=header.split(":", 1)[1].strip(), text=body.strip())

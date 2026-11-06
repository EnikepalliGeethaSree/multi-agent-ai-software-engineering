"""PostToolUse hook: run `ruff format` + safe `ruff check --fix` on edited Python files.

Silently does nothing if the file isn't Python, is outside src/ or tests/, or ruff isn't installed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    file_path = (payload.get("tool_input") or {}).get("file_path")
    if not file_path or not file_path.endswith(".py"):
        return 0

    path = Path(file_path).resolve()
    project = Path(__file__).resolve().parents[2]
    try:
        rel = path.relative_to(project)
    except ValueError:
        return 0
    if rel.parts[0] not in {"src", "tests", "experiments"} or not path.exists():
        return 0

    ruff = shutil.which("ruff") or shutil.which("ruff", path=str(project / ".venv" / "Scripts"))
    if ruff is None:
        return 0

    subprocess.run([ruff, "format", "--quiet", str(path)], cwd=project, check=False, timeout=20)
    subprocess.run(
        [ruff, "check", "--fix", "--quiet", "--exit-zero", str(path)],
        cwd=project,
        check=False,
        timeout=20,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

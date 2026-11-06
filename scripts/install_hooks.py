"""Install the code-review pre-commit hook into a git repository.

Usage (from anywhere):  python scripts/install_hooks.py [path/to/repo]

The hook reviews staged Python changes before each commit (see scripts/git-hooks/pre-commit).
An existing pre-commit hook is never overwritten silently: it is kept as pre-commit.bak.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "git-hooks" / "pre-commit"


def main(argv: list[str]) -> int:
    repo = Path(argv[1] if len(argv) > 1 else ".").resolve()
    git = shutil.which("git")
    if git is None:
        print("error: git is not installed", file=sys.stderr)
        return 2
    proc = subprocess.run(  # noqa: S603 - fixed binary, argument list, no shell
        [git, "-C", str(repo), "rev-parse", "--git-path", "hooks"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        print(f"error: {repo} is not a git repository", file=sys.stderr)
        return 2
    hooks = (repo / proc.stdout.strip()).resolve()
    hooks.mkdir(parents=True, exist_ok=True)
    target = hooks / "pre-commit"
    if target.exists():
        backup = target.with_suffix(".bak")
        shutil.copy2(target, backup)
        print(f"existing hook saved as {backup}")
    # newline="\n": git for Windows runs hooks with sh, which chokes on CRLF.
    target.write_text(HOOK.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    target.chmod(0o755)
    print(f"installed {target}")
    print("Configure with MARL_REVIEW_MODE / MARL_FAIL_ON / MARL_PYTHON (see the hook header).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

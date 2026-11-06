"""Phase 1: change (diff / PR) review - loading changes, impact analysis, risk, summary."""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from marl_agents.agents.code_review import CodeReviewAgent
from marl_agents.agents.code_review.change_review import review_change
from marl_agents.agents.code_review.impact import call_mismatch, signature_of
from marl_agents.config import Settings
from marl_agents.core.schemas import Finding
from marl_agents.findings import deduplicate
from marl_agents.ingestion.changes import (
    ChangeError,
    changeset_from_git,
    changeset_from_zips,
    diff_versions,
)
from marl_agents.llm import Message, MockLLMProvider

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

USERS_V1 = '''"""User helpers."""

USERS = {1: {"id": 1, "email": "a@x.com", "first": "Ada", "last": "Lovelace"}}


def get_user(conn, user_id):
    """Return the user dict."""
    return dict(USERS.get(user_id, {"id": user_id, "email": ""}))


def format_name(first, last):
    return f"{first} {last}"


def legacy_total(items):
    return sum(i["price"] for i in items)
'''

USERS_V2 = '''"""User helpers."""

USERS = {1: {"id": 1, "email": "a@x.com", "first": "Ada", "last": "Lovelace"}}


def get_user(conn, user_id):
    """Return the user dict, or None when the user does not exist."""
    if user_id not in USERS:
        return None
    return dict(USERS[user_id])


def format_name(first, last, title):
    return f"{title} {first} {last}"
'''

ORDERS = '''"""Order helpers that depend on users."""

from shop.users import format_name, get_user, legacy_total


def order_email(conn, uid):
    user = get_user(conn, uid)
    return user["email"].lower()


def label(user):
    return format_name(user["first"], user["last"])


def total(items):
    return legacy_total(items)
'''


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "shop").mkdir(parents=True)
    _git(repo.parent, "init", "-q", "-b", "main", str(repo))
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "shop" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "shop" / "users.py").write_text(USERS_V1, encoding="utf-8")
    (repo / "shop" / "orders.py").write_text(ORDERS, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    (repo / "shop" / "users.py").write_text(USERS_V2, encoding="utf-8")
    _git(repo, "commit", "-qam", "change users api")
    return repo


# ---- signature binding -------------------------------------------------------------------------


def _sig(src: str, method: bool = False):  # type: ignore[no-untyped-def]
    node = ast.parse(src).body[0]
    assert isinstance(node, ast.FunctionDef)
    return signature_of(node, method)


def _call(src: str) -> ast.Call:
    node = ast.parse(src).body[0]
    assert isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
    return node.value


@pytest.mark.parametrize(
    ("defn", "call", "method", "expected"),
    [
        ("def f(a, b, c): pass", "f(1, 2)", False, "missing required argument(s): c"),
        ("def f(a, b): pass", "f(1, 2, 3)", False, "at most 2"),
        ("def f(a, b=1): pass", "f(1, c=2)", False, "unknown keyword argument(s): c"),
        ("def f(a, *, key): pass", "f(1)", False, "missing required argument(s): key"),
        ("def f(a, b=1): pass", "f(1)", False, None),
        ("def f(a, *args): pass", "f(1, 2, 3, 4)", False, None),
        ("def f(a, **kw): pass", "f(1, anything=2)", False, None),
        ("def f(a, b): pass", "f(*xs)", False, None),  # undecidable -> no claim
        ("def m(self, a): pass", "obj.m(1)", True, None),  # self bound
        ("def m(self, a): pass", "obj.m()", True, "missing required argument(s): a"),
        ("@staticmethod\ndef m(a): pass", "C.m(1)", True, None),
    ],
)
def test_call_mismatch(defn: str, call: str, method: bool, expected: str | None) -> None:
    c = _call(call)
    why = call_mismatch(_sig(defn, method), c, isinstance(c.func, ast.Attribute))
    if expected is None:
        assert why is None
    else:
        assert why is not None and expected in why


def test_signature_text() -> None:
    assert _sig("def f(a, b=1, *args, k, **kw): pass").text() == "(a, b=…, *args, k, **kwargs)"
    assert _sig("def f(a, *, k=2): pass").text() == "(a, *, k=…)"


# ---- loading changes ---------------------------------------------------------------------------


def test_diff_versions_detects_add_delete_modify_rename() -> None:
    body = "def f():\n" + "".join(f"    x{i} = {i}\n" for i in range(20))
    old = {"a.py": "x = 1\n", "gone.py": "y = 2\n", "old_name.py": body, "same.py": "z = 3\n"}
    new = {
        "a.py": "x = 2\n",
        "new.py": "w = 4\n",
        "new_name.py": body + "    x99 = 99\n",
        "same.py": "z = 3\n",
    }
    files = {f.path: f for f in diff_versions(old, new)}
    assert files["a.py"].status == "modified" and files["a.py"].changed_ranges == [(1, 1)]
    assert files["new.py"].status == "added" and files["gone.py"].status == "deleted"
    assert (
        files["new_name.py"].status == "renamed" and files["new_name.py"].old_path == "old_name.py"
    )
    assert files["new_name.py"].added == 1 and "same.py" not in files and "old_name.py" not in files


@needs_git
def test_changeset_from_git_refs(git_repo: Path, settings: Settings) -> None:
    ch = changeset_from_git(git_repo, "HEAD~1", "HEAD", settings=settings.ingestion)
    try:
        assert [(f.path, f.status) for f in ch.files] == [("shop/users.py", "modified")]
        assert ch.old_sources["shop/users.py"] == USERS_V1.replace("\r\n", "\n")
        assert ch.repo.read_text("shop/orders.py").startswith('"""Order helpers')  # full new tree
        assert ch.scope()["shop/users.py"]
        workspace = ch.repo.workspace
    finally:
        ch.cleanup()
    assert workspace is not None and not workspace.exists()


@needs_git
def test_changeset_working_tree_and_staged(git_repo: Path, settings: Settings) -> None:
    (git_repo / "shop" / "orders.py").write_text(
        ORDERS + "\n\ndef extra():\n    return 1\n", encoding="utf-8"
    )
    wt = changeset_from_git(git_repo, "HEAD", settings=settings.ingestion)
    assert [f.path for f in wt.files] == ["shop/orders.py"] and wt.head == "working tree"
    wt.cleanup()
    with pytest.raises(ChangeError, match="No differences"):
        changeset_from_git(git_repo, "HEAD", staged=True, settings=settings.ingestion)
    _git(git_repo, "add", "shop/orders.py")
    staged = changeset_from_git(git_repo, "HEAD", staged=True, settings=settings.ingestion)
    assert [f.path for f in staged.files] == ["shop/orders.py"] and staged.head == "staged changes"
    staged.cleanup()


@needs_git
@pytest.mark.parametrize("bad", ["--output=/tmp/x", "HEAD;rm -rf /", "no-such-branch", "a b"])
def test_bad_refs_rejected(git_repo: Path, settings: Settings, bad: str) -> None:
    with pytest.raises(ChangeError):
        changeset_from_git(git_repo, bad, settings=settings.ingestion)


def test_not_a_git_repo(tmp_path: Path, settings: Settings) -> None:
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    with pytest.raises(ChangeError, match="not a git repository"):
        changeset_from_git(tmp_path, "HEAD", settings=settings.ingestion)


def _zip(path: Path, files: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, text in files.items():
            zf.writestr(f"proj/{name}", text)
    return path


def test_changeset_from_two_zips(tmp_path: Path, settings: Settings) -> None:
    before = _zip(tmp_path / "before.zip", {"shop/users.py": USERS_V1, "shop/orders.py": ORDERS})
    after = _zip(tmp_path / "after.zip", {"shop/users.py": USERS_V2, "shop/orders.py": ORDERS})
    ch = changeset_from_zips(before, after, settings.ingestion)
    try:
        assert [f.path for f in ch.files] == ["shop/users.py"] and ch.base == "before.zip"
    finally:
        ch.cleanup()
    same = _zip(tmp_path / "same.zip", {"shop/users.py": USERS_V1, "shop/orders.py": ORDERS})
    with pytest.raises(ChangeError, match="No differences"):
        changeset_from_zips(before, same, settings.ingestion)


# ---- the full change review ------------------------------------------------------------------


def impact_responder(messages: list[Message]) -> str:
    user = messages[-1].content
    if "## Change impact check" in user and "get_user" in user:
        return json.dumps(
            {
                "findings": [
                    {
                        "file": "shop/orders.py",
                        "start_line": 8,
                        "end_line": 8,
                        "category": "bug",
                        "severity": "high",
                        "title": "order_email assumes get_user always returns a dict",
                        "description": "get_user now returns None for unknown users.",
                        "evidence": ['return user["email"].lower()'],
                        "recommendation": "Handle None before indexing.",
                        "confidence": 0.9,
                    }
                ]
            }
        )
    if "Summarize this code change" in user:
        return json.dumps({"summary": "Changes the users API: get_user may return None."})
    return json.dumps({"findings": [], "static_assessments": []})


@needs_git
def test_review_change_static_only_finds_cross_file_breaks(
    git_repo: Path, settings: Settings
) -> None:
    settings.review.mode = "static_only"
    ch = changeset_from_git(git_repo, "HEAD~1", "HEAD", settings=settings.ingestion)
    try:
        result = review_change(CodeReviewAgent(settings=settings, progress=lambda _m: None), ch)
    finally:
        ch.cleanup()
    by_rule = {f.rule_id: f for f in result.findings}
    sig = by_rule["IMPACT-SIGNATURE"]
    assert (sig.file, sig.start_line) == (
        "shop/orders.py",
        12,
    )  # in a file the change never touched
    assert "missing required argument(s): title" in sig.description
    assert by_rule["IMPACT-REMOVED"].start_line == 16
    change = result.change
    assert change is not None
    kinds = {s.qualname: (s.kind, s.signature_changed) for s in change.summary.symbols}
    assert kinds == {
        "get_user": ("modified", False),
        "format_name": ("modified", True),
        "legacy_total": ("removed", False),
    }
    assert change.summary.impacted_files == ["shop/orders.py"]
    assert change.summary.narrative is None  # no LLM in static mode
    top = change.hunks[0]
    assert top.file == "shop/users.py" and top.level == "high"
    assert any("breaks 2 call site(s)" in r for r in top.reasons)
    assert result.stats["change"]["impact_findings"] == 2


@needs_git
def test_review_change_with_llm_catches_behaviour_change(
    git_repo: Path, settings: Settings
) -> None:
    llm = MockLLMProvider(responder=impact_responder)
    ch = changeset_from_git(git_repo, "HEAD~1", "HEAD", settings=settings.ingestion)
    try:
        result = review_change(
            CodeReviewAgent(llm, settings=settings, progress=lambda _m: None), ch
        )
    finally:
        ch.cleanup()
    behaviour = [f for f in result.findings if f.rule_id == "IMPACT-BEHAVIOR"]
    assert (
        len(behaviour) == 1
        and behaviour[0].file == "shop/orders.py"
        and behaviour[0].start_line == 8
    )
    assert behaviour[0].related and behaviour[0].related[0].startswith("shop/users.py:6")
    assert result.change is not None and "may return None" in (
        result.change.summary.narrative or ""
    )
    impact_prompts = [c for c in llm.calls if "## Change impact check" in c[-1].content]
    assert (
        len(impact_prompts) == 1
    )  # only get_user: the other two were already flagged deterministically
    assert (
        "BEFORE the change" in impact_prompts[0][-1].content
        and "return dict(USERS.get" in impact_prompts[0][-1].content
    )
    assert result.stats["llm_usage"]["calls"] == len(llm.calls)


def test_cross_file_duplicates_are_linked_and_keep_the_call_site() -> None:
    def f(**kw):  # type: ignore[no-untyped-def]
        base = {
            "id": "X",
            "start_line": 1,
            "end_line": 1,
            "category": "bug",
            "severity": "high",
            "title": "t",
            "description": "d",
            "evidence": ["e"],
            "confidence": 0.8,
            "sources": ["ast"],
        }
        return Finding.model_validate({**base, **kw})

    impact = f(
        file="orders.py",
        start_line=12,
        end_line=12,
        rule_id="IMPACT-SIGNATURE",
        related=["users.py:13 `format_name` changed signature"],
    )
    llm = f(
        file="users.py",
        start_line=13,
        end_line=13,
        sources=["llm"],
        title="Signature change breaks callers",
    )
    unrelated = f(file="users.py", start_line=40, end_line=40, sources=["llm"], title="other")
    report = deduplicate([impact, llm, unrelated])
    assert report.merged == 1 and len(report.findings) == 2
    merged = next(x for x in report.findings if x.file == "orders.py")
    assert merged.start_line == 12 and {s.value for s in merged.sources} == {"ast", "llm"}
    assert any(r.startswith("users.py:13") for r in merged.related)

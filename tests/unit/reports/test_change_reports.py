"""Change-review output: Markdown change section, SARIF export, PDF, and the CLI gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from marl_agents import cli
from marl_agents.core.schemas import (
    ChangedSymbol,
    ChangeReview,
    ChangeSummary,
    Finding,
    HunkRisk,
    ReviewResult,
    RunMetadata,
    SuggestedFix,
)
from marl_agents.reports import to_markdown, write_reports
from marl_agents.reports.sarif import to_sarif
from tests.unit.agents.test_change_review import git_repo, needs_git  # noqa: F401 - fixture

PATCH = "@@ -8,2 +8,2 @@\n-def format_name(first, last):\n+def format_name(first, last, title):\n"

IMPACT = Finding(
    id="CR-001",
    file="shop/orders.py",
    start_line=12,
    end_line=12,
    category="bug",
    severity="high",
    title="Call to format_name no longer matches its new signature",
    description="format_name now requires 'title'; this call passes two arguments.",
    recommendation="Pass a title or give it a default.",
    confidence=0.9,
    sources=["ast"],  # type: ignore[list-item]
    rule_id="IMPACT-SIGNATURE",
    related=["shop/users.py:8 format_name(first, last, title) (changed)"],
)
FIXED = Finding(
    id="CR-002",
    file="shop/users.py",
    start_line=1,
    end_line=1,
    category="quality",
    severity="low",
    title="Unused import",
    description="os is imported but never used.",
    confidence=0.8,
    sources=["ruff"],  # type: ignore[list-item]
    rule_id="F401",
    suggested_fix=SuggestedFix(
        file="shop/users.py",
        start_line=1,
        end_line=1,
        replacement="",
        diff="--- a/shop/users.py\n+++ b/shop/users.py\n@@ -1 +0,0 @@\n-import os\n",
        source="ruff",
        verified=True,
        checks=["ruff safe fix"],
    ),
)
INSERT_FIX = Finding.model_validate(
    {
        **FIXED.model_dump(),
        "id": "CR-003",
        "rule_id": None,
        "sources": ["llm"],
        "suggested_fix": {
            **FIXED.suggested_fix.model_dump(),  # type: ignore[union-attr]
            "start_line": 2,
            "end_line": 1,
            "replacement": "import re",
            "source": "llm",
        },
    }
)


def _change_result() -> ReviewResult:
    change = ChangeReview(
        summary=ChangeSummary(
            base="main (132b1d42)",
            head="feature (702aec34)",
            files_changed=1,
            lines_added=6,
            lines_deleted=8,
            symbols=[
                ChangedSymbol(
                    file="shop/users.py",
                    qualname="format_name",
                    kind="modified",
                    line=8,
                    signature_changed=True,
                    old_signature="format_name(first, last)",
                    new_signature="format_name(first, last, title)",
                    callers=1,
                    callers_not_updated=1,
                )
            ],
            salient="shop/users.py::format_name",
            impacted_files=["shop/orders.py"],
            narrative="format_name now needs a title; orders.py was not updated.",
        ),
        hunks=[
            HunkRisk(
                file="shop/users.py",
                start_line=8,
                end_line=9,
                score=68,
                level="high",
                reasons=["breaks 1 call site(s) in other code"],
                patch=PATCH,
                finding_ids=["CR-001"],
            )
        ],
    )
    return ReviewResult(
        agent="code_review",
        findings=[IMPACT, FIXED, INSERT_FIX],
        metadata=RunMetadata(agent="code_review", provider="mock"),
        files_analyzed=1,
        lines_analyzed=20,
        change=change,
    )


def test_markdown_has_change_section_hunks_and_fixes() -> None:
    md = to_markdown(_change_result())
    assert md.startswith("# Change Review Report")
    for needle in (
        "## Change summary",
        "`main (132b1d42)` → `feature (702aec34)`",
        "orders.py was not updated",
        "**Unchanged files that call changed code:** `shop/orders.py`",
        "`format_name(first, last)` → `format_name(first, last, title)`",
        "### Review these hunks first",
        "**HIGH (68/100)** `shop/users.py:8-9`",
        "+def format_name(first, last, title):",
        "shop/users.py:8 format_name(first, last, title) (changed)",
        "-import os",
    ):
        assert needle in md, needle


def test_sarif_structure() -> None:
    sarif = to_sarif(_change_result())
    assert sarif["version"] == "2.1.0"
    run = sarif["runs"][0]
    rule_ids = [r["id"] for r in run["tool"]["driver"]["rules"]]
    assert rule_ids == ["IMPACT-SIGNATURE", "F401", "LLM-quality"]
    impact, fixed, insert = run["results"]
    assert impact["level"] == "error" and fixed["level"] == "note"
    loc = impact["locations"][0]["physicalLocation"]
    assert loc["artifactLocation"]["uri"] == "shop/orders.py" and loc["region"]["startLine"] == 12
    rel = impact["relatedLocations"][0]
    assert rel["physicalLocation"]["region"]["startLine"] == 8
    assert rel["message"]["text"] == "format_name(first, last, title) (changed)"
    assert "fixes" not in impact
    repl = fixed["fixes"][0]["artifactChanges"][0]["replacements"][0]
    assert repl["deletedRegion"] == {"startLine": 1, "endLine": 1}
    assert fixed["fixes"][0]["description"]["text"] == "ruff fix (verified)"
    # pure insertion: empty region before line 2
    ins = insert["fixes"][0]["artifactChanges"][0]["replacements"][0]
    assert ins["deletedRegion"] == {"startLine": 2, "startColumn": 1, "endColumn": 1}
    assert ins["insertedContent"]["text"] == "import re\n"
    json.dumps(sarif)  # serialisable


def test_write_all_formats_for_a_change(tmp_path: Path) -> None:
    written = write_reports(_change_result(), tmp_path, ("json", "md", "pdf", "sarif"))
    assert set(written) == {"json", "md", "pdf", "sarif"}
    assert written["pdf"].read_bytes().startswith(b"%PDF")
    assert json.loads(written["sarif"].read_text(encoding="utf-8"))["runs"][0]["results"]
    assert json.loads(written["json"].read_text(encoding="utf-8"))["result"]["change"]["hunks"]


# ---- CLI ----------------------------------------------------------------------------------------


def test_exit_code_gate() -> None:
    result = _change_result()
    assert cli._exit_code(result, "none") == 0
    assert cli._exit_code(result, "critical") == 0
    assert cli._exit_code(result, "high") == 1
    assert cli._exit_code(result.model_copy(update={"findings": [FIXED]}), "medium") == 0
    assert cli._exit_code(result.model_copy(update={"findings": [FIXED]}), "low") == 1


@needs_git
def test_cli_review_change_blocks_on_high(
    git_repo: Path,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("marl_agents.static_analysis.type_check.mypy_available", lambda: False)
    monkeypatch.setenv("MARL_INGESTION__WORKSPACE_DIR", str(tmp_path / "ws"))
    out = tmp_path / "out"
    args = [
        "review-change", str(git_repo), "--base", "HEAD~1", "--head", "HEAD",
        "--mode", "static_only", "--provider", "mock", "--no-rag",
        "--out", str(out), "--formats", "md,sarif", "--fail-on", "high",
    ]  # fmt: skip
    assert cli.main(args) == 1
    printed = capsys.readouterr()
    assert "Review these first:" in printed.out and "IMPACT" not in printed.err
    assert "Call to format_name no longer matches its new signature" in printed.out
    assert "FAIL: " in printed.err
    assert (out / "review.md").is_file() and (out / "review.sarif").is_file()
    assert cli.main([*args[:-1], "critical"]) == 0


def test_cli_review_change_reports_bad_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["review-change", str(tmp_path), "--provider", "mock"]) == 2
    assert "not a git repository" in capsys.readouterr().err
    assert cli.main(["review-change", "--before", "a.zip", "--provider", "mock"]) == 2

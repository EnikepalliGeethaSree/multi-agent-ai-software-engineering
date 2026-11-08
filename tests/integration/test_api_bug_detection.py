"""The dashboard backend and CLI with the Bug Detection Agent (offline)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from marl_agents.agents.bug_detection import BugDetectionAgent
from marl_agents.agents.code_review.change_review import review_change
from marl_agents.api import create_app
from marl_agents.cli import main
from marl_agents.config import Settings
from marl_agents.ingestion.changes import changeset_from_git
from tests.integration.test_api import paths, wait_done  # noqa: F401 - `paths` is a fixture

CODE = "def mean(values):\n    return sum(values) / len(values)\n"
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@pytest.fixture
def client(settings: Settings, paths: dict[str, Path]):  # type: ignore[no-untyped-def]  # noqa: F811
    app = create_app(settings, paths["jobs"], paths["results"], paths["dist"])
    with TestClient(app) as c:
        yield c


def test_review_with_the_bug_agent(client: TestClient) -> None:
    options = {"mode": "static_only", "agent": "bug_detection"}
    job = client.post("/api/reviews", data={"snippet": CODE, "options": json.dumps(options)}).json()
    body = wait_done(client, job["id"])
    assert body["job"]["status"] == "done"
    assert body["job"]["options"]["agent"] == "bug_detection"
    result = body["result"]
    assert result["agent"] == "bug_detection"
    assert result["findings"][0]["id"] == "BD-001"
    assert result["findings"][0]["bug"]["bug_type"] == "boundary"
    report = client.get(f"/api/reviews/{job['id']}/report/md")
    assert report.text.startswith("# Bug Detection Report")


def test_code_review_stays_the_default(client: TestClient) -> None:
    job = client.post(
        "/api/reviews", data={"snippet": CODE, "options": json.dumps({"mode": "static_only"})}
    ).json()
    assert wait_done(client, job["id"])["result"]["agent"] == "code_review"


def test_failing_test_that_is_not_in_the_upload_fails_clearly(client: TestClient) -> None:
    options = {
        "mode": "static_only",
        "agent": "bug_detection",
        "failing_test": "tests/missing.py::test_x",
    }
    job = client.post("/api/reviews", data={"snippet": CODE, "options": json.dumps(options)}).json()
    body = wait_done(client, job["id"])
    assert body["job"]["status"] == "failed"
    assert "not in this repository" in body["job"]["error"]


def test_unknown_agent_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/reviews", data={"snippet": CODE, "options": json.dumps({"agent": "nope"})}
    )
    assert response.status_code == 422


def test_cli_bugs_writes_reports(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "stats.py"
    target.write_text(CODE, encoding="utf-8")
    out = tmp_path / "out"
    code = main(
        ["bugs", str(target), "--mode", "static_only", "--provider", "mock", "--no-cache",
         "--formats", "json,md", "--out", str(out)]
    )  # fmt: skip
    assert code == 0
    assert "BUG-" not in capsys.readouterr().err
    assert (out / "review.md").read_text(encoding="utf-8").startswith("# Bug Detection Report")


def test_cli_locates_a_failure_from_its_test(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "stats.py").write_text(CODE, encoding="utf-8")
    (repo / "tests" / "test_stats.py").write_text(
        "from stats import mean\n\n\ndef test_empty():\n    assert mean([]) == 0\n",
        encoding="utf-8",
    )
    code = main(
        ["bugs", str(repo), "--failing-test", "tests/test_stats.py::test_empty", "--mode",
         "static_only", "--provider", "mock", "--no-cache", "--formats", "json",
         "--out", str(tmp_path / "out")]
    )  # fmt: skip
    assert code == 0
    assert "1. stats.py:1 mean" in capsys.readouterr().out


def test_cli_refuses_the_test_split_without_final(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["eval-bugs", "detection", "--split", "test", "--provider", "mock"]) == 2
    assert "final numbers" in capsys.readouterr().err


def test_cli_refuses_unknown_configurations(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["eval-bugs", "detection", "--configurations", "nope", "--provider", "mock"])
    assert code == 2


@needs_git
def test_bug_agent_reviews_a_change(settings: Settings, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
            cwd=repo, check=True, capture_output=True,
        )  # fmt: skip

    git("init", "-q")
    (repo / "stats.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-q", "-m", "first")
    (repo / "stats.py").write_text(CODE, encoding="utf-8")
    settings.review.mode = "static_only"
    change = changeset_from_git(repo, "HEAD", None, False, settings.ingestion)
    try:
        result = review_change(BugDetectionAgent(None, settings=settings), change)
    finally:
        change.cleanup()
    assert result.change is not None
    assert [f.rule_id for f in result.findings] == ["BUG-DIV-BY-LEN"]

"""Change review through the API: two ZIPs, a local git repository, and every rejection path."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from marl_agents.api import create_app
from marl_agents.api.app import LOCAL_HEADER
from marl_agents.config import Settings
from tests.integration.test_api import STATIC, wait_done
from tests.unit.agents.test_change_review import (  # noqa: F401 - git_repo is a fixture
    ORDERS,
    USERS_V1,
    USERS_V2,
    git_repo,
    needs_git,
)

LOCAL = {"base_url": "http://127.0.0.1:8000", "client": ("127.0.0.1", 50000)}


def _zip(users: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("shop-main/shop/__init__.py", "")
        zf.writestr("shop-main/shop/users.py", users)
        zf.writestr("shop-main/shop/orders.py", ORDERS)
    return buf.getvalue()


def _app(settings: Settings, tmp_path: Path, **kw: object):  # type: ignore[no-untyped-def]
    return create_app(settings, tmp_path / "jobs", tmp_path / "results", tmp_path / "dist", **kw)


@pytest.fixture
def client(settings: Settings, tmp_path: Path):  # type: ignore[no-untyped-def]
    with TestClient(_app(settings, tmp_path)) as c:
        yield c


@pytest.fixture
def local_client(settings: Settings, tmp_path: Path):  # type: ignore[no-untyped-def]
    with TestClient(_app(settings, tmp_path), headers={LOCAL_HEADER: "dashboard"}, **LOCAL) as c:
        yield c


def _rules(body: dict) -> set[tuple[str, str, int]]:  # type: ignore[type-arg]
    return {(f["rule_id"], f["file"], f["start_line"]) for f in body["result"]["findings"]}


def test_change_review_from_two_zips(client: TestClient) -> None:
    files = {
        "before": ("v1.zip", _zip(USERS_V1), "application/zip"),
        "after": ("v2.zip", _zip(USERS_V2), "application/zip"),
    }
    r = client.post("/api/changes", files=files, data={"options": STATIC})
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["source_type"] == "change" and job["name"] == "v1.zip -> v2.zip"
    assert job["change"] == {"kind": "zips", "base": "v1.zip", "head": "v2.zip", "repo_path": None}
    body = wait_done(client, job["id"])
    assert body["job"]["status"] == "done", body["job"]["error"]
    change = body["result"]["change"]
    assert change["summary"]["impacted_files"] == ["shop/orders.py"]
    assert change["hunks"] and change["hunks"][0]["file"] == "shop/users.py"
    rules = _rules(body)
    assert ("IMPACT-SIGNATURE", "shop/orders.py", 12) in rules
    assert ("IMPACT-REMOVED", "shop/orders.py", 16) in rules
    # uploads are not kept once the review finishes
    assert not (Path(client.app.state.manager.jobs_dir) / job["id"] / "input").exists()  # type: ignore[attr-defined]
    sarif = client.get(f"/api/reviews/{job['id']}/report/sarif")
    assert sarif.status_code == 200 and sarif.json()["version"] == "2.1.0"
    md = client.get(f"/api/reviews/{job['id']}/report/md").text
    assert "Review these hunks first" in md


@needs_git
def test_change_review_from_local_git(local_client: TestClient, git_repo: Path) -> None:  # noqa: F811
    assert local_client.get("/api/health").json()["local_git"] is True
    data = {"repo_path": str(git_repo), "base": "HEAD~1", "head": "HEAD", "options": STATIC}
    r = local_client.post("/api/changes", data=data)
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["change"]["kind"] == "git" and job["change"]["head"] == "HEAD"
    body = wait_done(local_client, job["id"])
    assert body["job"]["status"] == "done", body["job"]["error"]
    assert ("IMPACT-SIGNATURE", "shop/orders.py", 12) in _rules(body)


@needs_git
def test_local_git_working_tree_and_staged(local_client: TestClient, git_repo: Path) -> None:  # noqa: F811
    (git_repo / "shop" / "users.py").write_text(USERS_V1, encoding="utf-8")  # revert, unstaged
    r = local_client.post("/api/changes", data={"repo_path": str(git_repo), "options": STATIC})
    body = wait_done(local_client, r.json()["id"])
    assert body["job"]["change"]["head"] == "working tree"
    assert body["result"]["change"]["summary"]["files_changed"] == 1
    # nothing staged -> the job fails with a clear message (no crash)
    r = local_client.post(
        "/api/changes", data={"repo_path": str(git_repo), "staged": "true", "options": STATIC}
    )
    body = wait_done(local_client, r.json()["id"])
    assert body["job"]["status"] == "failed" and "No differences" in body["job"]["error"]


@needs_git
@pytest.mark.parametrize(
    ("kw", "headers"),
    [
        ({}, {LOCAL_HEADER: "x"}),  # remote client address
        (LOCAL, {}),  # no custom header (plain cross-site form POST)
        (LOCAL, {LOCAL_HEADER: "x", "host": "evil.example:8000"}),  # DNS rebinding
    ],
)
def test_local_git_refused_unless_truly_local(
    settings: Settings,
    tmp_path: Path,
    git_repo: Path,  # noqa: F811
    kw: dict,  # type: ignore[type-arg]
    headers: dict[str, str],
) -> None:
    with TestClient(_app(settings, tmp_path), **kw) as c:
        r = c.post("/api/changes", data={"repo_path": str(git_repo)}, headers=headers)
        assert r.status_code == 403
        assert c.get("/api/reviews").json() == []


@needs_git
def test_local_git_can_be_disabled(settings: Settings, tmp_path: Path, git_repo: Path) -> None:  # noqa: F811
    app = _app(settings, tmp_path, allow_local_git=False)
    with TestClient(app, headers={LOCAL_HEADER: "x"}, **LOCAL) as c:
        assert c.get("/api/health").json()["local_git"] is False
        assert c.post("/api/changes", data={"repo_path": str(git_repo)}).status_code == 403


@needs_git
@pytest.mark.parametrize(
    ("data", "status", "message"),
    [
        ({"base": "no-such-branch"}, 422, "Unknown or invalid git reference"),
        ({"base": "--upload-pack=evil"}, 422, "Unknown or invalid git reference"),
        ({"head": "HEAD", "staged": "true"}, 422, "not both"),
    ],
)
def test_local_git_bad_input(
    local_client: TestClient,
    git_repo: Path,  # noqa: F811
    data: dict[str, str],
    status: int,
    message: str,
) -> None:
    r = local_client.post("/api/changes", data={"repo_path": str(git_repo), **data})
    assert r.status_code == status and message in r.json()["detail"]


def test_not_a_git_repository(local_client: TestClient, tmp_path: Path) -> None:
    r = local_client.post("/api/changes", data={"repo_path": str(tmp_path)})
    assert r.status_code == 422


def test_change_input_validation(client: TestClient) -> None:
    z = ("v.zip", _zip(USERS_V1), "application/zip")
    assert client.post("/api/changes", data={"options": STATIC}).status_code == 422  # nothing
    assert client.post("/api/changes", files={"before": z}).status_code == 422  # one ZIP only
    both = client.post("/api/changes", files={"before": z, "after": z}, data={"repo_path": "."})
    assert both.status_code == 422
    not_zip = {"before": ("a.py", b"x = 1\n", "text/x-python"), "after": z}
    assert client.post("/api/changes", files=not_zip).status_code == 415
    empty = {"before": ("a.zip", b"", "application/zip"), "after": z}
    assert client.post("/api/changes", files=empty).status_code == 422
    bad_opts = client.post(
        "/api/changes", files={"before": z, "after": z}, data={"options": json.dumps({"mode": 1})}
    )
    assert bad_opts.status_code == 422
    assert client.get("/api/reviews").json() == []  # rejected uploads leave no jobs behind

"""Dashboard backend: every route, happy paths and rejections (offline: static mode + mock LLM)."""

from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from marl_agents.api import JobManager, create_app
from marl_agents.api.app import safe_filename
from marl_agents.api.jobs import JobInfo, JobStatus, ReviewOptions
from marl_agents.config import Settings
from tests.conftest import PLANTED

STATIC = json.dumps({"mode": "static_only"})
CODE = "import os\n\ndef run(cmd):\n    return os.system(cmd)\n"


@pytest.fixture
def paths(tmp_path: Path) -> dict[str, Path]:
    return {
        "jobs": tmp_path / "jobs",
        "results": tmp_path / "results",
        "dist": tmp_path / "dist",
    }


@pytest.fixture
def client(settings: Settings, paths: dict[str, Path]):  # type: ignore[no-untyped-def]
    app = create_app(settings, paths["jobs"], paths["results"], paths["dist"])
    with TestClient(app) as c:
        yield c


def wait_done(client: TestClient, job_id: str, timeout: float = 60) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/reviews/{job_id}").json()
        if body["job"]["status"] in ("done", "failed"):
            return body
        time.sleep(0.1)
    raise AssertionError(f"review {job_id} did not finish")


def planted_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for p in PLANTED.rglob("*"):
            if p.is_file():
                zf.write(p, Path("planted-main") / p.relative_to(PLANTED))
    return buf.getvalue()


# ---- health & LLM ----------------------------------------------------------------------------------


def test_health(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["jobs"] == 0


def test_llm_status_with_mock_is_not_ready_and_never_leaks_keys(client: TestClient) -> None:
    body = client.get("/api/llm/status?probe=true").json()
    assert (
        body["provider"] == "mock" and body["ready"] is False and "static analysis" in body["error"]
    )
    assert "probe" not in body  # no probe when not ready
    assert not any("key" in k.lower() and "configured" not in k.lower() for k in body)


def test_llm_status_reports_missing_groq_key(settings: Settings, paths: dict[str, Path]) -> None:
    settings.llm.provider, settings.llm.model = "groq", "some-model"
    with TestClient(create_app(settings, paths["jobs"], paths["results"], paths["dist"])) as c:
        body = c.get("/api/llm/status").json()
        assert body["ready"] is False and "GROQ_API_KEY" in body["error"]
        assert c.get("/api/llm/models").status_code == 503


def test_llm_models_for_non_listing_provider(client: TestClient) -> None:
    assert client.get("/api/llm/models").json() == {"models": [], "default": None}


# ---- reviews: happy paths --------------------------------------------------------------------------


def test_snippet_review_end_to_end_with_reports(client: TestClient) -> None:
    r = client.post(
        "/api/reviews", data={"snippet": CODE, "snippet_name": "run.py", "options": STATIC}
    )
    assert r.status_code == 202
    job = r.json()
    assert job["status"] in ("queued", "running", "done") and job["source_type"] == "snippet"
    body = wait_done(client, job["id"])
    assert body["job"]["status"] == "done", body["job"]["error"]
    assert body["job"]["summary"]["total_findings"] == len(body["result"]["findings"]) > 0
    assert any(f["rule_id"] == "S605" for f in body["result"]["findings"])
    assert any("review started" in line for line in body["job"]["progress"])
    for fmt, ctype, magic in [
        ("json", "application/json", b"{"),
        ("md", "text/markdown", b"# Code Review Report"),
        ("pdf", "application/pdf", b"%PDF"),
    ]:
        rep = client.get(f"/api/reviews/{job['id']}/report/{fmt}")
        assert rep.status_code == 200 and rep.headers["content-type"].startswith(ctype)
        assert rep.content.startswith(magic)
        assert f"run-review.{fmt}" in rep.headers["content-disposition"]
    assert client.get(f"/api/reviews/{job['id']}/report/exe").status_code == 404


def test_zip_upload_review(client: TestClient, paths: dict[str, Path]) -> None:
    r = client.post(
        "/api/reviews",
        files={"file": ("planted.zip", planted_zip(), "application/zip")},
        data={"options": STATIC},
    )
    assert r.status_code == 202 and r.json()["source_type"] == "zip"
    body = wait_done(client, r.json()["id"])
    summary = body["job"]["summary"]
    assert summary["files_analyzed"] == 5 and summary["security_issues"] >= 8
    assert summary["by_severity"]["critical"] >= 1
    # the uploaded (untrusted) archive is deleted once the review finishes
    assert not (paths["jobs"] / r.json()["id"] / "input").exists()


def test_python_file_upload_and_name_sanitizing(client: TestClient) -> None:
    r = client.post(
        "/api/reviews",
        files={"file": ("../../evil name.py", CODE.encode(), "text/x-python")},
        data={"options": STATIC},
    )
    assert r.status_code == 202 and r.json()["name"] == "evil_name.py"
    assert wait_done(client, r.json()["id"])["job"]["status"] == "done"


def test_llm_mode_uses_shared_provider_and_records_model(client: TestClient) -> None:
    ids = [
        client.post(
            "/api/reviews", data={"snippet": CODE, "options": json.dumps({"mode": "full"})}
        ).json()["id"]
        for _ in range(2)
    ]
    for job_id in ids:
        body = wait_done(client, job_id)
        assert body["job"]["status"] == "done" and body["job"]["provider"] == "mock"
        assert body["result"]["stats"]["llm_usage"]["calls"] == 1  # per-run delta, not cumulative


def test_history_and_delete(client: TestClient) -> None:
    job_id = client.post("/api/reviews", data={"snippet": CODE, "options": STATIC}).json()["id"]
    wait_done(client, job_id)
    history = client.get("/api/reviews").json()
    assert [j["id"] for j in history] == [job_id] and len(history[0]["progress"]) <= 1
    # the list view trims a COPY: the job's own log (and job.json) keep every line
    assert len(client.get(f"/api/reviews/{job_id}").json()["job"]["progress"]) > 2
    assert client.delete(f"/api/reviews/{job_id}").status_code == 204
    assert client.get(f"/api/reviews/{job_id}").status_code == 404
    assert client.delete(f"/api/reviews/{job_id}").status_code == 404


# ---- reviews: rejections ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "status"),
    [
        ({"data": {"options": STATIC}}, 422),  # nothing to review
        ({"data": {"snippet": "   ", "options": STATIC}}, 422),  # blank snippet
        (
            {
                "data": {"snippet": CODE, "options": STATIC},
                "files": {"file": ("a.py", b"x=1", "text/plain")},
            },
            422,
        ),
        (
            {"files": {"file": ("notes.txt", b"hello", "text/plain")}, "data": {"options": STATIC}},
            415,
        ),
        ({"files": {"file": ("empty.py", b"", "text/plain")}, "data": {"options": STATIC}}, 422),
        ({"data": {"snippet": CODE, "options": '{"mode": "turbo"}'}}, 422),
        ({"data": {"snippet": CODE, "options": "not json"}}, 422),
        ({"data": {"snippet": CODE, "options": '{"min_confidence": 5}'}}, 422),
    ],
)
def test_invalid_submissions_are_rejected(
    client: TestClient, kwargs: dict[str, Any], status: int
) -> None:
    assert client.post("/api/reviews", **kwargs).status_code == status
    assert client.get("/api/reviews").json() == []  # nothing half-created


def test_oversized_upload_is_rejected_and_cleaned(
    settings: Settings, paths: dict[str, Path]
) -> None:
    settings.ingestion.max_file_bytes = 100
    with TestClient(create_app(settings, paths["jobs"], paths["results"], paths["dist"])) as c:
        r = c.post("/api/reviews", files={"file": ("big.py", b"x = 1\n" * 100, "text/plain")})
        assert r.status_code == 413
        assert c.get("/api/reviews").json() == [] and not any(paths["jobs"].iterdir())


@pytest.mark.parametrize("bad", ["../etc", "ABCDEF123456", "zzz", "..%2F..%2Fjob"])
def test_unknown_or_malformed_ids_are_404(client: TestClient, bad: str) -> None:
    assert client.get(f"/api/reviews/{bad}").status_code == 404
    assert client.get(f"/api/reviews/{bad}/report/json").status_code == 404


def test_failed_review_reports_error(client: TestClient) -> None:
    job_id = client.post(
        "/api/reviews", data={"snippet": CODE, "options": json.dumps({"mode": "full"})}
    ).json()["id"]
    assert wait_done(client, job_id)["job"]["status"] == "done"  # mock LLM works
    broken = client.post(
        "/api/reviews",
        files={"file": ("bad.zip", b"PK-not-really-a-zip", "application/zip")},
        data={"options": STATIC},
    ).json()["id"]
    body = wait_done(client, broken)
    assert body["job"]["status"] == "failed" and "zip" in body["job"]["error"].lower()
    assert body["result"] is None


# ---- persistence -------------------------------------------------------------------------------------


def test_jobs_survive_restart_and_interrupted_jobs_are_marked(
    settings: Settings, paths: dict[str, Path]
) -> None:
    with TestClient(create_app(settings, paths["jobs"], paths["results"], paths["dist"])) as c:
        job_id = c.post("/api/reviews", data={"snippet": CODE, "options": STATIC}).json()["id"]
        wait_done(c, job_id)
    stale = JobInfo(
        id="abcdef123456",
        name="x.py",
        source_type="snippet",
        options=ReviewOptions(),
        status=JobStatus.RUNNING,
    )
    (paths["jobs"] / stale.id).mkdir()
    (paths["jobs"] / stale.id / "job.json").write_text(stale.model_dump_json(), encoding="utf-8")
    (paths["jobs"] / "not-a-job").mkdir()

    manager = JobManager(settings, paths["jobs"])
    assert manager.get(job_id).status is JobStatus.DONE and manager.result(job_id) is not None
    assert manager.get(stale.id).status is JobStatus.FAILED and "restarted" in (
        manager.get(stale.id).error or ""
    )
    manager.shutdown()


# ---- experiments ---------------------------------------------------------------------------------------


def _run(results: Path, name: str, metrics: dict[str, Any], meta: dict[str, Any]) -> None:
    d = results / name
    d.mkdir(parents=True)
    (d / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    (d / "meta.json").write_text(json.dumps({**meta, "sample_ids": ["a"] * 5}), encoding="utf-8")
    (d / "summary.md").write_text(f"# {name}\n", encoding="utf-8")


def test_experiments_list_and_detail(client: TestClient, paths: dict[str, Path]) -> None:
    _run(
        paths["results"],
        "20260101T000000Z_planted_full",
        {"detection": {"recall": 1.0, "recall_llm": 1.0, "defect_precision": 0.9}},
        {"llm_model": "m1"},
    )
    _run(
        paths["results"],
        "20260102T000000Z_codereviewer_cls_test_static_only_n10",
        {
            "task": "cls",
            "n_evaluated": 10,
            "default": {"accuracy": 0.5},
            "roc_auc": 0.6,
            "sensitivity_without_cross_hunk_rules": {"default": {"accuracy": 0.55}, "roc_auc": 0.7},
        },
        {},
    )
    _run(
        paths["results"],
        "20260103T000000Z_retrieval_src",
        {"n_queries": 3, "hashing": {"recall@10": 0.5, "mrr": 0.4}},
        {},
    )
    runs = client.get("/api/experiments").json()
    assert [r["headline"]["kind"] for r in runs] == ["retrieval", "codereviewer_cls", "planted"]
    assert runs[2]["model"] == "m1" and runs[2]["headline"]["defect_precision"] == 0.9
    assert runs[1]["headline"]["adj_roc_auc"] == 0.7 and runs[0]["headline"]["hashing_mrr"] == 0.4
    _run(
        paths["results"],
        "20260104T000000Z_hunkrisk_cls_test_n10",
        {
            "n_evaluated": 10,
            "base_rate": 0.4,
            "auc": {"hunk_risk": {"auc": 0.61}, "size_baseline": {"auc": 0.58}},
            "by_level": {"high": {"commented_rate": 0.7}, "low": {"commented_rate": 0.3}},
        },
        {},
    )
    _run(
        paths["results"],
        "20260105T000000Z_usefulness_codereviewer_msg_test_full_n4",
        {
            "n_judged": 8,
            "agent": {"relevance": {"mean": 3.5}, "informativeness": {"mean": 3.0}},
            "human": {"relevance": {"mean": 4.0}, "informativeness": {"mean": 2.5}},
        },
        {"llm_model": "judge"},
    )
    heads = {r["headline"]["kind"]: r["headline"] for r in client.get("/api/experiments").json()}
    assert heads["hunk_risk"]["auc_risk"] == 0.61 and heads["hunk_risk"]["high_commented"] == 0.7
    assert heads["usefulness"]["human_informativeness"] == 2.5 and heads["usefulness"]["n"] == 8
    detail = client.get("/api/experiments/20260101T000000Z_planted_full").json()
    assert detail["summary_md"].startswith("# 2026") and "sample_ids" not in detail["meta"]
    assert client.get("/api/experiments/..%2Fsecrets").status_code == 404
    assert client.get("/api/experiments/nope").status_code == 404


# ---- dashboard hosting -----------------------------------------------------------------------------------


def test_spa_hosting(client: TestClient, paths: dict[str, Path]) -> None:
    assert "not built yet" in client.get("/").json()["message"]
    (paths["dist"] / "assets").mkdir(parents=True)
    (paths["dist"] / "index.html").write_text("<html>dashboard</html>", encoding="utf-8")
    (paths["dist"] / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    assert "dashboard" in client.get("/").text
    assert "dashboard" in client.get("/reviews/abc").text  # client-side route -> index.html
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/api/does-not-exist").status_code == 404
    assert "dashboard" in client.get("/../../etc/passwd").text  # never escapes dist


def test_safe_filename() -> None:
    assert safe_filename("..\\..\\a b$c.zip", "x") == "a_b_c.zip"
    assert safe_filename("...", "fallback") == "fallback"


def test_review_options_reach_the_agent_settings(client: TestClient) -> None:
    manager: JobManager = client.app.state.manager  # type: ignore[attr-defined]
    s = manager._job_settings(ReviewOptions(mode="full", suggest_fixes=False, include_tests=True))
    assert (s.review.suggest_fixes, s.review.include_tests, s.review.mode) == (False, True, "full")
    default = manager.settings.review.suggest_fixes  # not given -> server config
    assert manager._job_settings(ReviewOptions()).review.suggest_fixes is default


# ---- provider chosen per review --------------------------------------------------------------------


def test_llm_status_for_ollama_reports_a_local_provider(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from marl_agents.llm.ollama import OllamaProvider

    monkeypatch.setattr(OllamaProvider, "ensure_model", lambda self: None)
    body = client.get("/api/llm/status?provider=ollama").json()
    assert body["provider"] == "ollama" and body["server_provider"] == "mock"
    assert body["ready"] is True and body["local"] is True and body["data_notice"] is None
    assert body["selectable_providers"] == ["gemini", "ollama"]


def test_llm_status_for_ollama_explains_a_missing_model(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from marl_agents.llm.base import LLMError
    from marl_agents.llm.ollama import OllamaProvider

    def missing(self: OllamaProvider) -> None:
        raise LLMError("Ollama model 'qwen2.5-coder:7b' is not installed.")

    monkeypatch.setattr(OllamaProvider, "ensure_model", missing)
    body = client.get("/api/llm/status?provider=ollama").json()
    assert body["ready"] is False and "not installed" in body["error"]


def test_unknown_provider_is_rejected(client: TestClient) -> None:
    assert client.get("/api/llm/status?provider=openai").status_code == 422


def test_review_options_choose_the_provider(settings: Settings, paths: dict[str, Path]) -> None:
    manager = JobManager(settings, paths["jobs"])
    s = manager._job_settings(ReviewOptions(provider="ollama", model="gemini-3.6-flash"))
    assert (s.llm.provider, s.llm.model) == ("ollama", "qwen2.5-coder:7b")  # foreign id replaced
    assert manager._job_settings(ReviewOptions()).llm.provider == settings.llm.provider

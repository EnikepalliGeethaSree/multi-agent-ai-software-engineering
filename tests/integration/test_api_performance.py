"""Performance routes, resume after a quota stop, and credentials staying on the server."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from marl_agents.api import create_app
from marl_agents.api.jobs import JobManager, JobStatus
from marl_agents.config import Settings
from marl_agents.llm import GenerationConfig, LLMResponse, Message, MockLLMProvider
from marl_agents.llm.base import QuotaExhaustedError

CODE = "\n\n".join(
    f"def f{i}(x):\n" + "\n".join(f"    a{n} = x + {n}" for n in range(120)) + "\n    return a0"
    for i in range(3)
)
STATIC = json.dumps({"mode": "static_only", "rag_enabled": False})
FULL = json.dumps({"mode": "full", "rag_enabled": False, "suggest_fixes": False})


class QuotaOnce(MockLLMProvider):
    """Spends its quota after one call until `refilled` is set, like a daily reset."""

    refilled = False

    def generate(
        self, messages: list[Message], config: GenerationConfig | None = None
    ) -> LLMResponse:
        if len(self.calls) >= 1 and not self.refilled:
            raise QuotaExhaustedError("quota reached, resume later", resets_at="2026-11-07T08:00Z")
        return super().generate(messages, config)


@pytest.fixture
def setup(settings: Settings, tmp_path: Path):  # type: ignore[no-untyped-def]
    settings.review.unit_cache = True
    settings.review.cache_dir = str(tmp_path / "cache")
    results = tmp_path / "results"
    results.mkdir()
    app = create_app(
        settings=settings,
        jobs_dir=tmp_path / "jobs",
        results_dir=results,
        frontend_dir=tmp_path / "none",
    )
    with TestClient(app) as client:
        yield client, app.state.manager, results


def wait(client: TestClient, job_id: str) -> dict:  # type: ignore[type-arg]
    for _ in range(600):
        job = client.get(f"/api/reviews/{job_id}").json()["job"]
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def post_review(client: TestClient, options: str = STATIC) -> str:
    r = client.post(
        "/api/reviews", data={"snippet": CODE, "snippet_name": "m.py", "options": options}
    )
    assert r.status_code == 202
    return r.json()["id"]


def test_review_gets_a_performance_record(setup) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = setup
    job_id = post_review(client)
    job = wait(client, job_id)
    assert job["performance"]["file_name"] == "m.py"
    listed = client.get("/api/performance/reviews").json()
    assert [r["review_id"] for r in listed] == [job_id]
    detail = client.get(f"/api/performance/reviews/{job_id}").json()
    assert detail["record"]["total_sec"] > 0 and detail["record"]["lines_of_code"] > 300
    assert detail["record"]["llm_inference_sec"] is None  # static only: not measured
    assert detail["spans"]


def test_unknown_review_and_benchmark_are_404(setup) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = setup
    assert client.get("/api/performance/reviews/aaaaaaaaaaaa").status_code == 404
    assert client.get("/api/performance/benchmarks/none").status_code == 404
    assert client.get("/api/performance/benchmarks/..%2Fsecret").status_code == 404
    assert client.post("/api/reviews/aaaaaaaaaaaa/resume").status_code == 404


def test_benchmark_history(setup) -> None:  # type: ignore[no-untyped-def]
    client, _, results = setup
    run = results / "20261106T000000Z_runtime_static_only_r5"
    run.mkdir()
    metrics = {"mode": "static_only", "repeats": 5, "results": [{"category": "small"}]}
    (run / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    (run / "meta.json").write_text(json.dumps({"started_at": "2026-11-06"}), encoding="utf-8")
    (run / "results.json").write_text(
        json.dumps({"metrics": metrics, "runs": [{"total_sec": 1.0}]}), encoding="utf-8"
    )
    other = results / "20261106T000000Z_planted_static_only"
    other.mkdir()
    (other / "metrics.json").write_text("{}", encoding="utf-8")
    history = client.get("/api/performance/benchmarks").json()
    assert [h["name"] for h in history] == [run.name]
    assert client.get(f"/api/performance/benchmarks/{run.name}").json()["runs"] == [
        {"total_sec": 1.0}
    ]


def test_before_after_endpoint_reports_missing_runs(setup) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = setup
    table = client.get("/api/evaluation/before-after").json()
    assert table["rows"] and all(r["improved"] is None for r in table["rows"])


def test_quota_stop_is_partial_and_resume_continues(setup, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client, manager, _ = setup
    llm = QuotaOnce()
    monkeypatch.setattr(JobManager, "provider_for", lambda _self, _s: llm)
    job_id = post_review(client, FULL)
    job = wait(client, job_id)
    assert job["status"] == "done" and job["resumable"] is True
    assert "quota reached" in job["error"]
    assert job["performance"]["status"] == "partial"
    units = client.get(f"/api/reviews/{job_id}/units").json()
    assert units["resumable"] and len(units["failed_units"]) == 2
    assert units["resets_at"]
    assert (manager.input_dir(job_id) / "request.json").is_file()  # kept to resume

    calls_before = len(llm.calls)
    llm.refilled = True
    assert client.post(f"/api/reviews/{job_id}/resume").status_code == 202
    job = wait(client, job_id)
    assert job["status"] == JobStatus.DONE and job["resumable"] is False
    assert job["error"] is None and job["performance"]["status"] == "complete"
    assert job["performance"]["units_from_cache"] == 1
    assert len(llm.calls) - calls_before == 2  # only the two units that were missing
    assert not manager.input_dir(job_id).exists()  # untrusted input is gone


def test_finished_review_cannot_be_resumed_and_keeps_no_input(setup) -> None:  # type: ignore[no-untyped-def]
    client, manager, _ = setup
    job_id = post_review(client)
    wait(client, job_id)
    assert client.post(f"/api/reviews/{job_id}/resume").status_code == 409
    assert not manager.input_dir(job_id).exists()


def test_partial_input_expires(setup, settings: Settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client, manager, _ = setup
    monkeypatch.setattr(JobManager, "provider_for", lambda _self, _s: QuotaOnce())
    job_id = post_review(client, FULL)
    wait(client, job_id)
    settings.review.resume_ttl_hours = -1
    reloaded = JobManager(settings, manager.jobs_dir)
    assert reloaded.get(job_id).resumable is False
    assert not reloaded.input_dir(job_id).exists()
    reloaded.shutdown()


def test_old_jobs_without_a_record_still_load(setup) -> None:  # type: ignore[no-untyped-def]
    client, manager, _ = setup
    job_id = post_review(client)
    wait(client, job_id)
    job_file = manager.jobs_dir / job_id / "job.json"
    data = json.loads(job_file.read_text(encoding="utf-8"))
    for key in ("performance", "resumable", "failed_units"):
        data.pop(key)
    job_file.write_text(json.dumps(data), encoding="utf-8")
    manager._jobs.clear()
    manager._load_existing()
    listed = client.get("/api/performance/reviews").json()
    assert listed[0]["review_id"] == job_id and listed[0]["total_sec"] is not None


def test_status_exposes_no_credentials(settings: Settings, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("google.genai")
    secret = "REDACTED"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    settings.llm.provider, settings.llm.model = "gemini", "gemini-x"
    app = create_app(
        settings=settings,
        jobs_dir=tmp_path / "j",
        results_dir=tmp_path,
        frontend_dir=tmp_path / "n",
    )
    with TestClient(app) as client:
        r = client.get("/api/llm/status")
    assert secret not in r.text
    body = r.json()
    assert body["provider"] == "gemini" and body["free_tier"] is True
    assert "Google" in body["data_notice"] and body["quota"]["requests_used"] == 0

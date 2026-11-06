"""Performance and comparison routes. Everything comes from saved reviews and saved runs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from marl_agents.api.jobs import JobInfo, JobManager
from marl_agents.core.performance import PerformanceRecord, from_stats

_RUN_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_RUNTIME = re.compile(r"_runtime_")


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _record(manager: JobManager, job: JobInfo) -> PerformanceRecord | None:
    """The saved record; reviews made before records existed are rebuilt from their stats."""
    if job.performance is not None:
        return job.performance
    if job.status.value != "done":
        return None
    result = manager.result(job.id)
    if result is None:
        return None
    return from_stats(
        result.stats,
        job.id,
        job.name,
        provider=job.provider,
        model=job.model,
        findings=len(result.findings),
    )


def add_performance_routes(app: FastAPI, manager: JobManager, results_dir: Path) -> None:
    def job_or_404(job_id: str) -> JobInfo:
        try:
            return manager.get(job_id)
        except KeyError as exc:
            raise HTTPException(404, "Review not found") from exc

    def benchmark_dirs() -> list[Path]:
        if not results_dir.is_dir():
            return []
        return sorted(
            (
                d
                for d in results_dir.iterdir()
                if d.is_dir() and _RUNTIME.search(d.name) and (d / "metrics.json").is_file()
            ),
            key=lambda d: d.name,
            reverse=True,
        )

    @app.get("/api/performance/reviews")
    def performance_reviews() -> list[dict[str, Any]]:
        out = []
        for job in manager.list():
            record = _record(manager, job)
            if record is not None:
                out.append(record.model_dump(mode="json", exclude={"llm_calls_detail"}))
        return out

    @app.get("/api/performance/reviews/{job_id}")
    def performance_review(job_id: str) -> dict[str, Any]:
        job = job_or_404(job_id)
        record = _record(manager, job)
        if record is None:
            raise HTTPException(404, "No performance record for this review yet")
        result = manager.result(job_id)
        timing = result.stats.get("timing") if result is not None else None
        spans = timing.get("spans", []) if isinstance(timing, dict) else []
        return {"record": record.model_dump(mode="json"), "spans": spans}

    @app.get("/api/performance/benchmarks")
    def benchmarks() -> list[dict[str, Any]]:
        out = []
        for d in benchmark_dirs():
            metrics, meta = _read(d / "metrics.json"), _read(d / "meta.json")
            out.append(
                {
                    "name": d.name,
                    "started_at": meta.get("started_at"),
                    "git_commit": meta.get("git_commit"),
                    "mode": metrics.get("mode"),
                    "rag": metrics.get("rag"),
                    "repeats": metrics.get("repeats"),
                    "pipeline_check_only": metrics.get("pipeline_check_only", False),
                    "conditions": metrics.get("conditions", {}),
                    "results": metrics.get("results", []),
                }
            )
        return out

    @app.get("/api/performance/benchmarks/{name}")
    def benchmark(name: str) -> dict[str, Any]:
        if not _RUN_NAME.match(name) or name not in {d.name for d in benchmark_dirs()}:
            raise HTTPException(404, "Benchmark run not found")
        data = _read(results_dir / name / "results.json")
        metrics = data.get("metrics") or _read(results_dir / name / "metrics.json")
        return {"name": name, "metrics": metrics, "runs": data.get("runs", [])}

    @app.get("/api/evaluation/before-after")
    def before_after_table() -> dict[str, Any]:
        from marl_agents.evaluation.comparison.before_after import before_after

        return before_after(results_dir).model_dump()

    @app.get("/api/reviews/{job_id}/units")
    def review_units(job_id: str) -> dict[str, Any]:
        job = job_or_404(job_id)
        p = job.performance
        return {
            "status": p.status if p is not None else job.status.value,
            "resumable": job.resumable,
            "failed_units": job.failed_units,
            "skipped_units": p.skipped_units if p is not None else None,
            "message": job.error,
            "resets_at": p.resets_at if p is not None else None,
        }

    @app.post("/api/reviews/{job_id}/resume", status_code=202)
    def resume_review(job_id: str) -> JobInfo:
        job_or_404(job_id)
        try:
            return manager.resume(job_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

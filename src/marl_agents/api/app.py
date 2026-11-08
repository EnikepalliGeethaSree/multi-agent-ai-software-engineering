"""FastAPI backend for the Code Review dashboard.

    python -m marl_agents.cli serve            # http://127.0.0.1:8000 (API + built dashboard)

Routes (all JSON unless noted):
    GET    /api/health
    GET    /api/llm/status[?probe=true]       provider/model/key status; probe = 1 tiny call
    GET    /api/llm/models                    models available to the API key (cached)
    GET    /api/reviews                       review history
    POST   /api/reviews                       multipart: file (.zip/.py) or snippet + options
    GET    /api/reviews/{id}                  job status + progress + full result when done
    GET    /api/reviews/{id}/report/{fmt}     download json | md | pdf | sarif
    DELETE /api/reviews/{id}
    POST   /api/changes                       review a change: before+after ZIPs, or (local only)
                                              repo_path + base/head/staged of a git repository
    GET    /api/experiments                   saved evaluation runs (headline metrics + config)
    GET    /api/experiments/{name}            one run: metrics, meta, summary markdown
    GET    /api/evaluation/summary            baseline comparison (configurations A-D, baselines)
Performance routes (api/performance.py):
    GET    /api/performance/reviews           one performance record per review
    GET    /api/performance/reviews/{id}      a review's record, with stage spans
    GET    /api/performance/benchmarks        saved file-size benchmark runs
    GET    /api/performance/benchmarks/{name} one benchmark: statistics and every run
    GET    /api/evaluation/before-after       original vs improved system, saved runs only
    GET    /api/reviews/{id}/units            review status and the units that were not reviewed
    POST   /api/reviews/{id}/resume           continue a partial review
"""

from __future__ import annotations

import ipaddress
import json
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ValidationError

from marl_agents import __doc__ as package_doc
from marl_agents.api.jobs import (
    STAGED_LABEL,
    WORKING_LABEL,
    ChangeSpec,
    JobInfo,
    JobManager,
    JobStatus,
    ReviewOptions,
)
from marl_agents.api.performance import add_performance_routes
from marl_agents.config import PROJECT_ROOT, Settings, load_settings
from marl_agents.core.schemas import AgentRequest, ReviewResult
from marl_agents.ingestion.changes import (
    ChangeError,
    changeset_from_git,
    changeset_from_zips,
    check_git_target,
)
from marl_agents.llm.base import LLMError, Message
from marl_agents.llm.classifier import read_metadata

MAX_SNIPPET_CHARS = 1_000_000
GEMINI_DATA_NOTICE = (
    "Code is sent to Google. On the free tier Google may use it to improve its products, so do "
    "not review confidential code."
)
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_RUN_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
MODELS_CACHE_S = 600
MEDIA = {
    "json": "application/json",
    "md": "text/markdown",
    "pdf": "application/pdf",
    "sarif": "application/sarif+json",
}
# Reading a git repository from the server's disk is only allowed for the local user: the request
# must come from loopback, name a loopback Host (defeats DNS rebinding) and carry this header
# (a custom header forces a CORS preflight, so other websites cannot send it).
LOCAL_HEADER = "x-marl-client"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}


class ReviewDetail(BaseModel):
    job: JobInfo
    result: ReviewResult | None = None


def safe_filename(name: str, default: str) -> str:
    base = Path(name.replace("\\", "/")).name
    cleaned = _SAFE_NAME.sub("_", base).strip("._")
    return cleaned[:120] or default


def is_local_request(request: Request) -> bool:
    client = request.client.host if request.client else ""
    try:
        loopback = ipaddress.ip_address(client).is_loopback
    except ValueError:
        loopback = client == "localhost"
    host = request.headers.get("host", "").lower()
    hostname = host if host.endswith("]") else host.rsplit(":", 1)[0]
    return loopback and hostname in LOCAL_HOSTS and bool(request.headers.get(LOCAL_HEADER))


def classifier_info(settings: Settings) -> dict[str, Any]:
    cfg = settings.classifier
    meta = read_metadata(Path(cfg.model_dir)) if cfg.model_dir else None
    return {"enabled": cfg.enabled, "mode": cfg.mode, "model_dir": cfg.model_dir, "metadata": meta}


RUN_STATES = ("complete", "partial", "failed", "skipped")


def _headline(name: str, metrics: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    """The few numbers worth showing in a table, per kind of run."""
    kind = name.split("_", 1)[-1]
    if kind.startswith("runtime"):
        groups = metrics.get("results") or []
        return {
            "kind": "runtime",
            "mode": metrics.get("mode"),
            "repeats": metrics.get("repeats"),
            "inputs": len(metrics.get("inputs") or []),
            **{s: sum(g.get(s, 0) for g in groups) for s in RUN_STATES},
        }
    if kind.startswith("gemini"):
        return {
            "kind": "gemini_smoke",
            "live_checks": metrics.get("live_checks"),
            "live_passed": metrics.get("live_passed"),
            "failed": len(metrics.get("failed") or []),
        }
    if kind.startswith("classifier"):
        primary = metrics.get("repo_disjoint", {})
        return {
            "kind": "classifier",
            "n": primary.get("n"),
            "roc_auc": primary.get("roc_auc"),
            "f1": primary.get("f1"),
            "accuracy": primary.get("accuracy"),
        }
    if kind.startswith("hunkrisk"):
        auc = metrics.get("auc", {})
        top = metrics.get("precision_at_top", {})
        return {
            "kind": "hunk_risk",
            "n": metrics.get("n_evaluated"),
            "base_rate": metrics.get("base_rate"),
            "auc_risk": auc.get("hunk_risk", {}).get("auc"),
            "auc_size": auc.get("size_baseline", {}).get("auc"),
            "p10_risk": (top.get("hunk_risk") or {}).get("10%"),
            "p10_size": (top.get("size_baseline") or {}).get("10%"),
            "high_commented": metrics.get("by_level", {}).get("high", {}).get("commented_rate"),
            "low_commented": metrics.get("by_level", {}).get("low", {}).get("commented_rate"),
        }
    if kind.startswith("usefulness"):
        a, h = metrics.get("agent", {}), metrics.get("human", {})
        return {
            "kind": "usefulness",
            "n": metrics.get("n_judged"),
            "agent_relevance": a.get("relevance", {}).get("mean"),
            "agent_informativeness": a.get("informativeness", {}).get("mean"),
            "human_relevance": h.get("relevance", {}).get("mean"),
            "human_informativeness": h.get("informativeness", {}).get("mean"),
        }
    if kind.startswith("timing"):
        results: dict[str, Any] = metrics.get("results") or {}
        first_input: dict[str, Any] = next(iter(results.values()), {})
        first: dict[str, Any] = first_input.get("configs", {})
        return {
            "kind": "timing",
            "repeats": metrics.get("repeats"),
            "inputs": len(results),
            **{
                f"{c}_total": (v.get("total_sec") or {}).get("median")
                for c, v in first.items()
                if isinstance(v, dict)
            },
        }
    if kind.startswith("ablation"):
        return {
            "kind": "ablation",
            "group_id": metrics.get("group_id"),
            "benchmark": metrics.get("benchmark"),
            "repeats": metrics.get("repeats"),
        }
    if name.split("_", 1)[-1].startswith("planted"):
        d = metrics.get("detection", {})
        return {
            "kind": "planted",
            "recall": d.get("recall"),
            "recall_llm": d.get("recall_llm"),
            "defect_precision": d.get("defect_precision"),
            "negative_fp": d.get("negative_file_false_positives"),
            "mean_line_error": d.get("mean_line_error"),
        }
    if "retrieval" in name:
        methods = {k: v for k, v in metrics.items() if isinstance(v, dict) and "recall@10" in v}
        return {
            "kind": "retrieval",
            "n_queries": metrics.get("n_queries"),
            **{f"{m}_recall@10": v.get("recall@10") for m, v in methods.items()},
            **{f"{m}_mrr": v.get("mrr") for m, v in methods.items()},
        }
    if metrics.get("task") == "cls":
        d, s = metrics.get("default", {}), metrics.get("sensitivity_without_cross_hunk_rules", {})
        return {
            "kind": "codereviewer_cls",
            "n": metrics.get("n_evaluated"),
            "accuracy": d.get("accuracy"),
            "precision": d.get("precision"),
            "f1": d.get("f1"),
            "roc_auc": metrics.get("roc_auc"),
            "adj_accuracy": s.get("default", {}).get("accuracy"),
            "adj_precision": s.get("default", {}).get("precision"),
            "adj_roc_auc": s.get("roc_auc"),
        }
    if metrics.get("task") == "msg":
        t = metrics.get("text_metrics", {}).get("title_fix", {})
        return {
            "kind": "codereviewer_msg",
            "n": metrics.get("n_evaluated"),
            "bleu4": t.get("bleu4_smoothed"),
            "rouge_l": t.get("rouge_l"),
            "chrf": t.get("chrf"),
            "coverage": metrics.get("comment_coverage"),
        }
    return {"kind": "other"}


def _experiment_info(run_dir: Path) -> dict[str, Any] | None:
    """Configuration of a saved run (A-D flags, model, sample counts) for the runs table."""
    from marl_agents.evaluation.runs import load_run

    run = load_run(run_dir)
    skipped = {"retrieval", "hunkrisk", "timing", "ablation", "usefulness", "runtime", "classifier"}
    if run is None or run.kind in skipped:
        return None
    c = run.configuration
    exp = run.experiment
    return {
        "configuration": None if c is None else c.model_dump(exclude={"description"}),
        "model": run.model,
        "samples": exp.get("sample_count") or (len(run.sample_ids) or None),
        "evaluated": run.metrics.get("n_evaluated", exp.get("n_evaluated")),
        "failed": run.metrics.get("n_failed", exp.get("n_failed")),
        "group_id": run.group_id,
        "repeat": exp.get("repeat"),
        "recorded": bool(exp),
    }


def create_app(
    settings: Settings | None = None,
    jobs_dir: Path | None = None,
    results_dir: Path | None = None,
    frontend_dir: Path | None = None,
    allow_local_git: bool = True,
) -> FastAPI:
    settings = settings or load_settings()
    jobs_dir = jobs_dir or PROJECT_ROOT / "data" / "jobs"
    results_dir = results_dir or PROJECT_ROOT / "experiments" / "results"
    frontend_dir = frontend_dir or PROJECT_ROOT / "frontend" / "dist"
    manager = JobManager(settings, jobs_dir)
    models_cache: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):  # type: ignore[no-untyped-def]
        yield
        manager.shutdown()

    app = FastAPI(title="Code Review Agent", version="0.1.0", lifespan=lifespan)
    app.state.manager = manager
    # Vite dev server (npm run dev) talks to the API from another port.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- health & LLM ------------------------------------------------------------------------

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "app": (package_doc or "").strip(),
            "jobs": len(manager.list()),
            "running": sum(1 for j in manager.list() if j.status is JobStatus.RUNNING),
            "local_git": allow_local_git,
        }

    @app.get("/api/llm/status")
    def llm_status(probe: bool = False) -> dict[str, Any]:
        llm = settings.llm
        info: dict[str, Any] = {
            "provider": llm.provider,
            "model": llm.model,
            "requests_per_minute": llm.requests_per_minute,
            "tokens_per_minute": llm.tokens_per_minute,
            "requests_per_day": llm.requests_per_day,
            "tokens_per_day": llm.tokens_per_day,
            "free_tier": llm.provider == "gemini",
            "data_notice": GEMINI_DATA_NOTICE if llm.provider == "gemini" else None,
            "classifier": classifier_info(settings),
            "quota": None,
            "ready": False,
            "error": None,
        }
        try:
            provider = manager.provider_for(settings)
            info["ready"] = llm.provider != "mock"
            quota_status = getattr(provider, "quota_status", None)
            if quota_status is not None:
                info["quota"] = quota_status()
            if llm.provider == "mock":
                info["error"] = "No LLM configured (mock provider): only static analysis is useful."
            limiter = getattr(provider, "limiter", None)
            if limiter is not None:
                info["requests_per_minute"], info["tokens_per_minute"] = limiter.rpm, limiter.tpm
        except LLMError as exc:
            info["error"] = str(exc)
            return info
        if probe and info["ready"]:

            class Ping(BaseModel):
                status: str

            started = time.perf_counter()
            try:
                reply = provider.generate_structured(
                    [
                        Message(role="system", content="Reply with a JSON object only."),
                        Message(role="user", content='Return exactly this JSON: {"status": "ok"}'),
                    ],
                    Ping,
                )
                info["probe"] = {
                    "ok": reply.status == "ok",
                    "latency_ms": round(1000 * (time.perf_counter() - started)),
                }
            except LLMError as exc:
                info["probe"] = {"ok": False, "error": str(exc)}
        return info

    @app.get("/api/llm/models")
    def llm_models() -> dict[str, Any]:
        cached = models_cache.get("value")
        if cached and time.time() - models_cache["at"] < MODELS_CACHE_S:
            return dict(cached)
        try:
            provider = manager.provider_for(settings)
        except LLMError as exc:
            raise HTTPException(503, str(exc)) from exc
        list_models = getattr(provider, "list_models", None)
        if list_models is None:
            return {
                "models": [settings.llm.model] if settings.llm.model else [],
                "default": settings.llm.model,
            }
        try:
            models = list_models()
        except Exception as exc:
            raise HTTPException(502, f"Could not list models: {exc}") from exc
        value = {"models": models, "default": settings.llm.model}
        models_cache.update(value=value, at=time.time())
        return value

    # ---- reviews --------------------------------------------------------------------------------

    @app.get("/api/reviews")
    def list_reviews() -> list[JobInfo]:
        for job in (jobs := manager.list()):
            job.progress = job.progress[-1:]  # the list view needs only the latest line
        return jobs

    async def save_upload(file: UploadFile, target: Path, limit: int, job_id: str) -> None:
        """Stream an upload to disk with a size limit; discards the job on rejection."""
        size = 0
        with target.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    out.close()
                    manager.discard(job_id)
                    raise HTTPException(
                        413, f"File is larger than the {limit // (1024 * 1024)} MB limit."
                    )
                out.write(chunk)
        if size == 0:
            manager.discard(job_id)
            raise HTTPException(422, f"The uploaded file {target.name!r} is empty.")

    def parse_options(options: str) -> ReviewOptions:
        try:
            return ReviewOptions.model_validate_json(options or "{}")
        except ValidationError as exc:
            raise HTTPException(422, f"Invalid options: {exc.errors()[0]['msg']}") from exc

    @app.post("/api/reviews", status_code=202)
    async def create_review(
        file: UploadFile | None = File(default=None),  # noqa: B008 - FastAPI dependency
        snippet: str | None = Form(default=None),
        snippet_name: str = Form(default="snippet.py"),
        options: str = Form(default="{}"),
    ) -> JobInfo:
        opts = parse_options(options)
        extra = {"failing_test": opts.failing_test} if opts.failing_test else {}
        has_file = file is not None and bool(file.filename)
        if has_file == bool(snippet and snippet.strip()):
            raise HTTPException(422, "Provide exactly one of: a .zip/.py file, or a code snippet.")

        if not has_file:
            assert snippet is not None
            if len(snippet) > MAX_SNIPPET_CHARS:
                raise HTTPException(413, "Snippet is too large (max 1,000,000 characters).")
            name = safe_filename(snippet_name, "snippet.py")
            if not name.endswith(".py"):
                name += ".py"
            job = manager.new_job(name, "snippet", opts)
            request = AgentRequest(snippet=snippet, snippet_filename=name, options=extra)
            return manager.submit(job, request)

        assert file is not None and file.filename
        name = safe_filename(file.filename, "upload")
        suffix = Path(name).suffix.lower()
        if suffix not in {".zip", ".py"}:
            raise HTTPException(415, "Upload a .zip archive of a repository or a single .py file.")
        limit = (
            settings.ingestion.max_zip_bytes
            if suffix == ".zip"
            else settings.ingestion.max_file_bytes
        )
        job = manager.new_job(name, "zip" if suffix == ".zip" else "file", opts)
        target = manager.input_dir(job.id) / name
        await save_upload(file, target, limit, job.id)
        if suffix == ".py":
            code = target.read_bytes().decode("utf-8", errors="replace")
            request = AgentRequest(snippet=code, snippet_filename=name, options=extra)
        else:
            request = AgentRequest(repo_path=str(target), options=extra)
        return manager.submit(job, request)

    @app.post("/api/changes", status_code=202)
    async def create_change_review(
        request: Request,
        before: UploadFile | None = File(default=None),  # noqa: B008 - FastAPI dependency
        after: UploadFile | None = File(default=None),  # noqa: B008 - FastAPI dependency
        repo_path: str | None = Form(default=None),
        base: str | None = Form(default=None),
        head: str | None = Form(default=None),
        staged: bool = Form(default=False),
        options: str = Form(default="{}"),
    ) -> JobInfo:
        opts = parse_options(options)
        base_ref, head_ref = (base or "").strip() or None, (head or "").strip() or None
        has_zips = bool(before and before.filename) or bool(after and after.filename)
        if has_zips == bool(repo_path and repo_path.strip()):
            raise HTTPException(
                422, "Provide either two ZIP files (before and after) or a local git repository."
            )

        if repo_path:
            if not allow_local_git:
                raise HTTPException(403, "Reviewing a local git repository is disabled.")
            if not is_local_request(request):
                raise HTTPException(
                    403,
                    "A local git repository can only be reviewed from the dashboard on this "
                    "machine (http://localhost). Upload two ZIPs instead.",
                )
            if staged and head_ref:
                raise HTTPException(422, "Choose either 'staged' or a head reference, not both.")
            git_base = base_ref or ("main" if head_ref else "HEAD")
            try:
                top = check_git_target(repo_path.strip(), git_base, head_ref)
            except ChangeError as exc:
                raise HTTPException(422, str(exc)) from exc
            head_label = STAGED_LABEL if staged else (head_ref or WORKING_LABEL)
            spec = ChangeSpec(kind="git", base=git_base, head=head_label, repo_path=str(top))
            job = manager.new_job(f"{top.name}: {git_base} -> {head_label}", "change", opts, spec)
            return manager.submit_change(
                job, lambda s: changeset_from_git(top, git_base, head_ref, staged, s.ingestion)
            )

        if not (before and before.filename and after and after.filename):
            raise HTTPException(422, "Both the 'before' and the 'after' ZIP are required.")
        names = [safe_filename(f.filename or "", "version.zip") for f in (before, after)]
        if any(not n.lower().endswith(".zip") for n in names):
            raise HTTPException(415, "Both versions must be .zip archives.")
        spec = ChangeSpec(kind="zips", base=names[0], head=names[1])
        job = manager.new_job(f"{names[0]} -> {names[1]}", "change", opts, spec)
        paths: list[Path] = []
        for label, upload, name in (("before", before, names[0]), ("after", after, names[1])):
            (manager.input_dir(job.id) / label).mkdir(parents=True, exist_ok=True)
            target = manager.input_dir(job.id) / label / name
            await save_upload(upload, target, settings.ingestion.max_zip_bytes, job.id)
            paths.append(target)
        return manager.submit_change(
            job, lambda s: changeset_from_zips(paths[0], paths[1], s.ingestion)
        )

    @app.get("/api/reviews/{job_id}")
    def get_review(job_id: str) -> ReviewDetail:
        try:
            job = manager.get(job_id)
        except KeyError as exc:
            raise HTTPException(404, "Review not found") from exc
        result = manager.result(job_id) if job.status is JobStatus.DONE else None
        return ReviewDetail(job=job, result=result)

    @app.get("/api/reviews/{job_id}/report/{fmt}")
    def download_report(job_id: str, fmt: str) -> FileResponse:
        try:
            job = manager.get(job_id)
            path = manager.report_path(job_id, fmt)
        except KeyError as exc:
            raise HTTPException(404, "Review not found") from exc
        if path is None:
            raise HTTPException(404, f"No {fmt!r} report for this review")
        stem = Path(job.name).stem or "review"
        return FileResponse(path, media_type=MEDIA[fmt], filename=f"{stem}-review.{fmt}")

    @app.delete("/api/reviews/{job_id}", status_code=204)
    def delete_review(job_id: str) -> None:
        try:
            manager.delete(job_id)
        except KeyError as exc:
            raise HTTPException(404, "Review not found") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    # ---- evaluation runs -------------------------------------------------------------------

    def _run_dirs() -> list[Path]:
        if not results_dir.is_dir():
            return []
        return sorted(
            (d for d in results_dir.iterdir() if d.is_dir() and (d / "metrics.json").is_file()),
            key=lambda d: d.name,
            reverse=True,
        )

    def _read_json(path: Path) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    @app.get("/api/experiments")
    def list_experiments() -> list[dict[str, Any]]:
        runs = []
        for d in _run_dirs():
            metrics, meta = _read_json(d / "metrics.json"), _read_json(d / "meta.json")
            runs.append(
                {
                    "name": d.name,
                    "started_at": meta.get("started_at"),
                    "model": meta.get("llm_model"),
                    "provider": meta.get("llm_provider"),
                    "errors": meta.get("errors", 0),
                    "headline": _headline(d.name, metrics, meta),
                    "experiment": _experiment_info(d),
                }
            )
        return runs

    @app.get("/api/evaluation/summary")
    def evaluation_summary() -> dict[str, Any]:
        from marl_agents.evaluation.comparison import build_summary

        return build_summary(results_dir).model_dump()

    @app.get("/api/experiments/{name}")
    def get_experiment(name: str) -> dict[str, Any]:
        if not _RUN_NAME.match(name) or name not in {d.name for d in _run_dirs()}:
            raise HTTPException(404, "Run not found")
        d = results_dir / name
        meta = _read_json(d / "meta.json")
        meta.pop("sample_ids", None)  # can be thousands of ids; not useful in the UI
        summary = (
            (d / "summary.md").read_text(encoding="utf-8") if (d / "summary.md").is_file() else ""
        )
        return {
            "name": name,
            "metrics": _read_json(d / "metrics.json"),
            "meta": meta,
            "summary_md": summary,
        }

    add_performance_routes(app, manager, results_dir)

    # ---- built dashboard (frontend/dist), SPA fallback ----------------------------------------

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Any:
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        index = frontend_dir / "index.html"
        if not index.is_file():
            return JSONResponse(
                {
                    "message": "API is running. The dashboard is not built yet: "
                    "run `npm install && npm run build` in frontend/, or use `npm run dev`.",
                    "docs": "/docs",
                }
            )
        candidate = (frontend_dir / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(frontend_dir.resolve()):
            return FileResponse(candidate)
        return FileResponse(index)

    return app

"""Background review jobs for the dashboard: queue, run, persist, reload.

Each job lives in `data/jobs/<id>/`:
    job.json      status, options, progress log, summary (JobInfo)
    result.json   full ReviewResult
    review.json / review.md / review.pdf / review.sarif   downloadable reports
    performance.json     PerformanceRecord of the last run
Uploaded inputs are deleted as soon as the review finishes (untrusted code is not kept). The one
exception is a partial review, which keeps its input for `review.resume_ttl_hours` so it can resume
after a quota stop; `delete` and a finished resume remove it.
"""

from __future__ import annotations

import logging
import re
import shutil
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from marl_agents.agents.code_review import CodeReviewAgent
from marl_agents.config import Settings
from marl_agents.core.performance import PerformanceRecord, from_result, from_stats
from marl_agents.core.schemas import AgentRequest, ReviewResult
from marl_agents.ingestion.changes import (
    ChangeError,
    ChangeSet,
    changeset_from_git,
    changeset_from_zips,
)
from marl_agents.llm.base import LLMError, LLMProvider
from marl_agents.llm.classifier import ChangeClassifier, create_classifier
from marl_agents.llm.factory import create_provider
from marl_agents.reports import ReviewSummary, summarize, write_reports_timed

logger = logging.getLogger(__name__)

JOB_ID = re.compile(r"^[a-f0-9]{12}$")
MAX_PROGRESS_LINES = 500
REPORT_FILES = {
    "json": "review.json",
    "md": "review.md",
    "pdf": "review.pdf",
    "sarif": "review.sarif",
}
SourceType = Literal["zip", "file", "snippet", "change"]
Work = Callable[[CodeReviewAgent, Settings], ReviewResult]
REQUEST_FILE = "request.json"
STAGED_LABEL = "staged changes"
WORKING_LABEL = "working tree"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class ReviewOptions(BaseModel):
    mode: Literal["full", "static_only", "llm_only"] = "full"
    rag_enabled: bool = True
    structural_context: bool = True
    model: str | None = None
    min_confidence: float = Field(default=0.3, ge=0.0, le=1.0)
    include_tests: bool = False
    suggest_fixes: bool | None = None  # None: use the server config (review.suggest_fixes)


class ChangeSpec(BaseModel):
    """What a change review compares (shown in the dashboard)."""

    kind: Literal["git", "zips"]
    base: str
    head: str
    repo_path: str | None = None


class JobInfo(BaseModel):
    id: str
    name: str
    source_type: SourceType
    status: JobStatus = JobStatus.QUEUED
    options: ReviewOptions
    change: ChangeSpec | None = None
    provider: str | None = None
    model: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: list[str] = Field(default_factory=list)
    error: str | None = None
    summary: ReviewSummary | None = None
    performance: PerformanceRecord | None = None
    # A partial review with its input kept: POST /api/reviews/{id}/resume continues it.
    resumable: bool = False
    failed_units: list[str] = Field(default_factory=list)

    @property
    def duration_s(self) -> float | None:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None


class JobManager:
    """Runs reviews in a small thread pool; jobs and results are persisted to disk."""

    def __init__(self, settings: Settings, jobs_dir: Path, max_workers: int = 2) -> None:
        self.settings = settings
        self.jobs_dir = jobs_dir
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, JobInfo] = {}
        self._lock = threading.RLock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="review")
        # One provider per (provider, model): the rate limiter must be shared by all jobs.
        self._providers: dict[tuple[str, str | None], LLMProvider] = {}
        self._classifier: ChangeClassifier | None = None
        self._load_existing()

    # ---- persistence ------------------------------------------------------------------------

    def _dir(self, job_id: str) -> Path:
        if not JOB_ID.match(job_id):
            raise KeyError(job_id)
        return self.jobs_dir / job_id

    def _save(self, job: JobInfo) -> None:
        d = self._dir(job.id)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "job.json.tmp"
        tmp.write_text(job.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(d / "job.json")

    def _load_existing(self) -> None:
        for d in sorted(self.jobs_dir.iterdir()) if self.jobs_dir.exists() else []:
            f = d / "job.json"
            if not (d.is_dir() and JOB_ID.match(d.name) and f.is_file()):
                continue
            try:
                job = JobInfo.model_validate_json(f.read_text(encoding="utf-8"))
            except ValueError:
                logger.warning("Skipping unreadable job %s", d.name)
                continue
            if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
                # The server stopped while this job was running; it cannot be resumed.
                job.status = JobStatus.FAILED
                job.error = "Interrupted: the server was restarted while this review was running."
                job.finished_at = job.finished_at or datetime.now(UTC)
                shutil.rmtree(d / "input", ignore_errors=True)
                self._save(job)
            elif job.resumable and self._expired(job):
                job.resumable = False
                shutil.rmtree(d / "input", ignore_errors=True)
                self._save(job)
            self._jobs[job.id] = job

    def _expired(self, job: JobInfo) -> bool:
        limit = timedelta(hours=self.settings.review.resume_ttl_hours)
        return datetime.now(UTC) - (job.finished_at or job.created_at) > limit

    # ---- queries -----------------------------------------------------------------------------

    def list(self) -> list[JobInfo]:
        """Copies: callers may trim them (the history view keeps only the last progress line)."""
        with self._lock:
            jobs = [j.model_copy(deep=True) for j in self._jobs.values()]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    def get(self, job_id: str) -> JobInfo:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            return self._jobs[job_id].model_copy(deep=True)

    def result(self, job_id: str) -> ReviewResult | None:
        f = self._dir(job_id) / "result.json"
        if not f.is_file():
            return None
        return ReviewResult.model_validate_json(f.read_text(encoding="utf-8"))

    def report_path(self, job_id: str, fmt: str) -> Path | None:
        name = REPORT_FILES.get(fmt)
        if name is None:
            return None
        path = self._dir(job_id) / name
        return path if path.is_file() else None

    def delete(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
                raise ValueError("A running review cannot be deleted")
            del self._jobs[job_id]
        shutil.rmtree(self._dir(job_id), ignore_errors=True)

    # ---- submission ------------------------------------------------------------------------

    def new_job(
        self,
        name: str,
        source_type: SourceType,
        options: ReviewOptions,
        change: ChangeSpec | None = None,
    ) -> JobInfo:
        job = JobInfo(
            id=uuid.uuid4().hex[:12],
            name=name,
            source_type=source_type,
            options=options,
            change=change,
        )
        (self._dir(job.id) / "input").mkdir(parents=True, exist_ok=True)
        return job

    def discard(self, job_id: str) -> None:
        """Remove a job that was created but never submitted (e.g. upload rejected)."""
        with self._lock:
            self._jobs.pop(job_id, None)
        shutil.rmtree(self._dir(job_id), ignore_errors=True)

    def input_dir(self, job_id: str) -> Path:
        return self._dir(job_id) / "input"

    def submit(self, job: JobInfo, request: AgentRequest) -> JobInfo:
        """Review a whole repository / file / snippet."""
        self._remember_request(job, request)
        return self._enqueue(job, lambda agent, _settings: agent.run(request))

    def _remember_request(self, job: JobInfo, request: AgentRequest) -> None:
        """Kept in input/ with the upload, and deleted with it unless the review ends partial."""
        path = self.input_dir(job.id) / REQUEST_FILE
        path.write_text(request.model_dump_json(), encoding="utf-8")

    def resume(self, job_id: str) -> JobInfo:
        """Run a partial review again. Finished units come from the unit cache, not the LLM."""
        job = self.get(job_id)
        if not job.resumable:
            raise ValueError("This review cannot be resumed")
        work = self._resume_work(job)
        with self._lock:
            live = self._jobs[job_id]
            live.status = JobStatus.QUEUED
            live.error = None
            live.resumable = False
            live.finished_at = None
            self._save(live)
        settings = self._job_settings(job.options)
        self._pool.submit(self._run, job_id, work, settings)
        return self.get(job_id)

    def _resume_work(self, job: JobInfo) -> Work:
        change = job.change
        if change is None:
            path = self.input_dir(job.id) / REQUEST_FILE
            if not path.is_file():
                raise ValueError("The input of this review is gone")
            request = AgentRequest.model_validate_json(path.read_text(encoding="utf-8"))
            return lambda agent, _settings: agent.run(request)

        def rebuild(settings: Settings) -> ChangeSet:
            if change.kind == "git" and change.repo_path:
                head = None if change.head in (WORKING_LABEL, STAGED_LABEL) else change.head
                return changeset_from_git(
                    Path(change.repo_path),
                    change.base,
                    head,
                    change.head == STAGED_LABEL,
                    settings.ingestion,
                )
            root = self.input_dir(job.id)
            before = next((root / "before").glob("*.zip"))
            after = next((root / "after").glob("*.zip"))
            return changeset_from_zips(before, after, settings.ingestion)

        return self._change_work(rebuild)

    def submit_change(self, job: JobInfo, make_change: Callable[[Settings], ChangeSet]) -> JobInfo:
        """Review a code change. `make_change` builds the ChangeSet inside the worker thread."""
        return self._enqueue(job, self._change_work(make_change))

    @staticmethod
    def _change_work(make_change: Callable[[Settings], ChangeSet]) -> Work:
        def work(agent: CodeReviewAgent, settings: Settings) -> ReviewResult:
            from marl_agents.agents.code_review.change_review import review_change

            change = make_change(settings)
            try:
                return review_change(agent, change)
            finally:
                change.cleanup()

        return work

    def _enqueue(self, job: JobInfo, work: Work) -> JobInfo:
        settings = self._job_settings(job.options)
        if job.options.mode != "static_only":
            job.provider = settings.llm.provider
            job.model = settings.llm.model
        with self._lock:
            self._jobs[job.id] = job
            self._save(job)
        self._pool.submit(self._run, job.id, work, settings)
        return job

    def _job_settings(self, options: ReviewOptions) -> Settings:
        s = self.settings.model_copy(deep=True)
        s.review.mode = options.mode
        s.review.min_confidence = options.min_confidence
        s.review.include_tests = options.include_tests
        if options.suggest_fixes is not None:
            s.review.suggest_fixes = options.suggest_fixes
        s.rag.enabled = options.rag_enabled
        s.rag.structural_context = options.structural_context
        if options.model:
            s.llm.model = options.model
        return s

    def provider_for(self, settings: Settings) -> LLMProvider:
        key = (settings.llm.provider, settings.llm.model)
        with self._lock:
            if key not in self._providers:
                self._providers[key] = create_provider(settings.llm)
            return self._providers[key]

    def classifier_for(self, settings: Settings) -> ChangeClassifier | None:
        """Loaded once: a model takes seconds to load and is shared by all reviews."""
        if not settings.classifier.enabled or settings.review.mode == "static_only":
            return None
        with self._lock:
            if self._classifier is None:
                self._classifier = create_classifier(settings.classifier)
            return self._classifier

    def _update(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for k, v in changes.items():
                setattr(job, k, v)
            self._save(job)

    def _progress(self, job_id: str, message: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.progress.append(f"{datetime.now(UTC):%H:%M:%S} {message}")
            job.progress = job.progress[-MAX_PROGRESS_LINES:]
            self._save(job)

    def _run(
        self,
        job_id: str,
        work: Work,
        settings: Settings,
    ) -> None:
        self._update(job_id, status=JobStatus.RUNNING, started_at=datetime.now(UTC))
        self._progress(job_id, "review started")
        agent: CodeReviewAgent | None = None
        keep_input = False
        try:
            llm = None if settings.review.mode == "static_only" else self.provider_for(settings)
            agent = CodeReviewAgent(
                llm,
                settings=settings,
                progress=lambda m: self._progress(job_id, m),
                classifier=self.classifier_for(settings),
            )
            result = work(agent, settings)
            self._progress(job_id, "writing reports (JSON, Markdown, PDF, SARIF)")
            d = self._dir(job_id)
            write_reports_timed(result, d, tuple(REPORT_FILES))
            # after the reports, so result.json carries the full timing (incl. report generation)
            (d / "result.json").write_text(result.model_dump_json(), encoding="utf-8")
            keep_input = result.stats.get("review_status") == "partial"
            quota = result.stats.get("quota")
            self._update(
                job_id,
                status=JobStatus.DONE,
                summary=summarize(result),
                finished_at=datetime.now(UTC),
                performance=from_result(result, job_id, self.get(job_id).name),
                resumable=keep_input,
                failed_units=list(result.stats.get("units_failed_list", [])),
                error=quota.get("message") if isinstance(quota, dict) else None,
            )
            self._progress(job_id, f"done: {len(result.findings)} findings")
            if keep_input:
                self._progress(job_id, "partial review: some units were not reviewed; resumable")
        except LLMError as exc:
            self._fail(job_id, f"LLM error: {exc}", agent)
        except ChangeError as exc:
            self._fail(job_id, str(exc), agent)
        except Exception as exc:
            logger.exception("Review job %s failed", job_id)
            self._fail(job_id, f"{type(exc).__name__}: {exc}", agent)
        finally:
            if not keep_input:
                shutil.rmtree(self._dir(job_id) / "input", ignore_errors=True)

    def _fail(self, job_id: str, message: str, agent: CodeReviewAgent | None = None) -> None:
        # What was measured before the failure is kept: a crash must not erase its timing.
        stats = agent.partial_stats() if agent is not None else {}
        job = self.get(job_id)
        performance = (
            from_stats(stats, job_id, job.name, provider=job.provider, model=job.model,
                       message=message)
            if stats
            else None
        )  # fmt: skip
        self._update(
            job_id,
            status=JobStatus.FAILED,
            error=message,
            finished_at=datetime.now(UTC),
            performance=performance,
        )
        self._progress(job_id, f"failed: {message}")

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

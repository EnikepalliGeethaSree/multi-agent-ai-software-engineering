"""Bug Detection Agent on BugsInPy. Reads code; never runs a project's code or tests.

    python -m marl_agents.cli eval-bugs audit --split dev
    python -m marl_agents.cli eval-bugs localization --limit 10 --config configs/gemini.yaml
    python -m marl_agents.cli eval-bugs detection --split test --limit 30 --final

Two tracks (docs/bug-detection-agent.md):

- Localization: from the failing test's source, rank the repository's functions at the buggy commit.
- Detection: show the changed function, buggy and fixed, in separate requests with the same project
  around it. A repository scan cannot measure precision: BugsInPy labels one bug per commit, so an
  unmatched finding is not proven false. The fixed function is the negative.

Free-tier quota is small, so a run may take days. Finished samples go to a ledger keyed by task,
split, seed, model and prompt versions. Running the same command again continues from there, and a
prompt change starts a new ledger, so results from two prompts can never mix. A saved run always
reports everything finished so far and says how much is left.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tempfile
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from marl_agents.agents.bug_detection import BugDetectionAgent
from marl_agents.agents.bug_detection.agent import DEFECT_CATEGORIES
from marl_agents.agents.bug_detection.prompts import prompt_versions
from marl_agents.config import PROJECT_ROOT, Settings
from marl_agents.core.schemas import AgentRequest, Finding, SuspectFunction
from marl_agents.evaluation.configurations import (
    CONFIGURATIONS,
    apply_configuration,
    experiment_metadata,
)
from marl_agents.evaluation.datasets.bugsinpy import (
    BugsInPySample,
    is_small_fix,
    iter_bugs,
    ordered_candidates,
)
from marl_agents.evaluation.datasets.bugsinpy_repo import (
    BugRepoCache,
    DiskSpaceError,
    IneligibleBug,
    ResolvedBug,
    resolve_bug,
)
from marl_agents.evaluation.recorder import RunRecorder
from marl_agents.evaluation.runners import bug_scoring as scoring
from marl_agents.findings.confidence import priority
from marl_agents.ingestion import Repository, load_directory
from marl_agents.ingestion.models import FileKind
from marl_agents.llm.base import LLMProvider, QuotaExhaustedError, Usage
from marl_agents.parsing.python_ast import SymbolKind
from marl_agents.parsing.repo_index import RepoIndex

logger = logging.getLogger(__name__)

Task = Literal["localization", "detection"]
Row = dict[str, Any]
Progress = Callable[[str], None]
LINE_TOLERANCE = 2
# Bump when code changes what a sample's result would be: saved rows are then not reused.
HARNESS_VERSION = 4
ALL_RANKS = 100_000
SAVED_RANKS = 20
DEFAULT_CONFIGURATIONS = ("static_only", "llm_only", "static_llm", "static_llm_rag")


class BugEvalOptions(BaseModel):
    task: Task
    split: str = "dev"
    limit: int = 10  # small on purpose: a forgotten --limit must not spend a day's quota
    seed: int = 42
    configurations: list[str] = list(DEFAULT_CONFIGURATIONS)
    max_llm_calls: int | None = None
    bug_type_files: list[Path] = []


class QuotaStop(Exception):
    """The LLM quota ran out; finished work is kept and the command can be run again."""


def eval_settings(base: Settings, configuration: str) -> Settings:
    """One configuration, with everything else identical and nothing that varies run to run."""
    s = apply_configuration(base, configuration)
    s.review.suggest_fixes = False  # extra requests that no metric here uses
    s.review.type_check = False  # mypy needs each old project's dependencies
    s.review.concurrency = 1
    s.review.unit_cache = s.review.analysis_cache = False
    s.rag.vector_store = "memory"  # no collection per snapshot on a nearly full disk
    s.rag.persist_dir = None
    return s


def _cache_root(settings: Settings) -> Path:
    return PROJECT_ROOT / settings.datasets.cache_dir


# ---- which bugs ----------------------------------------------------------------------------------


def _load_resolution(path: Path) -> ResolvedBug | str | None:
    """A saved outcome: the bug, the reason it is unusable, or None if never checked."""
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return str(data["ineligible"]) if "ineligible" in data else ResolvedBug.model_validate(data)


def resolve_cached(sample: BugsInPySample, cache: BugRepoCache, folder: Path) -> ResolvedBug | str:
    """Resolve once; a network failure is retried next time, a permanent reason is not."""
    path = folder / f"{sample.sample_id}.json"
    saved = _load_resolution(path)
    if saved is not None:
        return saved
    try:
        bug = resolve_bug(sample, cache)
    except IneligibleBug as exc:
        if exc.reason != "commit_unavailable":
            path.write_text(json.dumps({"ineligible": exc.reason}), encoding="utf-8")
        return exc.reason
    path.write_text(bug.model_dump_json(), encoding="utf-8")
    return bug


def select_bugs(
    settings: Settings,
    cache: BugRepoCache,
    split: str,
    limit: int | None,
    seed: int,
    progress: Progress,
) -> tuple[list[ResolvedBug], dict[str, Any]]:
    """The first `limit` usable bugs in sampling order, and how many were passed over and why."""
    root = PROJECT_ROOT / settings.datasets.root
    everything = list(iter_bugs(root))
    pool = ordered_candidates(everything, split, seed)
    folder = _cache_root(settings) / "bugsinpy" / "resolved"
    folder.mkdir(parents=True, exist_ok=True)
    chosen: list[ResolvedBug] = []
    reasons: Counter[str] = Counter()
    checked = 0
    for sample in pool:
        if limit is not None and len(chosen) >= limit:
            break
        checked += 1
        outcome = resolve_cached(sample, cache, folder)
        if isinstance(outcome, str):
            reasons[outcome] += 1
            progress(f"{sample.sample_id}: not usable ({outcome})")
        else:
            chosen.append(outcome)
    audit = {
        "split": split,
        "seed": seed,
        "bugs_total": len(everything),
        "small_fix_total": sum(1 for b in everything if is_small_fix(b)),
        "pool": len(pool),
        "checked": checked,
        "usable": len(chosen),
        "ineligible": dict(reasons),
        "sample_ids": [b.sample_id for b in chosen],
    }
    return chosen, audit


# ---- ledger --------------------------------------------------------------------------------------


class Ledger:
    """Append-only record of finished (sample, configuration) work. Survives a quota stop."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.rows: dict[tuple[str, str, str], Row] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self.rows[self.key(row)] = row

    @staticmethod
    def key(row: Row) -> tuple[str, str, str]:
        return (row["sample_id"], row["configuration"], row.get("version", ""))

    def has(self, sample_id: str, configuration: str, version: str = "") -> bool:
        return (sample_id, configuration, version) in self.rows

    def add(self, row: Row) -> None:
        self.rows[self.key(row)] = row
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    def for_configuration(self, configuration: str, sample_ids: set[str]) -> list[Row]:
        rows = [
            r
            for r in self.rows.values()
            if r["configuration"] == configuration and r["sample_id"] in sample_ids
        ]
        return sorted(rows, key=lambda r: (r["sample_id"], r.get("version", "")))


def ledger_for(settings: Settings, options: BugEvalOptions) -> Ledger:
    llm = settings.llm
    identity = {
        "task": options.task,
        "split": options.split,
        "seed": options.seed,
        "provider": llm.provider,
        "model": llm.model,
        "temperature": llm.temperature,
        "harness": HARNESS_VERSION,
        "prompts": prompt_versions(),
        "bugs": settings.bugs.model_dump(),
        "rag": settings.rag.model_dump(),
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    name = f"{options.task}_{options.split}_{digest}.jsonl"
    return Ledger(_cache_root(settings) / "bugsinpy" / "ledger" / name)


# ---- one sample ----------------------------------------------------------------------------------


def _usage_fields(usage: Usage) -> dict[str, Any]:
    snap = usage.snapshot()
    return {
        "llm_calls": snap["calls"],
        "input_tokens": snap["input_tokens"],
        "output_tokens": snap["output_tokens"],
    }


def _count_functions(index: RepoIndex) -> int:
    return sum(
        1
        for path, module in index.modules.items()
        if index.repo.by_path[path].kind is FileKind.CODE
        for s in module.symbols
        if s.kind is not SymbolKind.CLASS
    )


def gold_names(bug: ResolvedBug, suspects: list[SuspectFunction]) -> set[str]:
    """The gold functions, plus any suspect containing a fixed line.

    A closure sits inside the function that defines it, so naming the outer one points at the
    right code. Without this, a correct answer about a nested function would score as a miss.
    """
    lines = [n for g in bug.gold for n in g.changed_lines]
    around = {
        f"{s.file}::{s.symbol}"
        for s in suspects
        if s.file == bug.file and any(s.start_line <= n <= s.end_line for n in lines)
    }
    return {f"{g.file}::{g.qualname}" for g in bug.gold} | around


def localize_sample(
    bug: ResolvedBug, repo: Repository, index: RepoIndex, config: str, settings: Settings,
    llm: LLMProvider | None, functions_in_repo: int,
) -> Row:  # fmt: skip
    row: Row = {
        "sample_id": bug.sample_id,
        "project": bug.sample.project,
        "configuration": config,
        "gold_file": bug.file,
        "functions_in_repo": functions_in_repo,
    }
    usage = Usage()
    agent = BugDetectionAgent(llm, settings=settings, progress=lambda _m: None)
    found = agent.localize(
        repo, index, bug.failing_test, bug.test_path, run_usage=usage, limit=ALL_RANKS
    )
    names = [f"{s.file}::{s.symbol}" for s in found.suspects]
    gold = gold_names(bug, found.suspects)
    rank = next((i for i, n in enumerate(names, start=1) if n in gold), None)
    return {
        **row,
        "gold_functions": sorted(gold),
        "status": "failed" if found.llm_failed else "complete",
        "gold_rank": rank,
        "ranked_functions": names[:SAVED_RANKS],
        "ranked_files": list(dict.fromkeys(s.file for s in found.suspects))[:SAVED_RANKS],
        "candidates": found.candidates_considered,
        "candidates_shown": found.candidates_shown,
        "ranked_by": found.ranked_by,
        "hypothesis": found.hypothesis,
        "errors": found.errors[:5],
        **_usage_fields(usage),
    }


def _near_gold(finding: Finding, bug: ResolvedBug) -> bool:
    lines = [n for g in bug.gold for n in g.changed_lines]
    return finding.file == bug.file and any(
        finding.start_line - LINE_TOLERANCE <= n <= finding.end_line + LINE_TOLERANCE for n in lines
    )


def detect_sample(
    bug: ResolvedBug, version: str, repo: Repository, index: RepoIndex, config: str,
    settings: Settings, llm: LLMProvider | None,
) -> Row:  # fmt: skip
    if version == "buggy":
        ranges = [(g.buggy_start, g.buggy_end) for g in bug.gold]
    else:
        ranges = [(g.fixed_start or 1, g.fixed_end or 1) for g in bug.gold]
    request = AgentRequest(repo_path=str(repo.root), options={"function_scope": {bug.file: ranges}})
    usage = Usage()
    agent = BugDetectionAgent(llm, settings=settings, progress=lambda _m: None)
    result = agent.review_repository(repo, index, request, run_usage=usage)
    if "quota" in result.stats:
        raise QuotaStop(str(result.stats["quota"].get("message", "quota")))
    defects = [f for f in result.findings if f.category in DEFECT_CATEGORIES]
    failed = int(result.stats.get("units_failed", 0) or 0)
    return {
        "sample_id": bug.sample_id,
        "project": bug.sample.project,
        "configuration": config,
        "version": version,
        "status": "failed" if failed else "complete",
        "flagged": bool(defects),
        # A finding on the fixed function is a false positive wherever it points.
        "flagged_at_gold": any(_near_gold(f, bug) for f in defects)
        if version == "buggy"
        else bool(defects),
        "top_priority": max((priority(f) for f in defects), default=0.0),
        "n_findings": len(defects),
        "findings": [
            {
                "line": f.start_line,
                "category": str(f.category),
                "severity": str(f.severity),
                "title": f.title,
                "rule": f.rule_id,
                "sources": [str(s) for s in f.sources],
                "bug_type": str(f.bug.bug_type) if f.bug else None,
                "trigger": f.bug.trigger if f.bug else None,
            }
            for f in defects[:10]
        ],
        "llm_rejected": sum(result.stats.get("llm_rejected_by_reason", {}).values()),
        "errors": result.errors[:5],
        **_usage_fields(usage),
    }


# ---- the run -------------------------------------------------------------------------------------


class _Snapshot:
    """A bug's repository at one commit, on disk only while it is being evaluated."""

    def __init__(self, cache: BugRepoCache, bug: ResolvedBug, settings: Settings) -> None:
        self.cache, self.bug, self.settings = cache, bug, settings
        parent = _cache_root(settings) / "bugsinpy" / "snapshots"
        parent.mkdir(parents=True, exist_ok=True)
        self.dir = Path(tempfile.mkdtemp(prefix=bug.sample_id + "_", dir=parent))

    def load(self, version: str = "buggy") -> tuple[Repository, RepoIndex]:
        bug = self.bug
        files = [p for p in self.dir.iterdir()]
        if not files:
            self.cache.snapshot(
                bug.sample.project, bug.buggy_commit, self.dir, self.settings.ingestion
            )
            if bug.file in getattr(self.cache, "skipped_long_paths", []):
                # Never review a snapshot that lacks the file under test.
                raise IneligibleBug("path_too_long", bug.file)
        if version == "fixed":
            # Only the patched file differs, so both versions have the same project around them.
            text = self.cache.show(bug.sample.project, bug.fixed_commit, bug.file)
            if text is None:
                raise IneligibleBug("patched_file_missing", bug.file)
            (self.dir / bug.file).write_text(text, encoding="utf-8", newline="\n")
        repo = load_directory(self.dir, self.settings.ingestion)
        return repo, RepoIndex.build(repo)

    def close(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)


def _pending(bug: ResolvedBug, configs: list[str], ledger: Ledger, task: Task) -> list[Any]:
    versions = ("",) if task == "localization" else ("buggy", "fixed")
    return [(c, v) for c in configs for v in versions if not ledger.has(bug.sample_id, c, v)]


def _run_bug(
    bug: ResolvedBug,
    work: list[tuple[str, str]],
    options: BugEvalOptions,
    base: Settings,
    llm: LLMProvider | None,
    cache: BugRepoCache,
    ledger: Ledger,
) -> int:
    """Everything still missing for one bug. Returns LLM calls made."""
    snapshot = _Snapshot(cache, bug, base)
    spent = 0
    try:
        for version in dict.fromkeys(v for _c, v in work):
            repo, index = snapshot.load(version or "buggy")
            functions = _count_functions(index)
            for config in [c for c, v in work if v == version]:
                settings = eval_settings(base, config)
                needs_llm = CONFIGURATIONS[config].llm
                provider = llm if needs_llm else None
                try:
                    if options.task == "localization":
                        row = localize_sample(
                            bug, repo, index, config, settings, provider, functions
                        )
                    else:
                        row = detect_sample(bug, version, repo, index, config, settings, provider)
                except QuotaExhaustedError as exc:
                    raise QuotaStop(str(exc)) from exc
                ledger.add(row)
                spent += int(row.get("llm_calls", 0) or 0)
    finally:
        snapshot.close()
    return spent


def _write_runs(
    options: BugEvalOptions, base: Settings, bugs: list[ResolvedBug], audit: dict[str, Any],
    ledger: Ledger, stopped: str | None, recorder_dir: Path | None,
) -> list[Path]:  # fmt: skip
    ids = {b.sample_id for b in bugs}
    per_bug = 1 if options.task == "localization" else 2
    meta: dict[str, Any] = {
        "split": options.split,
        "seed": options.seed,
        "n_samples": len(bugs),
        "n_requested": options.limit,
        "provider": base.llm.provider,
    }
    rows_by_config: dict[str, list[Row]] = {}
    paths: list[Path] = []
    for config in options.configurations:
        rows = ledger.for_configuration(config, ids)
        if not rows:
            continue
        rows_by_config[config] = rows
        pending = len(ids) * per_bug - len(rows)
        settings = eval_settings(base, config)
        name = f"bugsinpy_{options.task}_{options.split}_{config}_n{len(ids)}"
        recorder = RunRecorder(name, settings, recorder_dir)
        for row in rows:
            recorder.prediction(row)
            if row["status"] != "complete":
                recorder.error(row["sample_id"], "; ".join(row.get("errors", []))[:300])
        score = (
            scoring.score_localization if options.task == "localization"
            else scoring.score_detection
        )  # fmt: skip
        metrics = score(rows)
        extra = {**meta, "pending": pending, "uses_llm": CONFIGURATIONS[config].llm}
        summary = (
            scoring.localization_summary if options.task == "localization"
            else scoring.detection_summary
        )(config, metrics, extra)  # fmt: skip
        experiment = experiment_metadata(
            settings,
            benchmark=f"bugsinpy_{options.task}",
            llm_used=CONFIGURATIONS[config].llm,
            sample_ids=sorted(ids),
            n_evaluated=sum(1 for r in rows if r["status"] == "complete"),
            n_failed=sum(1 for r in rows if r["status"] != "complete"),
            dataset="BugsInPy",
            split=options.split,
            seed=options.seed,
            limit=options.limit,
            evaluation_rules={
                "pool": "one source file, at most 10 changed lines, change inside a function",
                "failed_samples": "counted as wrong, never dropped (D22)",
                "line_tolerance": LINE_TOLERANCE,
            },
            analyzers=[
                a.name for a in BugDetectionAgent(None, settings=_static(settings)).analyzers
            ],
        )
        experiment["prompt_versions"] = prompt_versions() if CONFIGURATIONS[config].llm else {}
        experiment["agent"] = "bug_detection"
        paths.append(
            recorder.finish(
                {**metrics, "complete": pending == 0},
                summary,
                experiment=experiment,
                audit=audit,
                sample_ids=sorted(ids),
                pending=pending,
                stopped=stopped,
                ledger=ledger.path.name,
            )
        )
    if len(rows_by_config) > 1:
        paths.append(
            _write_comparison(options, base, ids, rows_by_config, meta, recorder_dir, per_bug)
        )
    return paths


def _static(settings: Settings) -> Settings:
    s = settings.model_copy(deep=True)
    s.review.mode = "static_only"
    return s


def _write_comparison(
    options: BugEvalOptions, base: Settings, ids: set[str], rows_by_config: dict[str, list[Row]],
    meta: dict[str, Any], recorder_dir: Path | None, per_bug: int,
) -> Path:  # fmt: skip
    finished = {c: rows for c, rows in rows_by_config.items() if len(rows) == len(ids) * per_bug}
    compare = (
        scoring.compare_localization if options.task == "localization"
        else scoring.compare_detection
    )  # fmt: skip
    comparison = compare(rows_by_config)
    labels: dict[str, Any] = {}
    if options.bug_type_files:
        labels = _bug_type_breakdown(options, rows_by_config)
    name = f"bugsinpy_{options.task}_{options.split}_comparison_n{len(ids)}"
    recorder = RunRecorder(name, _static(base), recorder_dir)  # a table: it calls nothing itself
    extra = {**meta, "pending": sum(len(ids) * per_bug - len(r) for r in rows_by_config.values())}
    return recorder.finish(
        {
            "comparison": comparison,
            "configurations": list(rows_by_config),
            "finished_configurations": list(finished),
            "bug_types": labels,
        },
        scoring.comparison_summary(options.task, comparison, extra),
        sample_ids=sorted(ids),
    )


def read_type_labels(path: Path) -> dict[str, str]:
    import csv

    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return {r["sample_id"]: r["bug_type"].strip() for r in rows if r.get("bug_type", "").strip()}


def _bug_type_breakdown(
    options: BugEvalOptions, rows_by_config: dict[str, list[Row]]
) -> dict[str, Any]:
    agreement = scoring.type_agreement([read_type_labels(p) for p in options.bug_type_files])
    out: dict[str, Any] = {"n": agreement["n"], "kappa": agreement["kappa"]}
    if options.task == "localization":
        out["top_1_by_type"] = {
            c: scoring.localization_by_type(rows, agreement["agreed"])
            for c, rows in rows_by_config.items()
        }
    return out


def run_bug_evaluation(
    options: BugEvalOptions,
    settings: Settings,
    llm: LLMProvider | None,
    cache: BugRepoCache | None = None,
    progress: Progress = logger.info,
    recorder_dir: Path | None = None,
) -> list[Path]:
    """Run what is missing, then save everything finished so far."""
    cache = cache or BugRepoCache(_cache_root(settings))
    bugs, audit = select_bugs(settings, cache, options.split, options.limit, options.seed, progress)
    progress(f"{len(bugs)} usable bugs (of {options.limit} requested)")
    ledger = ledger_for(settings, options)
    spent = 0
    stopped: str | None = None
    per_config = 1 if options.task == "localization" else 2
    llm_cost = per_config * sum(1 for c in options.configurations if CONFIGURATIONS[c].llm)
    configs = options.configurations
    for i, bug in enumerate(bugs):
        # Rotating the order means drift over a long run does not always hit the same configuration.
        rotated = configs[i % len(configs) :] + configs[: i % len(configs)]
        work = _pending(bug, rotated, ledger, options.task)
        if not work:
            continue
        if options.max_llm_calls is not None and spent + llm_cost > options.max_llm_calls:
            stopped = f"--max-llm-calls {options.max_llm_calls} reached"
            break
        try:
            spent += _run_bug(bug, work, options, settings, llm, cache, ledger)
        except QuotaStop as exc:
            stopped = f"LLM quota: {exc}"[:300]
            break
        except DiskSpaceError as exc:
            stopped = str(exc)
            break
        progress(f"{i + 1}/{len(bugs)} {bug.sample_id}: done ({spent} LLM calls so far)")
    if stopped:
        progress(f"stopped: {stopped}. Run the same command again to continue.")
    return _write_runs(options, settings, bugs, audit, ledger, stopped, recorder_dir)


def run_audit(
    settings: Settings,
    split: str,
    seed: int,
    limit: int | None,
    cache: BugRepoCache | None = None,
    progress: Progress = logger.info,
    recorder_dir: Path | None = None,
) -> Path:
    """Check which bugs can be used. Fetches commits; makes no LLM call."""
    cache = cache or BugRepoCache(_cache_root(settings))
    _bugs, audit = select_bugs(settings, cache, split, limit, seed, progress)
    # Recorded as what it is: no LLM ran, whatever the configured default mode says.
    recorder = RunRecorder(f"bugsinpy_audit_{split}", _static(settings), recorder_dir)
    return recorder.finish(audit, scoring.audit_summary(audit), sample_ids=audit["sample_ids"])


def write_label_sheet(
    settings: Settings,
    split: str,
    seed: int,
    limit: int,
    out: Path,
    cache: BugRepoCache | None = None,
) -> Path:
    """A blank bug-type sheet for one rater. Each person fills in their own copy, alone."""
    import csv

    cache = cache or BugRepoCache(_cache_root(settings))
    bugs, _audit = select_bugs(settings, cache, split, limit, seed, logger.info)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["sample_id", "project", "file", "functions", "commit_url", "bug_type"])
        for bug in bugs:
            writer.writerow(
                [
                    bug.sample_id,
                    bug.sample.project,
                    bug.file,
                    "; ".join(g.qualname for g in bug.gold),
                    f"{bug.sample.github_url}/commit/{bug.fixed_commit}",
                    "",
                ]
            )
    return out

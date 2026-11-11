"""File-size performance benchmark: how long does a review take for small, medium, large files?

    python -m marl_agents.evaluation.benchmark_runtime --mode static_only --repeats 5
    python -m marl_agents.evaluation.benchmark_runtime --repeats 5 --max-llm-calls 200
    python -m marl_agents.evaluation.benchmark_runtime --resume experiments/results/<run>

Categories: small 1-100 lines, medium 101-1,000, large 1,001-5,000. Inputs default to real Python
files from the interpreter's standard library: they are always available, chosen by a fixed rule,
and identified by SHA-256 in the results. They are parsed and never run.

Control of variables: same machine and settings for every run; concurrency 1; files interleaved
round by round so drift hits every category alike; fix suggestions off; one untimed warm-up. Each
round has a cold run (empty caches, fresh vector store) followed by a warm run that may reuse them,
reported separately.

Free-tier quota: a run that hits the quota is recorded as failed, later LLM runs are recorded as
skipped, and `--resume` continues on another day. Failed and skipped runs never enter the timing
statistics, and their count is always shown.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import shutil
import sys
import tempfile
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean, median
from typing import Any

from pydantic import BaseModel

from marl_agents.agents.code_review import CodeReviewAgent
from marl_agents.config import Settings, load_settings
from marl_agents.core.performance import PerformanceRecord, from_result, from_stats
from marl_agents.core.schemas import AgentRequest
from marl_agents.core.timing import percentile
from marl_agents.evaluation.recorder import RunRecorder
from marl_agents.evaluation.runners.timing import hardware
from marl_agents.llm.base import LLMProvider, QuotaExhaustedError
from marl_agents.llm.factory import create_provider
from marl_agents.reports import write_reports_timed

logger = logging.getLogger(__name__)

CATEGORIES: dict[str, tuple[int, int]] = {
    "small": (1, 100),
    "medium": (101, 1000),
    "large": (1001, 5000),
}
REPORT_FORMATS = ("json", "md", "pdf", "sarif")
RUN_TYPES = ("cold", "warm")
NOT_MEASURED = ("failed", "skipped")
CSV_FIELDS = (
    "category", "file_name", "repeat", "run_type", "status", "provider", "model", "file_size_kb",
    "lines_of_code", "review_units", "failed_units", "skipped_units", "units_from_cache",
    "cache_hit_rate", "llm_calls", "llm_failed_calls", "input_tokens", "output_tokens",
    "thinking_tokens", "findings", "total_sec",
    "file_ingestion_sec", "parsing_sec", "ast_call_graph_sec", "static_analysis_sec",
    "rag_retrieval_sec", "rag_index_sec", "prompt_construction_sec", "llm_inference_sec",
    "llm_quota_wait_sec", "evidence_validation_sec", "dedup_severity_sec", "validation_sec",
    "report_generation_sec", "message",
)  # fmt: skip


class BenchmarkInput(BaseModel):
    category: str
    path: str
    name: str
    lines: int
    size_kb: float
    sha256: str


def line_count(path: Path) -> int:
    return len(path.read_bytes().splitlines())


def describe_input(path: Path, category: str) -> BenchmarkInput:
    raw = path.read_bytes()
    return BenchmarkInput(
        category=category,
        path=str(path),
        name=path.name,
        lines=len(raw.splitlines()),
        size_kb=round(len(raw) / 1024, 2),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def categorize(lines: int) -> str | None:
    return next((c for c, (lo, hi) in CATEGORIES.items() if lo <= lines <= hi), None)


def evenly_spaced(items: list[Any], k: int) -> list[Any]:
    """`k` items spread across a sorted list (a fixed rule, so the choice is reproducible)."""
    if len(items) <= k:
        return list(items)
    if k == 1:
        return [items[len(items) // 2]]
    return [items[round(i * (len(items) - 1) / (k - 1))] for i in range(k)]


def select_inputs(directory: Path, per_category: int = 3) -> list[BenchmarkInput]:
    """Top-level .py files of `directory`, bucketed by size, smallest to largest in each bucket."""
    buckets: dict[str, list[tuple[int, Path]]] = {c: [] for c in CATEGORIES}
    for path in sorted(directory.glob("*.py")):
        lines = line_count(path)
        category = categorize(lines)
        if category and not path.name.startswith("_") and lines >= 10:
            buckets[category].append((lines, path))
    chosen: list[BenchmarkInput] = []
    for category, files in buckets.items():
        for _, path in evenly_spaced(sorted(files), per_category):
            chosen.append(describe_input(path, category))
    return chosen


def stdlib_dir() -> Path:
    return Path(os.__file__).resolve().parent


def cache_hit_rate(row: dict[str, Any]) -> float | None:
    """Share of review units answered from the LLM cache. None when no units were measured."""
    units, cached = row.get("review_units"), row.get("units_from_cache")
    return round(cached / units, 4) if units and cached is not None else None


def run_settings(
    base: Settings, mode: str, rag: bool, cache_dir: Path, store: Path | None
) -> Settings:
    """The one configuration every measured run uses."""
    s = base.model_copy(deep=True)
    s.review.mode = mode  # type: ignore[assignment]
    s.review.concurrency = 1
    s.review.suggest_fixes = False
    s.review.unit_cache = True
    s.review.analysis_cache = True
    s.review.cache_dir = str(cache_dir)  # absolute, so it replaces the project-relative default
    s.rag.enabled = rag
    s.rag.vector_store = "chroma" if store is not None else "memory"
    s.rag.persist_dir = str(store) if store is not None else None
    return s


def review_file(
    settings: Settings, llm: LLMProvider | None, item: BenchmarkInput, out_dir: Path
) -> tuple[PerformanceRecord, bool]:
    """One timed review, request to reports. Returns the record and whether the quota ran out."""
    path = Path(item.path)
    agent = CodeReviewAgent(
        llm if settings.review.mode != "static_only" else None,
        settings=settings,
        progress=lambda _m: None,
    )
    code = path.read_bytes().decode("utf-8", errors="replace")
    try:
        result = agent.run(AgentRequest(snippet=code, snippet_filename=path.name))
        write_reports_timed(result, out_dir, REPORT_FORMATS)
    except QuotaExhaustedError as exc:
        return _failed(agent, item, str(exc), llm), True
    except Exception as exc:  # recorded as a failed experiment, never dropped
        logger.warning("Review of %s failed: %s", item.name, type(exc).__name__)
        return _failed(agent, item, f"{type(exc).__name__}: {exc}"[:300], llm), False
    record = from_result(result, path.name, path.name)
    if record.status == "partial" and not record.message:
        record.message = next((e for e in result.errors if e), "")[:300] or None
    return record, "quota" in result.stats


def _failed(
    agent: CodeReviewAgent, item: BenchmarkInput, message: str, llm: LLMProvider | None
) -> PerformanceRecord:
    return from_stats(
        agent.partial_stats(),
        item.name,
        item.name,
        provider=getattr(llm, "name", None),
        model=getattr(llm, "model", None),
        message=message,
    )


def _skipped(item: BenchmarkInput, reason: str, llm: LLMProvider | None) -> dict[str, Any]:
    return {
        "file_name": item.name,
        "status": "skipped",
        "message": reason,
        "provider": getattr(llm, "name", None),
        "model": getattr(llm, "model", None),
    }


def run_benchmark(
    base: Settings,
    llm: LLMProvider | None,
    inputs: list[BenchmarkInput],
    *,
    mode: str,
    rag: bool,
    repeats: int,
    recorder: RunRecorder,
    done: dict[tuple[str, int, str], dict[str, Any]] | None = None,
    max_llm_calls: int | None = None,
    progress: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    uses_llm = mode != "static_only"
    rows: list[dict[str, Any]] = []
    previous = done or {}
    calls = sum(int(r.get("llm_calls") or 0) for r in previous.values())
    stop_reason: str | None = None
    with tempfile.TemporaryDirectory(prefix="marl_runtime_", ignore_cleanup_errors=True) as tmp:
        tmp_dir = Path(tmp)
        warm_up = run_settings(base, "static_only", False, tmp_dir / "warmup", None)
        warm_up.review.analysis_cache = False
        review_file(warm_up, None, inputs[0], tmp_dir / "warmup_report")
        for rep in range(1, repeats + 1):
            for item in inputs:
                cache_dir = Path(tempfile.mkdtemp(prefix="cache_", dir=tmp_dir))
                store = Path(tempfile.mkdtemp(prefix="chroma_", dir=tmp_dir)) if rag else None
                for run_type in RUN_TYPES:
                    key = (item.name, rep, run_type)
                    if key in previous:
                        rows.append(previous[key])
                        continue
                    if uses_llm and max_llm_calls is not None and calls >= max_llm_calls:
                        stop_reason = f"--max-llm-calls {max_llm_calls} reached"
                    if stop_reason and uses_llm:
                        row = _skipped(item, stop_reason, llm)
                    else:
                        settings = run_settings(base, mode, rag, cache_dir, store)
                        record, quota = review_file(
                            settings, llm, item, tmp_dir / f"r{rep}_{item.name}_{run_type}"
                        )
                        row = record.model_dump(mode="json", exclude={"llm_calls_detail"})
                        row["llm_call_durations"] = record.llm_durations
                        calls += record.llm_calls or 0
                        if quota:
                            stop_reason = "LLM quota reached in an earlier run"
                    row.update(
                        cache_hit_rate=cache_hit_rate(row),
                        category=item.category,
                        repeat=rep,
                        run_type=run_type,
                        sha256=item.sha256,
                        measured_at=datetime.now(UTC).isoformat(),
                    )
                    rows.append(row)
                    recorder.prediction(row)
                    progress(
                        f"round {rep}/{repeats} {item.category:6} {item.name:24} {run_type} "
                        f"{row.get('status')}: {row.get('total_sec')}"
                    )
                if store is not None:
                    shutil.rmtree(store, ignore_errors=True)
    return rows


def _nums(rows: Iterable[dict[str, Any]], key: str) -> list[float]:
    return [float(r[key]) for r in rows if isinstance(r.get(key), int | float)]


def _mean(rows: list[dict[str, Any]], key: str) -> float | None:
    xs = _nums(rows, key)
    return round(fmean(xs), 4) if xs else None


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def aggregate(rows: list[dict[str, Any]], run_type: str, category: str) -> dict[str, Any]:
    """Statistics over complete runs only; failed, partial and skipped runs are counted apart."""
    group = [r for r in rows if r.get("run_type") == run_type and r.get("category") == category]
    ok = [r for r in group if r.get("status") == "complete"]
    totals = _nums(ok, "total_sec")
    files = sorted({r["file_name"] for r in group})
    return {
        "category": category,
        "run_type": run_type,
        "files": files,
        "runs": len(group),
        "complete": len(ok),
        "partial": sum(1 for r in group if r.get("status") == "partial"),
        "failed": sum(1 for r in group if r.get("status") == "failed"),
        "skipped": sum(1 for r in group if r.get("status") == "skipped"),
        "success_rate": round(len(ok) / len(group), 4) if group else None,
        "mean_sec": _rounded(fmean(totals)) if totals else None,
        "median_sec": _rounded(median(totals)) if totals else None,
        "p95_sec": _rounded(percentile(totals, 95)),
        "min_sec": _rounded(min(totals)) if totals else None,
        "max_sec": _rounded(max(totals)) if totals else None,
        "mean_llm_inference_sec": _mean(ok, "llm_inference_sec"),
        "mean_rag_retrieval_sec": _mean(ok, "rag_retrieval_sec"),
        "mean_static_analysis_sec": _mean(ok, "static_analysis_sec"),
        "mean_input_tokens": _mean(ok, "input_tokens"),
        "mean_output_tokens": _mean(ok, "output_tokens"),
        "mean_findings": _mean(ok, "findings"),
        "mean_cache_hit_rate": _mean(ok, "cache_hit_rate"),
        "mean_review_chunks": _mean(ok, "review_units"),
        "mean_lines": _mean(ok, "lines_of_code"),
        "mean_size_kb": _mean(ok, "file_size_kb"),
        "skipped_chunks": int(sum(_nums(group, "skipped_units"))),
    }


def metrics(
    rows: list[dict[str, Any]],
    inputs: list[BenchmarkInput],
    *,
    mode: str,
    rag: bool,
    repeats: int,
    llm: LLMProvider | None,
    settings: Settings,
) -> dict[str, Any]:
    uses_llm = mode != "static_only"
    mock = uses_llm and getattr(llm, "name", "") == "mock"
    return {
        "benchmark": "runtime",
        "mode": mode,
        "rag": rag,
        "repeats": repeats,
        "pipeline_check_only": mock,
        "inputs": [i.model_dump() for i in inputs],
        "results": [aggregate(rows, t, c) for c in CATEGORIES for t in RUN_TYPES],
        "conditions": {
            "provider": getattr(llm, "name", None) if uses_llm else None,
            "model": getattr(llm, "model", None) if uses_llm else None,
            "temperature": settings.llm.temperature if uses_llm else None,
            "date": datetime.now(UTC).date().isoformat(),
            "concurrency": 1,
            "chunking_max_unit_lines": settings.review.max_unit_lines,
            "embedding_model": settings.rag.embedding_model if rag else None,
            "rag_top_k": settings.rag.top_k if rag else None,
            "suggested_fixes": False,
            "hardware": hardware(),
            "api_conditions": (
                f"{llm.name} (provider reply cache off; per-run unit cache only); throttling "
                "appears in llm_quota_wait_sec"
            )
            if uses_llm and not mock and llm is not None
            else "no API used",
            "order": "interleaved: round -> file -> cold then warm",
        },
    }


def _fmt(value: Any) -> str:
    return "-" if value is None else (f"{value:.2f}" if isinstance(value, float) else str(value))


def summary_md(m: dict[str, Any]) -> str:
    c = m["conditions"]
    llm = f"{c['provider']} / {c['model']}" if c["provider"] else "none (static analysis only)"
    head = [
        "# Review time by file size",
        "",
        f"LLM: {llm}. Mode: {m['mode']}, RAG {'on' if m['rag'] else 'off'}. "
        f"{m['repeats']} rounds per file, concurrency 1, fixes off. Date {c['date']}. "
        f"API conditions: {c['api_conditions']}.",
        f"Hardware: {c['hardware']['platform']}, {c['hardware']['cpu_count']} CPUs, "
        f"Python {c['hardware']['python']}.",
    ]
    if m["pipeline_check_only"]:
        head += ["", "**Mock LLM: this checks the pipeline only. Do not report these times.**"]
    if m["mode"] == "static_only":
        head += ["", "No LLM was used, so these times exclude LLM inference and token use."]
    rows = [
        "",
        "| Size | Run | Complete | Partial/failed/skipped | Mean | Median | P95 | Min | Max | "
        "LLM | RAG | Static | Tokens in | Tokens out | Findings | Chunks |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in m["results"]:
        rows.append(
            f"| {r['category']} | {r['run_type']} | {r['complete']}/{r['runs']} | "
            f"{r['partial']}/{r['failed']}/{r['skipped']} | {_fmt(r['mean_sec'])} | "
            f"{_fmt(r['median_sec'])} | {_fmt(r['p95_sec'])} | {_fmt(r['min_sec'])} | "
            f"{_fmt(r['max_sec'])} | {_fmt(r['mean_llm_inference_sec'])} | "
            f"{_fmt(r['mean_rag_retrieval_sec'])} | {_fmt(r['mean_static_analysis_sec'])} | "
            f"{_fmt(r['mean_input_tokens'])} | {_fmt(r['mean_output_tokens'])} | "
            f"{_fmt(r['mean_findings'])} | {_fmt(r['mean_review_chunks'])} |"
        )
    files = ["", "Files (SHA-256 prefix in results):"]
    files += [
        f"- {i['category']}: `{i['name']}`, {i['lines']} lines, {i['size_kb']} KB"
        for i in m["inputs"]
    ]
    note = [
        "",
        "Times are seconds. Statistics use complete runs only. P95 with few runs is close to the "
        "maximum. '-' means not measured.",
        "",
    ]
    return "\n".join(head + rows + files + note)


def write_outputs(folder: Path, rows: list[dict[str, Any]], m: dict[str, Any]) -> None:
    (folder / "results.json").write_text(
        json.dumps({"metrics": m, "runs": rows}, indent=2, default=str), encoding="utf-8"
    )
    with (folder / "results.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    with (folder / "summary.csv").open("w", newline="", encoding="utf-8") as fh:
        fields = [k for k in m["results"][0] if k != "files"]
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(m["results"])


def load_previous(run_dir: Path) -> dict[tuple[str, int, str], dict[str, Any]]:
    """Measured rows of an earlier run, so `--resume` only repeats what did not finish."""
    data = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    return {
        (r["file_name"], r["repeat"], r["run_type"]): r
        for r in data["runs"]
        if r.get("status") not in NOT_MEASURED and r.get("failed_units") in (0, None)
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review time by file size (CSV + JSON output)")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--mode", choices=["static_only", "full"], default="full")
    parser.add_argument("--no-rag", action="store_true")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--per-category", type=int, default=3)
    parser.add_argument("--inputs", type=Path, help="folder of .py files (default: Python stdlib)")
    parser.add_argument("--max-llm-calls", type=int, help="stop LLM runs at this many calls")
    parser.add_argument("--resume", type=Path, help="earlier run folder to continue")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)

    settings = load_settings(args.config)
    rag = args.mode != "static_only" and not args.no_rag
    # A cold run must reach the LLM: the provider reply cache would answer rounds 2+ from disk.
    # Warm runs reuse the per-run unit cache that `run_settings` points at a fresh folder instead.
    settings.llm.response_cache = False
    llm = create_provider(settings.llm) if args.mode != "static_only" else None
    inputs = select_inputs(args.inputs or stdlib_dir(), args.per_category)
    for category in CATEGORIES:
        if not any(i.category == category for i in inputs):
            print(f"warning: no input file for category {category}", file=sys.stderr)
    done = load_previous(args.resume) if args.resume else None
    recorder = RunRecorder(f"runtime_{args.mode}_r{args.repeats}", settings)
    rows = run_benchmark(
        settings,
        llm,
        inputs,
        mode=args.mode,
        rag=rag,
        repeats=args.repeats,
        recorder=recorder,
        done=done,
        max_llm_calls=args.max_llm_calls,
    )
    m = metrics(
        rows, inputs, mode=args.mode, rag=rag, repeats=args.repeats, llm=llm, settings=settings
    )
    md = summary_md(m)
    out = recorder.finish(
        m,
        md,
        benchmark="runtime",
        repeats=args.repeats,
        llm_provider=getattr(llm, "name", None),
        llm_model=getattr(llm, "model", None),
        sample_ids=[i.sha256 for i in inputs],
    )
    write_outputs(out, rows, m)
    print(md)
    print(f"saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

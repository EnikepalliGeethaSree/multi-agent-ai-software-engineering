"""Efficiency analysis: how long a complete review takes and where the time goes.

Each (input, configuration) pair is reviewed `repeats` times; every run writes the dashboard's
reports (JSON, Markdown, PDF, SARIF) so the total covers request -> final reports.

Fairness rules (recorded in the run's conditions):
- the same inputs for every configuration; repeats are interleaved (input x config per round) so
  network or machine drift affects all configurations alike;
- concurrency 1, so component times are sequential and "other" is meaningful;
- a fresh, empty vector store for every run (the content-hashed persistent index would otherwise
  make repeat 2+ skip embedding);
- one untimed static-only warm-up per input (imports, tool caches);
- suggested fixes off by default (extra LLM calls that are not part of the review itself);
- LLM runs where any review unit failed (quota, size) are kept in predictions but excluded from
  the aggregates and from the RAG overhead.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from marl_agents.agents.code_review import CodeReviewAgent
from marl_agents.config import Settings
from marl_agents.core.schemas import AgentRequest
from marl_agents.core.timing import TimingBreakdown, describe
from marl_agents.evaluation.configurations import classify
from marl_agents.evaluation.metrics.efficiency import overhead_pct
from marl_agents.evaluation.recorder import RunRecorder
from marl_agents.llm.base import LLMProvider
from marl_agents.reports import write_reports_timed

logger = logging.getLogger(__name__)

REPORT_FORMATS = ("json", "md", "pdf", "sarif")
# Timing configuration names predate the A-D ablation names; saved runs use them, so they stay.
# Each maps to exactly one ablation configuration (evaluation/configurations.py).
CONFIGS: dict[str, dict[str, Any]] = {
    "static_only": {"mode": "static_only", "rag": False},  # A  Static Only
    "llm_only": {"mode": "llm_only", "rag": False},  # B  LLM Only
    "llm_no_rag": {"mode": "full", "rag": False},  # C  Static + LLM
    "llm_rag": {"mode": "full", "rag": True},  # D  Static + LLM + RAG
}
TO_CONFIGURATION = {
    "static_only": "static_only",
    "llm_only": "llm_only",
    "llm_no_rag": "static_llm",
    "llm_rag": "static_llm_rag",
}
COMPONENTS = (
    "total_sec",
    "static_analysis_sec",
    "rag_sec",
    "llm_inference_sec",
    "validation_sec",
    "report_generation_sec",
    "other_sec",
    "llm_rate_limit_wait_sec",
)


@dataclass(frozen=True)
class TimingInput:
    sample_id: str
    path: Path


def default_inputs(project_root: Path) -> list[TimingInput]:
    """A small multi-file repository and a single file, both shipped with the project."""
    return [
        TimingInput("planted_repo", project_root / "tests" / "fixtures" / "repos" / "planted"),
        TimingInput("order_service_file", project_root / "examples" / "order_service.py"),
    ]


def hardware() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
    }


def _vector_store() -> str:
    try:
        import chromadb  # noqa: F401
    except ImportError:
        return "memory"
    return "chroma"


def config_settings(base: Settings, config: str, fixes: bool, store_dir: Path | None) -> Settings:
    spec = CONFIGS[config]
    s = base.model_copy(deep=True)
    s.review.mode = spec["mode"]
    s.review.concurrency = 1
    s.review.suggest_fixes = fixes
    s.rag.enabled = spec["rag"]
    s.rag.vector_store = "chroma" if store_dir is not None else "memory"
    s.rag.persist_dir = str(store_dir) if store_dir is not None else None
    return s


def time_one(
    settings: Settings, llm: LLMProvider | None, item: TimingInput, out_dir: Path
) -> dict[str, Any]:
    """One timed review of `item` (request -> reports). Returns the prediction row."""
    agent = CodeReviewAgent(
        llm if settings.review.mode != "static_only" else None,
        settings=settings,
        progress=lambda _m: None,
    )
    if item.path.is_file() and item.path.suffix == ".py":
        request = AgentRequest(
            snippet=item.path.read_text(encoding="utf-8"), snippet_filename=item.path.name
        )
    else:
        request = AgentRequest(repo_path=str(item.path))
    result = agent.run(request)
    write_reports_timed(result, out_dir, REPORT_FORMATS)
    timing = TimingBreakdown.model_validate(result.stats["timing"])
    st = result.stats
    return {
        "timing": timing.summary(),
        "static_tools_sec": timing.static_tools_sec,
        "conditions": {
            "files": st.get("files_total"),
            "python_files": st.get("python_files"),
            "files_reviewed": st.get("files_reviewed"),
            "lines_reviewed": st.get("lines_reviewed"),
            "review_units": st.get("units_total", 0),
            "llm_calls": timing.llm_calls,
            "findings": len(result.findings),
        },
        "units_failed": st.get("units_failed", 0),
    }


def run_timing(
    base: Settings,
    llm: LLMProvider | None,
    recorder: RunRecorder,
    inputs: list[TimingInput],
    configs: list[str],
    repeats: int = 3,
    fixes: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    progress = progress or (lambda m: logger.info(m))
    store = _vector_store()
    llm_configs = [c for c in configs if CONFIGS[c]["mode"] != "static_only"]
    if llm_configs and llm is None:
        raise ValueError(f"configurations {llm_configs} need an LLM provider")
    rows: list[dict[str, Any]] = []
    # ignore_cleanup_errors: ChromaDB keeps its files open on Windows until the process exits
    with tempfile.TemporaryDirectory(prefix="marl_timing_", ignore_cleanup_errors=True) as tmp:
        tmp_dir = Path(tmp)
        for item in inputs:  # warm-up (not recorded)
            time_one(config_settings(base, "static_only", False, None), None, item, tmp_dir / "w")
        for rep in range(1, repeats + 1):
            for item in inputs:
                for config in configs:
                    store_dir = None
                    if store == "chroma" and CONFIGS[config]["rag"]:
                        store_dir = Path(tempfile.mkdtemp(prefix="chroma_", dir=tmp_dir))
                    s = config_settings(base, config, fixes, store_dir)
                    row = time_one(s, llm, item, tmp_dir / f"r{rep}_{item.sample_id}_{config}")
                    row.update(sample_id=item.sample_id, config=config, repeat=rep)
                    row["complete"] = not row["units_failed"]
                    rows.append(row)
                    recorder.prediction(row)
                    if store_dir is not None:
                        shutil.rmtree(store_dir, ignore_errors=True)
                    progress(
                        f"round {rep}/{repeats} {item.sample_id} {config}: "
                        f"{row['timing']['total_sec']:.2f}s"
                    )
    return timing_metrics(rows, configs, inputs, llm, repeats, fixes, store)


def timing_metrics(
    rows: list[dict[str, Any]],
    configs: list[str],
    inputs: list[TimingInput],
    llm: LLMProvider | None,
    repeats: int,
    fixes: bool,
    store: str,
) -> dict[str, Any]:
    results: dict[str, dict[str, Any]] = {}
    for item in inputs:
        per_config: dict[str, Any] = {}
        for config in configs:
            runs = [r for r in rows if r["sample_id"] == item.sample_id and r["config"] == config]
            done = [r for r in runs if r["complete"]]
            spec = CONFIGS[config]
            per_config[config] = {
                "configuration": classify(spec["mode"], spec["rag"]).model_dump(
                    exclude={"description"}
                ),
                "runs": len(runs),
                "complete_runs": len(done),
                **{c: describe(r["timing"].get(c) for r in done).model_dump() for c in COMPONENTS},
                "active_sec": describe(_active(r) for r in done).model_dump(),
                # LLM calls beyond one per review unit are JSON-schema retries
                "llm_calls": describe(r["conditions"].get("llm_calls") for r in done).model_dump(),
                "llm_retries": describe(
                    (r["conditions"].get("llm_calls") or 0)
                    - (r["conditions"].get("review_units") or 0)
                    for r in done
                ).model_dump(),
                "static_tools_sec": {
                    tool: describe(r["static_tools_sec"].get(tool) for r in done).model_dump()
                    for tool in sorted({t for r in done for t in r["static_tools_sec"]})
                },
                "conditions": done[0]["conditions"]
                if done
                else (runs[0]["conditions"] if runs else {}),
            }
        results[item.sample_id] = {"configs": per_config, "rag_overhead": rag_overhead(per_config)}
    return {
        "benchmark": "timing",
        "repeats": repeats,
        "inputs": {i.sample_id: str(i.path) for i in inputs},
        "configs": configs,
        "results": results,
        "conditions": {
            "provider": getattr(llm, "name", None) if llm is not None else None,
            "model": getattr(llm, "model", None) if llm is not None else None,
            "concurrency": 1,
            "suggested_fixes": fixes,
            "vector_store": f"{store} (fresh per run)",
            "warm_up": "one untimed static-only run per input",
            "order": "interleaved: round -> input -> configuration",
            "report_formats": list(REPORT_FORMATS),
            "hardware": hardware(),
        },
    }


def _active(row: dict[str, Any]) -> float:
    """Total minus time spent waiting for the LLM provider's quota (environment, not pipeline)."""
    t = row["timing"]
    return float(t["total_sec"]) - float(t.get("llm_rate_limit_wait_sec") or 0.0)


def rag_overhead(per_config: dict[str, Any]) -> dict[str, Any] | None:
    """((T_rag - T_no_rag) / T_no_rag) x 100 on median active time; None unless comparable."""
    a, b = per_config.get("llm_no_rag"), per_config.get("llm_rag")
    if not a or not b or not a["complete_runs"] or not b["complete_runs"]:
        return None
    t_no, t_rag = a["active_sec"]["median"], b["active_sec"]["median"]
    pct = overhead_pct(t_rag, t_no)
    if pct is None:
        return None
    rag_direct = b["rag_sec"]["median"] or 0.0
    retries = (a.get("llm_retries", {}).get("median"), b.get("llm_retries", {}).get("median"))
    return {
        "median_active_sec_without_rag": t_no,
        "median_active_sec_with_rag": t_rag,
        "overhead_pct": round(pct, 1),
        "basis": "median active time (total minus LLM quota waiting), same input and model",
        # What RAG itself costs (index + queries), and whether LLM retries differ between configs.
        "rag_direct_median_sec": rag_direct,
        "rag_direct_share_pct": round(rag_direct / t_rag * 100, 1) if t_rag else None,
        "median_llm_retries_without_rag": retries[0],
        "median_llm_retries_with_rag": retries[1],
    }


def _fmt(d: dict[str, Any] | None) -> str:
    if not d or d.get("median") is None:
        return "-"
    if d["n"] > 1:
        return f"{d['median']:.2f} ({d['min']:.2f}-{d['max']:.2f})"
    return f"{d['median']:.2f}"


LABELS = {
    "static_analysis_sec": "Static analysis",
    "rag_sec": "RAG (index + retrieval)",
    "llm_inference_sec": "LLM inference",
    "validation_sec": "Validation",
    "report_generation_sec": "Report generation",
    "other_sec": "Other / orchestration",
    "llm_rate_limit_wait_sec": "  of which: LLM quota waiting",
    "total_sec": "**Total**",
}


def timing_summary_md(m: dict[str, Any], title: str) -> str:
    c = m["conditions"]
    lines = [
        f"# {title}",
        "",
        f"Repeats: {m['repeats']} per input and configuration (median, min-max shown, seconds). "
        f"LLM: {c['provider']} / {c['model']}. Concurrency {c['concurrency']}; vector store "
        f"{c['vector_store']}; suggested fixes {'on' if c['suggested_fixes'] else 'off'}; "
        f"{c['warm_up']}; order {c['order']}.",
        f"Hardware: {c['hardware']['platform']}, {c['hardware']['processor']}, "
        f"{c['hardware']['cpu_count']} CPUs, Python {c['hardware']['python']}.",
    ]
    for sample, res in m["results"].items():
        cfgs = res["configs"]
        names = list(cfgs)
        cond: dict[str, Any] = next(
            (cfgs[n]["conditions"] for n in names if cfgs[n]["conditions"]), {}
        )
        lines += [
            "",
            f"## {sample}",
            "",
            f"{cond.get('files')} files ({cond.get('python_files')} Python), "
            f"{cond.get('lines_reviewed')} lines reviewed.",
            "",
            "| Component | " + " | ".join(names) + " |",
            "|---|" + "---:|" * len(names),
        ]
        for comp, label in LABELS.items():
            lines.append(
                f"| {label} | " + " | ".join(_fmt(cfgs[n].get(comp)) for n in names) + " |"
            )
        lines.append(
            "| Complete runs | "
            + " | ".join(f"{cfgs[n]['complete_runs']}/{cfgs[n]['runs']}" for n in names)
            + " |"
        )
        lines.append(
            "| LLM review units | "
            + " | ".join(str(cfgs[n]["conditions"].get("review_units", "-")) for n in names)
            + " |"
        )
        lines.append(
            "| LLM calls (incl. JSON retries) | "
            + " | ".join(_fmt(cfgs[n].get("llm_calls")) for n in names)
            + " |"
        )
        tools = sorted({t for n in names for t in cfgs[n]["static_tools_sec"]})
        if tools:
            lines += [
                "",
                "Static analysis by tool (median s): "
                + ", ".join(
                    f"{t} {_fmt(cfgs[names[0]]['static_tools_sec'].get(t))}" for t in tools
                ),
            ]
        ov = res["rag_overhead"]
        if ov:
            lines += [
                "",
                f"RAG latency overhead: {ov['overhead_pct']:+.1f}% "
                f"({ov['median_active_sec_without_rag']:.2f}s -> "
                f"{ov['median_active_sec_with_rag']:.2f}s; {ov['basis']}).",
            ]
            if ov.get("rag_direct_median_sec") is not None:
                lines.append(
                    f"RAG's own cost (index + queries): {ov['rag_direct_median_sec']:.2f}s, "
                    f"{ov['rag_direct_share_pct']}% of active time with RAG. Median JSON retries: "
                    f"{ov['median_llm_retries_without_rag']} without RAG, "
                    f"{ov['median_llm_retries_with_rag']} with RAG; a retry repeats the LLM call, "
                    "so differing retries, not retrieval, can dominate a small-n comparison."
                )
    lines += [
        "",
        "Components are sums of measured spans; 'Other' = total - components (ingestion and "
        "parsing, context assembly, waiting for the LLM quota, scheduling).",
        "",
    ]
    return "\n".join(lines)

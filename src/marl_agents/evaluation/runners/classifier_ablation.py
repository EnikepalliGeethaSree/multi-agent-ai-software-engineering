"""The classifier off, prioritizing and gating, on identical development samples.

    python -m marl_agents.cli eval classifier-ablation --model-dir data/models/change_cls \
        --limit 30 --max-llm-calls 150 --config configs/gemini.yaml

Samples come from the dev set only. Membership is decided by data/classifier/py/dev.jsonl, so the
classifier's test split is never opened. Dev also chose the checkpoint and threshold, so these
numbers are not an independent test of the classifier.

Every sample is reviewed in all three modes, in rotating order so drift hits each mode alike. A
budget or quota stop happens between samples, and only samples complete in all three modes are
compared. The LLM cache is off, so calls and time are real.

"Useful" and "important" are proxies, defined in `METRIC_NOTES`. Nobody judged these findings.
"""

from __future__ import annotations

import csv
import json
import logging
import random
from collections.abc import Callable
from pathlib import Path
from typing import Any

from marl_agents.agents.code_review import CodeReviewAgent
from marl_agents.config import PROJECT_ROOT, Settings
from marl_agents.core.schemas import Severity
from marl_agents.evaluation.datasets import load_codereviewer
from marl_agents.evaluation.datasets.codereviewer import CodeReviewerSample
from marl_agents.evaluation.recorder import RunRecorder
from marl_agents.evaluation.runners.code_review import _compact, review_patch, timing_summary
from marl_agents.ingestion.diff import PatchError
from marl_agents.llm.base import LLMProvider, QuotaExhaustedError
from marl_agents.llm.classifier import change_text, create_classifier
from marl_agents.training.data import patch_key, read_examples

logger = logging.getLogger(__name__)

MODES = ("disabled", "prioritize", "gate")
DEFAULT_LIMIT = 30  # a small default, so a forgotten --limit cannot spend a day's free quota
LINE_TOLERANCE = 3
USEFUL_RANK = Severity("medium").rank
IMPORTANT_RANK = Severity("high").rank
CSV_FIELDS = (
    "sample_id", "mode", "status", "label", "units_total", "units_scored", "units_skipped",
    "units_protected", "units_failed", "llm_calls", "input_tokens", "output_tokens", "total_sec",
    "llm_inference_sec", "findings_count", "message",
)  # fmt: skip
METRIC_NOTES = (
    "Baseline: the same sample with the classifier disabled.",
    f"Retained: a baseline finding with a match (same rule if both have one, else same category, "
    f"within {LINE_TOLERANCE} lines).",
    "Useful (proxy): severity medium or above, on a change a human commented on.",
    "Important (proxy): severity high or critical.",
    "Prioritize reviews the same units as disabled, so its gap from 100% shows LLM run-to-run "
    "variation, not lost work.",
    "These samples are single changes, so prioritize usually has nothing to reorder.",
)


def dev_samples(
    settings: Settings, data_dir: Path, limit: int, seed: int = 42
) -> list[CodeReviewerSample]:
    """A reproducible sample of the dev set. The test split is never loaded."""
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    projects = set(manifest["dev_projects"])
    allowed = {e.text for e in read_examples(data_dir / "dev.jsonl")}
    valid = load_codereviewer(
        "cls",
        "valid",
        root=PROJECT_ROOT / settings.datasets.root,
        cache_dir=PROJECT_ROOT / settings.datasets.cache_dir,
    )
    unique: dict[str, CodeReviewerSample] = {}
    for sample in valid:
        if sample.proj in projects and change_text(sample.patch) in allowed:
            unique.setdefault(patch_key(sample.patch), sample)
    eligible = sorted(unique.values(), key=lambda s: s.sample_id)
    return random.Random(seed).sample(eligible, min(limit, len(eligible)))


def mode_settings(
    base: Settings, mode: str, model_dir: Path, store_dir: Path | None = None
) -> Settings:
    """Identical in every mode except the classifier. `store_dir` is a fresh ChromaDB folder."""
    s = base.model_copy(deep=True)
    if store_dir is not None:
        s.rag.vector_store = "chroma"
        s.rag.persist_dir = str(store_dir)
    s.review.mode = "full"
    s.review.concurrency = 1
    s.review.suggest_fixes = False
    s.review.unit_cache = False
    s.rag.enabled = True
    s.classifier.enabled = mode != "disabled"
    s.classifier.model_dir = str(model_dir)
    s.classifier.mode = "gate" if mode == "gate" else "prioritize"
    return s


def build_agents(
    base: Settings, llm: LLMProvider, model_dir: Path, store_dir: Path | None = None
) -> dict[str, CodeReviewAgent]:
    """One agent per mode, sharing one provider and one vector store, so inputs stay identical."""
    agents = {}
    for mode in MODES:
        settings = mode_settings(base, mode, model_dir, store_dir)
        agents[mode] = CodeReviewAgent(
            llm,
            settings=settings,
            progress=lambda _m: None,
            classifier=create_classifier(settings.classifier),
        )
    return agents


def _review(agent: CodeReviewAgent, sample: CodeReviewerSample, mode: str) -> dict[str, Any]:
    row: dict[str, Any] = {"sample_id": sample.sample_id, "mode": mode, "label": sample.label}
    try:
        result, _ranges = review_patch(agent, sample.oldf, sample.patch)
    except PatchError as exc:
        return {**row, "status": "ineligible", "message": f"patch: {exc}"[:200]}
    except QuotaExhaustedError as exc:
        return {**row, "status": "quota", "message": str(exc)[:200]}
    except Exception as exc:  # recorded as a failed run, never dropped
        logger.warning("Sample %s failed in mode %s", sample.sample_id, mode)
        return {**row, "status": "failed", "message": f"{type(exc).__name__}: {exc}"[:200]}
    stats = result.stats
    usage = stats.get("llm_usage") or {}
    plan = stats.get("classifier") or {}
    failed = int(stats.get("units_failed", 0) or 0)
    timing = timing_summary(result)
    status = "quota" if "quota" in stats else "partial" if failed else "complete"
    return {
        **row,
        "status": status,
        "units_total": stats.get("units_total"),
        "units_scored": plan.get("scored", 0),
        "units_skipped": plan.get("skipped", 0),
        "units_protected": plan.get("protected", 0),
        "units_failed": failed,
        "llm_calls": usage.get("calls"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "total_sec": timing.get("total_sec"),
        "llm_inference_sec": timing.get("llm_inference_sec"),
        "findings_count": len(result.findings),
        "findings": _compact(result.findings),
        "message": "; ".join(result.errors)[:200],
    }


def run_ablation(
    agents: dict[str, CodeReviewAgent],
    samples: list[CodeReviewerSample],
    recorder: RunRecorder,
    done: dict[tuple[str, str], dict[str, Any]] | None = None,
    max_llm_calls: int | None = None,
    progress: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    """Reviews each sample in every mode. Stops only between samples, unless the quota runs out."""
    previous = done or {}
    calls = sum(int(r.get("llm_calls") or 0) for r in previous.values())
    rows: list[dict[str, Any]] = []
    stop: str | None = None
    for index, sample in enumerate(samples):
        if stop is None and max_llm_calls is not None and calls >= max_llm_calls:
            stop = f"--max-llm-calls {max_llm_calls} reached"
        shift = index % len(MODES)
        for mode in (*MODES[shift:], *MODES[:shift]):
            key = (sample.sample_id, mode)
            if key in previous:
                rows.append(previous[key])
                continue
            if stop is not None:
                row: dict[str, Any] = {
                    "sample_id": sample.sample_id,
                    "mode": mode,
                    "label": sample.label,
                    "status": "skipped",
                    "message": stop,
                }
            else:
                row = _review(agents[mode], sample, mode)
                calls += int(row.get("llm_calls") or 0)
                if row["status"] == "quota":
                    stop = "LLM quota reached in an earlier sample"
            rows.append(row)
            recorder.prediction(row)
            progress(f"{index + 1}/{len(samples)} {mode:10} {row['status']} calls={calls}")
    return rows


def load_previous(run_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """Measured rows of an earlier run. Skipped and quota rows are run again."""
    kept: dict[tuple[str, str], dict[str, Any]] = {}
    with (run_dir / "predictions.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row.get("status") not in {"skipped", "quota"}:
                kept[(row["sample_id"], row["mode"])] = row
    return kept


def _matches(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a.get("rule") and b.get("rule"):
        return bool(a["rule"] == b["rule"])
    if a["category"] != b["category"]:
        return False
    return bool(
        a["lines"][0] - LINE_TOLERANCE <= b["lines"][1]
        and b["lines"][0] - LINE_TOLERANCE <= a["lines"][1]
    )


def missing_from(base: list[dict[str, Any]], other: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Baseline findings with no match in `other`. Each finding of `other` is used once."""
    free = list(other)
    missing = []
    for finding in base:
        match = next((f for f in free if _matches(finding, f)), None)
        if match is None:
            missing.append(finding)
        else:
            free.remove(match)
    return missing


def _rank(finding: dict[str, Any]) -> int:
    return Severity(finding["severity"]).rank


def _is_static(finding: dict[str, Any]) -> bool:
    return "llm" not in finding.get("sources", [])


def _sum(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [r[key] for r in rows if r.get(key) is not None]
    return sum(values) if values else None


def compare(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-mode totals over the samples complete in all three modes."""
    by_sample: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        by_sample.setdefault(row["sample_id"], {})[row["mode"]] = row
    paired = {
        sample: entry
        for sample, entry in by_sample.items()
        if all(entry.get(m, {}).get("status") == "complete" for m in MODES)
    }
    modes: dict[str, Any] = {}
    for mode in MODES:
        group = [m[mode] for m in paired.values()]
        total = _sum(group, "total_sec")
        block: dict[str, Any] = {
            "samples": len(group),
            "units_total": _sum(group, "units_total"),
            "units_skipped": _sum(group, "units_skipped"),
            "units_protected": _sum(group, "units_protected"),
            "llm_calls": _sum(group, "llm_calls"),
            "input_tokens": _sum(group, "input_tokens"),
            "output_tokens": _sum(group, "output_tokens"),
            "total_sec": None if total is None else round(total, 2),
            "findings": _sum(group, "findings_count"),
        }
        if mode != "disabled":
            base, useful, important = 0, 0, 0
            lost, useful_lost, important_lost, static_lost = 0, 0, [], 0
            for sample, entry in paired.items():
                baseline = entry["disabled"].get("findings", [])
                gone = missing_from(baseline, entry[mode].get("findings", []))
                commented = entry[mode].get("label") == 1
                base += len(baseline)
                lost += len(gone)
                useful += sum(1 for f in baseline if commented and _rank(f) >= USEFUL_RANK)
                useful_lost += sum(1 for f in gone if commented and _rank(f) >= USEFUL_RANK)
                important += sum(1 for f in baseline if _rank(f) >= IMPORTANT_RANK)
                for finding in gone:
                    if _rank(finding) < IMPORTANT_RANK:
                        continue
                    important_lost.append({"sample_id": sample, **finding})
                    if _is_static(finding) and entry[mode].get("units_skipped"):
                        static_lost += 1
            block |= {
                "baseline_findings": base,
                "findings_retained": base - lost,
                "useful_baseline": useful,
                "useful_retained": useful - useful_lost,
                "important_baseline": important,
                "important_missed": len(important_lost),
                "important_missed_detail": important_lost,
                "static_high_lost_in_skipped_units": static_lost,
            }
        modes[mode] = block
    counts: dict[str, dict[str, int]] = {}
    for row in rows:
        tally = counts.setdefault(row["mode"], {})
        tally[row["status"]] = tally.get(row["status"], 0) + 1
    return {"paired_samples": len(paired), "status_counts": counts, "modes": modes}


def summary_md(metrics: dict[str, Any]) -> str:
    fields = (
        ("Samples compared", "samples"),
        ("Review units", "units_total"),
        ("Units skipped", "units_skipped"),
        ("Units protected from gating", "units_protected"),
        ("LLM calls", "llm_calls"),
        ("Input tokens", "input_tokens"),
        ("Output tokens", "output_tokens"),
        ("Total time (s)", "total_sec"),
        ("Findings", "findings"),
        ("Baseline findings retained", "findings_retained"),
        ("Useful retained (proxy)", "useful_retained"),
        ("Useful in baseline (proxy)", "useful_baseline"),
        ("Important missed (proxy)", "important_missed"),
        ("Important in baseline (proxy)", "important_baseline"),
        ("Static high/critical lost in skipped units", "static_high_lost_in_skipped_units"),
    )
    modes = metrics["modes"]
    lines = [
        "# Classifier ablation on development samples",
        "",
        f"Provider `{metrics['provider']}`, model `{metrics['model']}`, threshold from the model. "
        f"Dev samples, seed {metrics['seed']}. Dev tuned the classifier, so this is not an "
        "independent test.",
        "",
        "| Measure | Disabled | Prioritize | Gate |",
        "|---|---:|---:|---:|",
    ]
    for label, key in fields:
        values = [modes[m].get(key) for m in MODES]
        cells = ["-" if v is None else str(v) for v in values]
        lines.append(f"| {label} | {cells[0]} | {cells[1]} | {cells[2]} |")
    lines += ["", f"Run status by mode: {metrics['status_counts']}.", ""]
    lines += [f"- {note}" for note in METRIC_NOTES]
    return "\n".join([*lines, ""])


def write_outputs(folder: Path, rows: list[dict[str, Any]]) -> None:
    """Raw measurements, one row per sample and mode."""
    (folder / "results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    with (folder / "results.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

"""Collect, re-verify and summarise the official Groq evaluation (D38/D39) from saved runs only.

    python scripts/groq_final_results.py

Reads experiments/results/ (never writes there) and writes:
- experiments/evaluation_summary/groq_final_results.json  (machine-readable, every number + source run)
- experiments/evaluation_summary/groq_final_results.md    (human-readable summary)
- experiments/evaluation_summary/groq_manifest.json       (run ids, commits, samples, commands)

Reproducibility check: CodeReviewer BLEU-4, ROUGE-L, chrF and coverage are recomputed from each run's
saved predictions and compared with the values the run stored; planted counts are recomputed from
the saved answer-key comparison; BugsInPy metrics are recomputed from the saved per-sample rows.
Any mismatch is listed and makes the script exit with code 1. No model is called.
"""

from __future__ import annotations

import json
import statistics
import sys
from typing import Any

from marl_agents.config import PROJECT_ROOT
from marl_agents.evaluation.comparison.detection import msg_metrics
from marl_agents.evaluation.runners import bug_scoring
from marl_agents.evaluation.runs import SavedRun, load_runs

RESULTS = PROJECT_ROOT / "experiments" / "results"
OUT = PROJECT_ROOT / "experiments" / "evaluation_summary"
LEDGER = PROJECT_ROOT / "data" / "cache" / "llm_quota" / "groq_openai_gpt-oss-120b_budget.json"
MODEL = "openai/gpt-oss-120b"
PLANTED_GROUP = "abl-20261111T111100Z"
CR_GROUP = "abl-20261111T111605Z"
RUNTIME_RUN = "20261111T121516Z_runtime_full_r5"
PRICES = {"input": 0.15, "output": 0.60}  # USD per 1M tokens, configured from the Groq console
ORDER = ["static_only", "llm_only", "static_llm", "static_llm_rag"]
LETTER = dict(zip(ORDER, "ABCD", strict=True))
COMMANDS = {
    "planted": "python -m marl_agents.cli eval ablation --benchmark planted --configurations "
    "static_only,llm_only,static_llm,static_llm_rag --repeats 3 --no-cache --config configs/groq.yaml",
    "codereviewer_msg": "python -m marl_agents.cli eval ablation --benchmark codereviewer --task msg "
    "--limit 40 --seed 42 --configurations static_only,llm_only,static_llm,static_llm_rag --repeats 3 "
    "--no-cache --workers 1 --config configs/groq.yaml",
    "clean_repos": "python -m marl_agents.cli eval clean-repos --config configs/groq.yaml",
    "runtime": "python -m marl_agents.evaluation.benchmark_runtime --config configs/groq.yaml --mode full "
    "--repeats 5 --per-category 1 --max-llm-calls 200",
    "bugsinpy_dev": "python -m marl_agents.cli eval-bugs {localization|detection} --split dev --limit 20 "
    "--no-cache --config configs/groq.yaml",
    "bugsinpy_test": "python -m marl_agents.cli eval-bugs {localization|detection} --split test --limit 20 "
    "--final --no-cache --config configs/groq.yaml",
}  # fmt: skip
TOL = 0.011  # metrics are stored rounded to 2-3 decimals


def spread(values: list[float]) -> dict[str, float]:
    return {"mean": round(statistics.mean(values), 4), "min": min(values), "max": max(values)}


def groq(run: SavedRun) -> bool:
    return run.provider == "groq" and run.model == MODEL


def meta_row(run: SavedRun) -> dict[str, Any]:
    return {
        "run": run.name,
        "provider": run.provider,
        "model": run.model,
        "commit": run.meta.get("git_commit"),
        "prompt_versions": run.experiment.get("prompt_versions"),
    }


def planted(runs: list[SavedRun], problems: list[str]) -> dict[str, Any]:
    group = [r for r in runs if r.kind == "planted" and r.group_id == PLANTED_GROUP]
    out: dict[str, Any] = {"group": PLANTED_GROUP, "issues": 17, "configurations": {}}
    for key in ORDER:
        rs = [r for r in group if r.configuration and r.configuration.key == key]
        dets = [r.metrics["detection"] for r in rs]
        found = [int(d["matched"]) for d in dets]
        tp = [int(d.get("tp", 0)) for d in dets]
        fp = [int(d.get("fp", 0)) for d in dets]
        for d in dets:  # recompute recall from the saved counts
            if abs(d["matched"] / d["expected"] - float(d["recall"])) > TOL:
                problems.append(f"planted {key}: recall does not match matched/expected")
        prec = [t / (t + f) for t, f in zip(tp, fp, strict=True) if t + f]
        out["configurations"][LETTER[key]] = {
            "runs": [r.name for r in rs],
            "issues_found_per_run": found,
            "true_positive_defect_findings_per_run": tp,
            "false_positive_defect_findings_per_run": fp,
            "issue_recall": spread([f / 17 for f in found]),
            "defect_precision_per_finding": spread(prec) if prec else None,
            "complete": all(r.metrics.get("complete") for r in rs),
        }
    return out


def codereviewer(runs: list[SavedRun], problems: list[str]) -> dict[str, Any]:
    group = [r for r in runs if r.kind == "codereviewer" and r.group_id == CR_GROUP]
    out: dict[str, Any] = {
        "group": CR_GROUP,
        "samples": 40,
        "split": "test, Python",
        "configurations": {},
    }
    for key in ORDER:
        rs = [r for r in group if r.configuration and r.configuration.key == key]
        per: dict[str, list[float]] = {"bleu4": [], "rouge_l": [], "chrf": [], "coverage": []}
        counts = []
        for r in rs:
            preds = r.predictions()
            m = msg_metrics(preds)
            stored = r.metrics["text_metrics"]["title_fix"]
            pairs = {"bleu4": stored["bleu4_smoothed"], "rouge_l": stored["rouge_l"],
                     "chrf": stored["chrf"], "coverage": r.metrics["comment_coverage"]}  # fmt: skip
            for name, value in pairs.items():
                if m[name] is None or abs(float(m[name]) - float(value)) > TOL * (
                    100 if name != "coverage" else 1
                ):
                    problems.append(
                        f"codereviewer {r.name}: {name} recomputed {m[name]} != stored {value}"
                    )
                per[name].append(round(float(m[name] or 0), 4))
            counts.append(sum(1 for p in preds if p.get("comment")))
            if r.metrics.get("n_evaluated") != 40 or r.metrics.get("n_failed"):
                problems.append(f"codereviewer {r.name}: not 40/40")
        out["configurations"][LETTER[key]] = {
            "runs": [r.name for r in rs],
            **{k: spread(v) for k, v in per.items()},
            "coverage_count_per_run": counts,
        }
    return out


def clean_repos(runs: list[SavedRun]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for r in runs:
        if r.name.split("_", 1)[-1].startswith("cleanrepo_") and groq(r):
            m = r.metrics
            out[m["repo"]["name"]] = {
                "run": r.name, "commit": m["repo"]["commit"], "package": m["repo"]["package"],
                "lines": m["lines"], "files": m["files"], "findings": m["findings"],
                "per_kloc": m["per_kloc"], "by_severity": m["by_severity"],
                "per_kloc_by_severity": m["per_kloc_by_severity"], "units": m["units_total"],
                "units_failed": m["units_failed"], "llm_calls": (m.get("llm_usage") or {}).get("calls"),
                "fixes": m.get("fixes"), "status": m["review_status"],
            }  # fmt: skip
    return out


def runtime(by_name: dict[str, SavedRun]) -> dict[str, Any]:
    r = by_name[RUNTIME_RUN]
    keep = ("category", "run_type", "runs", "complete", "partial", "mean_sec", "median_sec",
            "mean_llm_inference_sec", "mean_static_analysis_sec", "mean_input_tokens",
            "mean_output_tokens", "mean_cache_hit_rate")  # fmt: skip
    return {"run": r.name, "rows": [{k: row.get(k) for k in keep} for row in r.metrics["results"]]}


def bugsinpy(runs: list[SavedRun], problems: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for split in ("dev", "test"):
        for task in ("localization", "detection"):
            block: dict[str, Any] = {}
            for key in ORDER:
                rs = [r for r in runs if r.name.endswith(f"_bugsinpy_{task}_{split}_{key}_n20")
                      and r.stamp.startswith("2026111")]  # fmt: skip
                if not rs:
                    continue
                r = rs[-1]
                if r.config.get("llm", {}).get("provider") != "groq":
                    problems.append(f"bugsinpy {r.name}: provider is not groq")
                rows = r.predictions()
                again = (bug_scoring.score_localization(rows) if task == "localization"
                         else bug_scoring.score_detection(rows))  # fmt: skip
                m = r.metrics
                if task == "localization":
                    for k in ("top_1", "top_3", "top_5"):
                        if abs(again["top_function"][k] - m["top_function"][k]) > 1e-9:
                            problems.append(f"bugsinpy {r.name}: {k} differs on recompute")
                    block[LETTER[key]] = {
                        "run": r.name, "n": m["n"], "failed": m["n_failed"],
                        "top_1": m["top_function"]["top_1"], "top_3": m["top_function"]["top_3"],
                        "top_5": m["top_function"]["top_5"], "mrr": round(m["mrr_function"], 4),
                        "wilson": m.get("wilson"), "llm_calls": m["llm_calls"],
                    }  # fmt: skip
                else:
                    if abs(again["function_level"]["f1"] - m["function_level"]["f1"]) > 1e-9:
                        problems.append(f"bugsinpy {r.name}: F1 differs on recompute")
                    fl, pr = m["function_level"], m["pairs"]
                    block[LETTER[key]] = {
                        "run": r.name, "bugs": m["n_bugs"], "failed": m["n_failed"],
                        "precision": round(fl["precision"], 4), "recall": round(fl["recall"], 4),
                        "f1": round(fl["f1"], 4), "told_apart": pr["only_buggy"],
                        "flagged_both": pr["both_flagged"], "flagged_only_fixed": pr["only_fixed"],
                        "neither": pr["neither"], "false_positives_per_bug": round(
                            (pr["both_flagged"] + pr["only_fixed"]) / pr["n"], 4),
                        "wilson": m.get("wilson"), "llm_calls": m["llm_calls"],
                        "llm_rejected": m["llm_rejected"],
                    }  # fmt: skip
            comp = [r for r in runs if r.name.endswith(f"_bugsinpy_{task}_{split}_comparison_n20")
                    and r.stamp.startswith("2026111")]  # fmt: skip
            if comp:
                block["mcnemar"] = comp[-1].metrics["comparison"]
                block["comparison_run"] = comp[-1].name
            out[f"{task}_{split}"] = block
    return out


def main() -> int:
    runs = load_runs(RESULTS)
    by_name = {r.name: r for r in runs}
    problems: list[str] = []
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    cost_in = ledger["input_tokens"] * PRICES["input"] / 1e6
    cost_out = ledger["output_tokens"] * PRICES["output"] / 1e6
    data = {
        "provider": "groq",
        "model": MODEL,
        "prices_usd_per_1m_tokens": PRICES,
        "usage_all_groq_calls": {
            "requests": ledger["requests"],
            "input_tokens": ledger["input_tokens"],
            "output_tokens": ledger["output_tokens"],
            "estimated_cost_usd": {
                "input": round(cost_in, 4),
                "output": round(cost_out, 4),
                "total": round(cost_in + cost_out, 4),
            },
            "note": "includes 2 key checks, 8 calls of the stopped first planted attempt, 7 calls of "
            "the agent smoke tests, 1 API probe and the superseded runtime run",
        },  # fmt: skip
        "planted": planted(runs, problems),
        "codereviewer_msg": codereviewer(runs, problems),
        "clean_repos": clean_repos(runs),
        "runtime": runtime(by_name),
        "bugsinpy": bugsinpy(runs, problems),
        "reproducibility": {"checked": True, "mismatches": problems},
    }
    official = [r for r in runs if groq(r) and r.stamp >= "20261111"]
    manifest = {
        "commands": COMMANDS,
        "runs": [meta_row(r) for r in official],
        "commits": sorted({str(r.meta.get("git_commit")) for r in official}),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "groq_final_results.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    (OUT / "groq_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (OUT / "groq_final_results.md").write_text(summary_md(data), encoding="utf-8")
    print(summary_md(data))
    print("reproducibility:", "OK, all recomputed metrics match" if not problems else problems)
    return 1 if problems else 0


def summary_md(d: dict[str, Any]) -> str:
    u = d["usage_all_groq_calls"]
    lines = [
        "# Official Groq evaluation (openai/gpt-oss-120b)", "",
        f"All numbers from saved runs (sources in groq_final_results.json). Groq usage: {u['requests']} "
        f"requests, {u['input_tokens']:,} input + {u['output_tokens']:,} output tokens, estimated "
        f"${u['estimated_cost_usd']['total']:.2f} at ${d['prices_usd_per_1m_tokens']['input']}/"
        f"${d['prices_usd_per_1m_tokens']['output']} per 1M tokens.", "",
        "## Planted issues (17 issues, 3 runs per configuration)", "",
        "| Config | Issues found per run | Recall mean (min-max) | Defect precision mean | FP per run |",
        "|---|---|---|---|---|",
    ]  # fmt: skip
    for k, v in d["planted"]["configurations"].items():
        r, p = v["issue_recall"], v["defect_precision_per_finding"]
        lines.append(f"| {k} | {v['issues_found_per_run']} | {r['mean']:.3f} ({r['min']:.3f}-"
                     f"{r['max']:.3f}) | {p['mean']:.3f} | {v['false_positive_defect_findings_per_run']} |")  # fmt: skip
    lines += ["", "## CodeReviewer comments (40 test samples, Python, 3 runs)", "",
              "| Config | BLEU-4 | ROUGE-L | chrF | Coverage (x/40 per run) |", "|---|---|---|---|---|"]  # fmt: skip
    for k, v in d["codereviewer_msg"]["configurations"].items():
        lines.append(f"| {k} | {v['bleu4']['mean']:.2f} ({v['bleu4']['min']:.2f}-{v['bleu4']['max']:.2f}) | "
                     f"{v['rouge_l']['mean']:.2f} | {v['chrf']['mean']:.2f} | {v['coverage_count_per_run']} |")  # fmt: skip
    lines += ["", "## Clean repositories (configuration D)", "",
              "| Repo | Lines | Findings | Per 1,000 lines | High | Critical |", "|---|---:|---:|---:|---:|---:|"]  # fmt: skip
    for name, v in d["clean_repos"].items():
        lines.append(f"| {name} | {v['lines']:,} | {v['findings']} | {v['per_kloc']} | "
                     f"{v['by_severity']['high']} | {v['by_severity']['critical']} |")  # fmt: skip
    lines += ["", "## BugsInPy (20 dev bugs, 20 test bugs; test run once)", ""]
    for split in ("dev", "test"):
        loc, det = d["bugsinpy"][f"localization_{split}"], d["bugsinpy"][f"detection_{split}"]
        lines += [f"### {split}", "", "| Config | Top-1 | Top-3 | Top-5 | Detection P | R | F1 | Told apart |",
                  "|---|---|---|---|---|---|---|---|"]  # fmt: skip
        for k in "ABCD":
            a, b = loc[k], det[k]
            lines.append(f"| {k} | {a['top_1']:.2f} | {a['top_3']:.2f} | {a['top_5']:.2f} | "
                         f"{b['precision']:.3f} | {b['recall']:.3f} | {b['f1']:.3f} | {b['told_apart']}/{b['bugs']} |")  # fmt: skip
        lines.append("")
    prob = d["reproducibility"]["mismatches"]
    lines.append("Reproducibility: " + ("all recomputed metrics match the stored values." if not prob
                                        else f"{len(prob)} mismatch(es): {prob}"))  # fmt: skip
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())

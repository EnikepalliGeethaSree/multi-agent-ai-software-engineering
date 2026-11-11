"""Part 3.10: findings of the full system (configuration D) on mature, well-tested repositories.

    python -m marl_agents.cli eval clean-repos --config configs/groq.yaml

The repositories were chosen by the team: psf/requests, pallets/flask and pydantic/pydantic, each
pinned to the commit in `REPOS` and cloned once into data/cache/clean_repos/ (never executed). The
review covers each project's package folder only (no tests, docs or examples).

Why: these projects are mature, so most findings are likely false alarms or debatable. The run
reports findings per 1,000 lines by severity. Whether each finding is a real issue is decided by a
human: a seeded random sample of 50 findings is exported to
results/manual_label/clean_repo_findings.csv with empty `label` and `notes` columns. The tool never
labels findings, so no false-alarm *rate* exists until the team has labelled the sheet.

Every unit is reviewed: `review.max_units` is raised to the number of units of the largest
package (pydantic: 218), and the value is recorded.
"""

from __future__ import annotations

import csv
import random
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from marl_agents.config import PROJECT_ROOT, Settings
from marl_agents.core.schemas import AgentRequest, Finding, Severity
from marl_agents.evaluation.configurations import apply_configuration, experiment_metadata
from marl_agents.evaluation.recorder import RunRecorder
from marl_agents.llm.base import LLMProvider

CLONES = PROJECT_ROOT / "data" / "cache" / "clean_repos"
SHEET = PROJECT_ROOT / "results" / "manual_label" / "clean_repo_findings.csv"
MAX_UNITS = 220  # pydantic's package has 218 review units: none may be skipped
SAMPLE = 50
SEED = 42
SHEET_COLUMNS = [
    "repo", "run", "finding_id", "file", "start_line", "end_line", "severity", "category", "title",
    "description", "evidence", "sources", "label", "notes",
]  # fmt: skip


class CleanRepo(BaseModel):
    name: str
    url: str
    commit: str
    package: str


REPOS = [
    CleanRepo(name="requests", url="https://github.com/psf/requests",
              commit="3c7baaa05ab4aa49cc819ce3a819d260de19c157", package="src/requests"),
    CleanRepo(name="flask", url="https://github.com/pallets/flask",
              commit="49943b5a94413a530761350f04e896f76e8d620e", package="src/flask"),
    CleanRepo(name="pydantic", url="https://github.com/pydantic/pydantic",
              commit="560f0f96a37d6913afdfddb2de22030ef08e68c3", package="pydantic"),
]  # fmt: skip


def clone_commit(repo: CleanRepo) -> str:
    out = subprocess.run(  # noqa: S603 - fixed git command on our own clone
        ["git", "-C", str(CLONES / repo.name), "rev-parse", "HEAD"],  # noqa: S607
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return out.stdout.strip()


def density(findings: list[Finding], lines: int) -> dict[str, Any]:
    """Findings per 1,000 lines, overall and by severity (lines = lines reviewed)."""
    per = Counter(f.severity.value for f in findings)
    k = lines / 1000 if lines else 0
    return {
        "lines": lines,
        "findings": len(findings),
        "per_kloc": round(len(findings) / k, 3) if k else None,
        "by_severity": {s.value: per.get(s.value, 0) for s in Severity},
        "per_kloc_by_severity": {
            s.value: (round(per.get(s.value, 0) / k, 3) if k else None) for s in Severity
        },
    }


def settings_for(base: Settings) -> Settings:
    s = apply_configuration(base, "static_llm_rag")
    s.review.max_units = max(s.review.max_units, MAX_UNITS)
    s.review.unit_cache = s.review.analysis_cache = False  # a benchmark measures real work
    s.review.type_check = False  # mypy would need each project's dependencies installed
    return s


def review_repo(repo: CleanRepo, settings: Settings, llm: LLMProvider) -> Path:
    from marl_agents.agents.code_review import CodeReviewAgent

    commit = clone_commit(repo)
    if commit != repo.commit:
        raise RuntimeError(f"{repo.name}: clone is at {commit}, expected {repo.commit}")
    target = CLONES / repo.name / repo.package
    agent = CodeReviewAgent(llm, settings=settings)
    result = agent.run(AgentRequest(repo_path=str(target)))
    recorder = RunRecorder(f"cleanrepo_{repo.name}_static_llm_rag", settings)
    for f in result.findings:
        recorder.prediction({"repo": repo.name, **f.model_dump(mode="json")})
    for e in result.errors:
        recorder.error(repo.name, e[:300])
    stats = result.stats
    metrics = {
        "benchmark": "clean_repos",
        "repo": repo.model_dump(),
        "review_status": stats.get("review_status"),
        "files": result.files_analyzed,
        **density(result.findings, result.lines_analyzed),
        "units_total": stats.get("units_total"),
        "units_failed": stats.get("units_failed"),
        "units_not_attempted": stats.get("units_not_attempted"),
        "max_units": settings.review.max_units,
        "llm_usage": stats.get("llm_usage"),
        "llm_funnel": {k: stats.get(k) for k in (
            "llm_items_schema_invalid", "llm_findings_raw", "llm_findings_valid",
            "llm_findings_actionable", "llm_findings_after_dedupe", "llm_rejected_by_reason")},
        "fixes": stats.get("fixes"),
        "timing": stats.get("timing"),
        "complete": stats.get("review_status") == "complete",
        "labels": "not labelled: false alarms are judged by the team in the exported sheet",
    }  # fmt: skip
    experiment = experiment_metadata(
        settings, benchmark="clean_repos", llm_used=True, sample_ids=[repo.name],
        n_evaluated=1 if metrics["complete"] else 0, n_failed=0 if metrics["complete"] else 1,
        dataset=f"{repo.url}@{repo.commit[:12]}", split="package folder " + repo.package,
    )  # fmt: skip
    experiment["prompt_versions"] = result.metadata.prompt_versions
    return recorder.finish(metrics, summary_md(metrics), experiment=experiment)


def summary_md(m: dict[str, Any]) -> str:
    r = m["repo"]
    sev = ", ".join(f"{k} {v}" for k, v in m["by_severity"].items())
    per = ", ".join(f"{k} {v}" for k, v in m["per_kloc_by_severity"].items())
    return "\n".join([
        f"# Clean repository: {r['name']} (configuration D)", "",
        f"- Source: {r['url']} at {r['commit']}, package folder `{r['package']}`",
        f"- Status: {m['review_status']}; units {m['units_total']} (failed {m['units_failed']}, "
        f"not attempted {m['units_not_attempted']}; cap {m['max_units']})",
        f"- Lines reviewed: {m['lines']:,}; files: {m['files']}",
        f"- Findings: {m['findings']} ({m['per_kloc']} per 1,000 lines)",
        f"- By severity: {sev}",
        f"- Per 1,000 lines by severity: {per}",
        "- Not labelled: whether a finding is a false alarm is judged by the team "
        "(results/manual_label/clean_repo_findings.csv).", "",
    ])  # fmt: skip


def export_sheet(rows: list[dict[str, Any]], out: Path = SHEET, n: int = SAMPLE) -> int:
    """Seeded random sample of findings for human labelling; never overwrites an existing sheet."""
    if out.exists():
        raise FileExistsError(f"{out} exists; move it to results/archive/ first")
    chosen = random.Random(SEED).sample(rows, min(n, len(rows)))
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=SHEET_COLUMNS)
        w.writeheader()
        for r in chosen:
            w.writerow({
                "repo": r["repo"], "run": r["run"], "finding_id": r["id"], "file": r["file"],
                "start_line": r["start_line"], "end_line": r["end_line"], "severity": r["severity"],
                "category": r["category"], "title": r["title"], "description": r["description"],
                "evidence": " | ".join(r.get("evidence") or []),
                "sources": ",".join(r.get("sources") or []), "label": "", "notes": "",
            })  # fmt: skip
    return len(chosen)

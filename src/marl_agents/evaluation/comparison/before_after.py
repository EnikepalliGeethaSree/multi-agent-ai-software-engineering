"""Original vs improved system, built only from saved runs.

"Original" is the agent as it stood on Groq; "improved" is the agent on Gemini, with the classifier
when a run used it. A metric is only compared on the same benchmark, and a pair of runs on different
sample sets is shown as not comparable. A missing run is N/A with the command that produces it.
Nothing here is inferred: if the improved system is worse, the table says so.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from marl_agents.evaluation.runs import SavedRun, load_runs

ORIGINAL_PROVIDER = "groq"
IMPROVED_PROVIDER = "gemini"
FULL_AGENT = "static_llm_rag"
WITH_CLASSIFIER = "static_llm_rag_classifier"
RUN_LATER = "python -m marl_agents.cli eval"


class BeforeAfterRow(BaseModel):
    benchmark: str
    metric: str
    original: float | None = None
    improved: float | None = None
    original_run: str | None = None
    improved_run: str | None = None
    n: int | None = None
    note: str | None = None
    higher_is_better: bool | None = True


class BeforeAfterTable(BaseModel):
    rows: list[BeforeAfterRow]
    notes: list[str]


def _provider(run: SavedRun) -> str | None:
    exp_llm = run.experiment.get("llm")
    if isinstance(exp_llm, dict) and exp_llm.get("provider"):
        return str(exp_llm["provider"])
    provider = run.meta.get("llm_provider")
    if provider:
        return str(provider)
    llm = run.config.get("llm")
    return str(llm.get("provider")) if isinstance(llm, dict) else None


def _latest(runs: list[SavedRun], kind: str, provider: str, rest: str = "") -> SavedRun | None:
    matches = [
        r
        for r in runs
        if r.kind == kind
        and rest in r.rest
        and _provider(r) == provider
        and r.configuration is not None
        and r.configuration.key == FULL_AGENT
    ]
    return matches[-1] if matches else None


def _fingerprint(run: SavedRun | None) -> str | None:
    value = run.experiment.get("sample_fingerprint") if run else None
    return str(value) if value else None


def _value(run: SavedRun | None, path: tuple[str, ...]) -> float | None:
    node: Any = run.metrics if run else None
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
    return float(node) if isinstance(node, int | float) else None


def _rows(
    benchmark: str,
    before: SavedRun | None,
    after: SavedRun | None,
    metrics: Sequence[tuple[str, tuple[str, ...], bool | None]],
    command: str,
) -> list[BeforeAfterRow]:
    same = _fingerprint(before) == _fingerprint(after)
    note = None
    if after is None:
        note = f"improved run missing: {RUN_LATER} {command} --config configs/gemini.yaml"
    elif before is None:
        note = "no original run with the same benchmark"
    elif not same:
        note = "not comparable: the two runs used different samples"
    rows = []
    for label, path, higher in metrics:
        comparable = before is not None and after is not None and same
        rows.append(
            BeforeAfterRow(
                benchmark=benchmark,
                metric=label,
                original=_value(before, path),
                improved=_value(after, path) if comparable or before is None else None,
                original_run=before.name if before else None,
                improved_run=after.name if after else None,
                n=int(v) if (v := _value(after or before, ("n_evaluated",))) is not None else None,
                note=note,
                higher_is_better=higher,
            )
        )
    return rows


def _classification_rows(runs: list[SavedRun]) -> list[BeforeAfterRow]:
    """Original static analysis vs the classifier, both inside the classifier's evaluation run."""
    latest = [r for r in runs if r.kind == "classifier"]
    if not latest:
        return [
            BeforeAfterRow(
                benchmark="Needs-review classification",
                metric="ROC-AUC",
                note="no classifier evaluation: python -m marl_agents.cli eval classifier "
                "--model-dir data/models/change_cls",
            )
        ]
    run = latest[-1]
    primary = run.metrics.get("repo_disjoint", {})
    static = primary.get("baselines", {}).get("static_analysis") or {}
    metrics = [
        ("Accuracy", "accuracy", True),
        ("Precision", "precision", True),
        ("Recall", "recall", True),
        ("F1-score", "f1", True),
        ("False positive rate", "false_positive_rate", False),
        ("ROC-AUC", "roc_auc", True),
    ]
    return [
        BeforeAfterRow(
            benchmark="Needs-review classification",
            metric=label,
            original=static.get(key),
            improved=primary.get(key),
            original_run=static.get("source_run"),
            improved_run=run.name,
            n=primary.get("n"),
            higher_is_better=higher,
        )
        for label, key, higher in metrics
    ]


def _system_rows(runs: list[SavedRun]) -> list[BeforeAfterRow]:
    """LLM work per sample: the agent on Gemini without and with classifier prioritization."""
    keyed = [r for r in runs if r.kind == "codereviewer" and "msg" in r.rest]

    def latest(key: str) -> SavedRun | None:
        found = [
            r
            for r in keyed
            if _provider(r) == IMPROVED_PROVIDER and r.configuration and r.configuration.key == key
        ]
        return found[-1] if found else None

    return _rows(
        "LLM work per sample (Gemini, without vs with classifier)",
        latest(FULL_AGENT),
        latest(WITH_CLASSIFIER),
        [
            ("Average LLM calls", ("llm_work", "mean_calls"), False),
            ("Average input tokens", ("llm_work", "mean_input_tokens"), False),
            ("Average output tokens", ("llm_work", "mean_output_tokens"), False),
            ("Average execution time (s)", ("llm_work", "mean_total_sec"), False),
        ],
        "classifier-ablation --model-dir data/models/change_cls --limit 15 --max-llm-calls 45",
    )


def before_after(results_dir: Path) -> BeforeAfterTable:
    runs = load_runs(results_dir)
    rows: list[BeforeAfterRow] = []

    planted = [
        ("Precision", ("detection", "defect_precision"), True),
        ("Recall", ("detection", "recall"), True),
        (
            "False positives in the clean file",
            ("detection", "negative_file_false_positives"),
            False,
        ),
    ]
    rows += _rows(
        "Planted issues",
        _latest(runs, "planted", ORIGINAL_PROVIDER),
        _latest(runs, "planted", IMPROVED_PROVIDER),
        planted,
        "planted --configuration static_llm_rag",
    )

    msg = [
        ("Comment coverage", ("comment_coverage",), True),
        ("BLEU-4", ("text_metrics", "title_fix", "bleu4_smoothed"), True),
        ("ROUGE-L", ("text_metrics", "title_fix", "rouge_l"), True),
        ("chrF", ("text_metrics", "title_fix", "chrf"), True),
    ]
    rows += _rows(
        "CodeReviewer comments",
        _latest(runs, "codereviewer", ORIGINAL_PROVIDER, "msg"),
        _latest(runs, "codereviewer", IMPROVED_PROVIDER, "msg"),
        msg,
        "codereviewer --task msg --limit 40 --seed 42 --configuration static_llm_rag --workers 1",
    )

    rows += _classification_rows(runs)
    rows += _system_rows(runs)

    notes = [
        "Classification rows compare the original static analysis with the fine-tuned classifier "
        "on the same repository-disjoint test samples. They do not depend on the LLM provider.",
        "Original = the agent on Groq; improved = the agent on Gemini. Both are the full "
        "configuration (static + LLM + RAG).",
        "Execution time, LLM calls and token use by file size are in the file-size benchmark.",
        "The classifier has its own evaluation run, because it scores changes, not findings.",
    ]
    return BeforeAfterTable(rows=rows, notes=notes)


def _cell(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.3f}"


def before_after_md(table: BeforeAfterTable) -> str:
    lines = [
        "# Original vs improved system",
        "",
        "| Benchmark | Metric | Original | Improved | n | Note |",
        "|---|---|---:|---:|---:|---|",
    ]
    for r in table.rows:
        lines.append(
            f"| {r.benchmark} | {r.metric} | {_cell(r.original)} | {_cell(r.improved)} | "
            f"{r.n if r.n is not None else '-'} | {r.note or ''} |"
        )
    lines += ["", *[f"- {n}" for n in table.notes], ""]
    return "\n".join(lines)

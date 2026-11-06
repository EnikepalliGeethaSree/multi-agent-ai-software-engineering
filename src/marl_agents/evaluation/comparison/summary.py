"""Assemble the evaluation summary: master comparison table + one section per benchmark."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from marl_agents.evaluation.comparison.baselines import (
    planted_timing_table,
    retrieval_table,
    risk_table,
    timing_tables,
    usefulness_table,
)
from marl_agents.evaluation.comparison.common import config_row, is_mock
from marl_agents.evaluation.comparison.detection import codereviewer_tables, planted_table
from marl_agents.evaluation.comparison.models import (
    DEFINITIONS,
    Column,
    ComparisonTable,
    EvaluationSummary,
)
from marl_agents.evaluation.configurations import ORDER
from marl_agents.evaluation.runs import SavedRun, load_runs

SCOPE = [
    "Agent-level benchmark evaluation of the Code Review Agent on its own. These numbers are not "
    "system-level results of the five-agent platform (SWE-bench Lite resolve rate), which is not "
    "built yet.",
    "Configuration D (Static + LLM + RAG) is the shipped Code Review Agent; A-C are ablations "
    "that switch one component off.",
    "Every value comes from a saved run in experiments/results/ (run ids are listed per row). "
    "A configuration without a valid run is N/A with the command that produces it. Runs made "
    "with the offline mock LLM test the pipeline and are never shown as results.",
]

MASTER_COLUMNS = [
    Column(key="planted_precision", label="Precision", metric="precision", group="Planted issues"),
    Column(key="planted_recall", label="Recall", metric="recall", group="Planted issues"),
    Column(key="planted_f1", label="F1", metric="f1", group="Planted issues"),
    Column(key="cls_precision", label="Precision", metric="precision",
           group="CodeReviewer classification (raw)"),
    Column(key="cls_recall", label="Recall", metric="recall",
           group="CodeReviewer classification (raw)"),
    Column(key="cls_f1", label="F1", metric="f1", group="CodeReviewer classification (raw)"),
    Column(key="cls_roc_auc", label="ROC-AUC", metric="roc_auc",
           group="CodeReviewer classification (raw)"),
]  # fmt: skip


# A headline needs a paired sample large enough to mean something; smaller comparisons stay
# visible (with their warning) in their own section only.
MIN_PAIRED_N = 30


def master_table(planted: ComparisonTable, cls: ComparisonTable) -> ComparisonTable:
    by_planted = {r.configuration.key: r for r in planted.rows if r.configuration}
    by_cls = {r.configuration.key: r for r in cls.rows if r.configuration}
    cls_n = next((r.n for r in cls.rows if r.status == "ok"), None)
    small = cls_n is not None and cls_n < MIN_PAIRED_N
    rows = []
    for key in ORDER:
        row = config_row(key)
        sources = (("planted_", by_planted.get(key), ("precision", "recall", "f1")),
                   ("cls_", by_cls.get(key), ("precision", "recall", "f1", "roc_auc")))  # fmt: skip
        for prefix, src, metrics in sources:
            if prefix == "cls_" and small and src is not None and src.status == "ok":
                for metric in metrics:
                    row.values[prefix + metric] = None
                    row.na[prefix + metric] = (
                        f"paired CodeReviewer sample too small for a headline (n = {cls_n} < "
                        f"{MIN_PAIRED_N}); see section 2"
                    )
                continue
            for metric in metrics:
                col = prefix + metric
                if src is None or src.status != "ok":
                    row.values[col] = None
                    row.na[col] = (
                        "not run" if src is None or src.status == "not_run" else src.status
                    )
                    continue
                row.values[col] = src.values.get(metric)
                if metric in src.sd:
                    row.sd[col] = src.sd[metric]
                if src.values.get(metric) is None:
                    row.na[col] = src.na.get(metric, "undefined")
            if src is not None and src.status == "ok":
                row.run_ids += src.run_ids
                row.model = row.model or src.model
        if not row.run_ids:
            row.status = "not_run"
        rows.append(row)
    planted_n = next((r.n for r in planted.rows if r.status == "ok"), None)
    return ComparisonTable(
        id="master",
        section="Summary",
        title="Code Review evaluation summary",
        about="Detection quality of each configuration. Planted issues: ROC-AUC is not applicable "
        "(positives only). CodeReviewer: raw metrics on the paired sample set; adjusted metrics "
        "are in section 2.",
        columns=MASTER_COLUMNS,
        rows=rows,
        show_counts=False,
        conditions={
            "planted issues": f"{planted_n} labelled issues" if planted_n else "N/A",
            "CodeReviewer samples (paired)": cls_n if cls_n is not None else "N/A",
            "minimum paired n for a headline": MIN_PAIRED_N,
        },
        notes=[
            "Model, sample counts, failures and the exact runs behind every cell are in the "
            "benchmark sections below.",
        ],
    )


def build_summary(results_dir: Path) -> EvaluationSummary:
    runs = load_runs(results_dir)
    planted = planted_table(runs)
    cls_tables = codereviewer_tables(runs, "cls")
    msg_tables = codereviewer_tables(runs, "msg")
    tables = [
        planted,
        *cls_tables,
        *msg_tables,
        retrieval_table(runs),
        risk_table(runs),
        *timing_tables(runs),
        planted_timing_table(runs),
    ]
    useful = usefulness_table(runs)
    if useful is not None:
        tables.append(useful)
    mock = [r.name for r in runs if r.kind in {"planted", "codereviewer"} and is_mock(r)]
    master = master_table(planted, cls_tables[0])
    if mock:
        master.notes.append(f"{len(mock)} mock-LLM run(s) ignored (pipeline tests, not results).")
    return EvaluationSummary(
        generated_at=datetime.now(UTC).isoformat(),
        master=master,
        tables=tables,
        definitions=list(DEFINITIONS.values()),
        scope=SCOPE,
    )


def build_group_tables(runs: list[SavedRun]) -> list[ComparisonTable]:
    """Comparison tables for the runs of one ablation group (used by `eval ablation`)."""
    tables: list[ComparisonTable] = []
    if any(r.kind == "planted" for r in runs):
        tables += [planted_table(runs), planted_timing_table(runs)]
    for task in ("cls", "msg"):
        if any(r.kind == "codereviewer" and r.task == task for r in runs):
            tables += codereviewer_tables(runs, task)
    return tables

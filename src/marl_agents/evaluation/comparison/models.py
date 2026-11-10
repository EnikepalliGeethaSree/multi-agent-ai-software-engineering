"""Data model of the baseline-comparison tables, and the metric definitions shown with them."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from marl_agents.evaluation.configurations import ExperimentConfiguration


class MetricDefinition(BaseModel):
    key: str
    name: str
    definition: str
    scale: str
    higher_is_better: bool | None = True


DEFINITIONS: dict[str, MetricDefinition] = {
    d.key: d
    for d in (
        MetricDefinition(key="precision", name="Precision", definition="TP / (TP + FP)",
                         scale="0-1"),
        MetricDefinition(key="recall", name="Recall", definition="TP / (TP + FN)", scale="0-1"),
        MetricDefinition(key="f1", name="F1",
                         definition="2 x Precision x Recall / (Precision + Recall)", scale="0-1"),
        MetricDefinition(key="issue_recall", name="Issue recall",
                         definition="Labelled issues found / all labelled issues (any category).",
                         scale="0-1"),
        MetricDefinition(key="defect_precision", name="Defect precision",
                         definition="Correct defect findings / all defect findings. Style and "
                         "documentation findings are not in the answer key, so they are not "
                         "counted.", scale="0-1"),
        MetricDefinition(key="mixed_f1", name="F1 (mixed basis)",
                         definition="Harmonic mean of defect precision and issue recall. The two "
                         "have different denominators, so this is not a standard F1.",
                         scale="0-1"),
        MetricDefinition(key="roc_auc", name="ROC-AUC",
                         definition="Probability that a randomly chosen positive case is scored "
                         "above a randomly chosen negative one (Mann-Whitney U; ties count 1/2): "
                         "ranking quality across all thresholds. 0.5 = chance.", scale="0-1"),
        MetricDefinition(key="accuracy", name="Accuracy", definition="(TP + TN) / N",
                         scale="0-1"),
        MetricDefinition(key="bleu4", name="BLEU-4",
                         definition="Smoothed sentence BLEU-4 (Lin & Och 2004 +1 smoothing for "
                         "n >= 2), averaged over samples, x100 (CodeReviewer convention).",
                         scale="0-100"),
        MetricDefinition(key="rouge_l", name="ROUGE-L",
                         definition="Longest-common-subsequence F1 of word tokens, averaged over "
                         "samples, x100.", scale="0-100"),
        MetricDefinition(key="chrf", name="chrF",
                         definition="Character 1-6-gram F-score (beta = 2, Popovic 2015), averaged "
                         "over samples, x100.", scale="0-100"),
        MetricDefinition(key="coverage", name="Coverage",
                         definition="Share of diffs for which the agent produced a comment.",
                         scale="0-1"),
        MetricDefinition(key="recall_at_10", name="Recall@10",
                         definition="Share of a query's relevant chunks (its callees in the AST "
                         "call graph) found in the top 10 retrieved; averaged over queries.",
                         scale="0-1"),
        MetricDefinition(key="mrr", name="MRR",
                         definition="Mean over queries of 1 / rank of the first relevant chunk.",
                         scale="0-1"),
        MetricDefinition(key="precision_at_top10", name="Precision@Top10%",
                         definition="Of the 10% of hunks ranked riskiest, the share a human "
                         "reviewer commented on.", scale="0-1"),
        MetricDefinition(key="seconds", name="Time",
                         definition="Wall-clock seconds measured with time.perf_counter().",
                         scale="seconds", higher_is_better=False),
        MetricDefinition(key="rating", name="Rating",
                         definition="Mean 1-5 rating by the LLM judge (supplementary).",
                         scale="1-5"),
    )
}  # fmt: skip


class Column(BaseModel):
    key: str
    label: str
    metric: str | None = Field(default=None, description="DEFINITIONS key (scale, direction).")
    group: str | None = Field(default=None, description="Column group, e.g. RAW / ADJUSTED.")
    digits: int = 3


class Row(BaseModel):
    label: str
    configuration: ExperimentConfiguration | None = None
    status: Literal["ok", "not_run", "incomplete"] = "ok"
    values: dict[str, float | int | None] = Field(default_factory=dict)
    sd: dict[str, float | None] = Field(default_factory=dict, description="Over repeated runs.")
    spread: dict[str, list[float | None]] = Field(
        default_factory=dict, description="[min, max] of repeated measurements (timing)."
    )
    na: dict[str, str] = Field(default_factory=dict, description="Metric -> why it is N/A.")
    ci: dict[str, list[float | None]] = Field(
        default_factory=dict, description="Metric -> [low, high] 95% interval (evaluation/stats)."
    )
    n: int | None = None
    n_failed: int | None = None
    n_runs: int = 0
    model: str | None = None
    run_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    how_to_run: str | None = None


class FairnessCheck(BaseModel):
    name: str
    ok: bool | None = Field(description="None = not recorded / not applicable.")
    detail: str = ""


class ComparisonTable(BaseModel):
    id: str
    section: str
    title: str
    about: str = ""
    columns: list[Column]
    rows: list[Row]
    conditions: dict[str, Any] = Field(default_factory=dict)
    fairness: list[FairnessCheck] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    statistics: list[str] = Field(
        default_factory=list, description="Wilson intervals, McNemar and bootstrap tests."
    )
    notes: list[str] = Field(default_factory=list)
    supplementary: bool = False
    show_counts: bool = Field(default=True, description="Render the n / failed / runs columns.")
    badges: list[str] = Field(default_factory=list, description="Status and provider labels.")
    warning: str | None = Field(default=None, description="Shown above the table, always visible.")


class StatusItem(BaseModel):
    name: str
    status: Literal["complete", "preliminary", "incomplete", "pending"]
    detail: str = ""
    run_ids: list[str] = Field(default_factory=list)
    command: str | None = None


class EvaluationStatus(BaseModel):
    items: list[StatusItem] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    unfinished_runs: list[str] = Field(default_factory=list)


class EvaluationSummary(BaseModel):
    generated_at: str
    master: ComparisonTable | None
    tables: list[ComparisonTable]
    definitions: list[MetricDefinition]
    scope: list[str]
    status: EvaluationStatus | None = None

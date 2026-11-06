"""Markdown rendering of comparison tables (summary.md, ablation run summaries)."""

from __future__ import annotations

from marl_agents.evaluation.comparison.models import (
    DEFINITIONS,
    Column,
    ComparisonTable,
    EvaluationSummary,
    Row,
)

MARK = {True: "✓", False: "✗", None: "?"}


def _cell(row: Row, col: Column) -> str:
    if row.status != "ok":
        return "N/A"
    value = row.values.get(col.key)
    if value is None:
        return "N/A"
    text = f"{value:.{col.digits}f}" if isinstance(value, float) else f"{value}"
    sd = row.sd.get(col.key)
    return f"{text} ± {sd:.{col.digits}f}" if sd is not None else text


def _na_lines(row: Row, columns: list[Column]) -> dict[str, str]:
    """One line per (row, reason): 'all metrics' when a reason covers every column."""
    labels = {c.key: f"{c.group} {c.label}" if c.group else c.label for c in columns}
    by_reason: dict[str, list[str]] = {}
    for key, why in row.na.items():
        by_reason.setdefault(why, []).append(key)
    groups: dict[str, set[str]] = {}
    for c in columns:
        if c.group:
            groups.setdefault(c.group, set()).add(c.key)
    out = {}
    for why, keys in by_reason.items():
        if "*" in keys or set(keys) >= set(labels):
            out[f"{row.label} / all metrics"] = why
            continue
        names, rest = [], set(keys)
        for group, members in groups.items():
            if members <= rest:  # a whole column group: name it once
                names.append(f"{group} (all)")
                rest -= members
        names += [labels.get(k, k) for k in keys if k in rest]
        out[f"{row.label} / " + ", ".join(names)] = why
    return out


def table_md(t: ComparisonTable) -> str:
    has_config = any(r.configuration for r in t.rows)
    head = ["Configuration", "Static", "LLM", "RAG"] if has_config else ["Method"]
    head += [f"{c.group} {c.label}" if c.group else c.label for c in t.columns]
    head += ["n", "failed", "runs"] if t.show_counts else []
    head += ["model"] if has_config else []
    lines = [f"### {t.title}", ""]
    if t.about:
        lines += [t.about, ""]
    if t.conditions:
        lines += [f"- **{k}:** {v}" for k, v in t.conditions.items() if v is not None] + [""]
    lines += ["| " + " | ".join(head) + " |", "|---" * len(head) + "|"]
    na_reasons: dict[str, str] = {}
    for r in t.rows:
        cells = [r.label]
        if has_config:
            c = r.configuration
            cells += [MARK[c.static], MARK[c.llm], MARK[c.rag]] if c else ["", "", ""]
        cells += [_cell(r, col) for col in t.columns]
        if t.show_counts:
            runs = (str(r.n_runs) if r.n_runs else "-") if r.status == "ok" else r.status
            cells += [
                "-" if r.n is None else str(r.n),
                "-" if r.n_failed is None else str(r.n_failed),
                runs.replace("_", " "),
            ]
        if has_config:
            cells.append(r.model or ("-" if not (r.configuration and r.configuration.llm) else "?"))
        lines.append("| " + " | ".join(cells) + " |")
        na_reasons.update(_na_lines(r, t.columns))
    lines.append("")
    if any(r.sd for r in t.rows):
        lines += ["Values with ± are the mean ± sample standard deviation over repeated runs.", ""]
    not_run = [r for r in t.rows if r.status != "ok" and r.how_to_run]
    if na_reasons:
        lines += ["N/A:"] + [f"- {k}: {v}" for k, v in na_reasons.items()] + [""]
    if not_run:
        lines += ["To run:"] + [f"- {r.label}: `{r.how_to_run}`" for r in not_run] + [""]
    if t.fairness:
        lines += ["Fairness checks:"]
        lines += [f"- {MARK[c.ok]} {c.name}: {c.detail}" for c in t.fairness] + [""]
    if t.observations:
        lines += ["Observations (computed from the numbers above):"]
        lines += [f"- {o}" for o in t.observations] + [""]
    if t.notes:
        lines += [f"- {n}" for n in t.notes] + [""]
    sources = sorted({rid for r in t.rows for rid in r.run_ids})
    if sources:
        lines += ["Source runs: " + ", ".join(f"`{x}`" for x in sources), ""]
    return "\n".join(lines)


def tables_md(tables: list[ComparisonTable], title: str) -> str:
    return "\n".join([f"# {title}", "", *[table_md(t) for t in tables]])


def definitions_md() -> str:
    lines = ["| Metric | Definition | Scale | Better |", "|---|---|---|---|"]
    for d in DEFINITIONS.values():
        better = {True: "higher", False: "lower", None: "-"}[d.higher_is_better]
        lines.append(f"| {d.name} | {d.definition} | {d.scale} | {better} |")
    return "\n".join(lines)


def summary_md(summary: EvaluationSummary) -> str:
    lines = ["# Code Review Agent: baseline comparison", ""]
    lines += [f"- {s}" for s in summary.scope] + [""]
    if summary.master is not None:
        lines += [table_md(summary.master)]
    section = None
    for t in summary.tables:
        if t.section != section:
            section = t.section
            lines += [f"## {section}", ""]
        lines.append(table_md(t))
    lines += ["## Metric definitions", "", definitions_md(), ""]
    return "\n".join(lines)

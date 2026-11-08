"""Shared helpers: run selection, N/A-safe arithmetic, fairness checks, observation wording."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from marl_agents.evaluation.comparison.models import Column, FairnessCheck, Row
from marl_agents.evaluation.configurations import CONFIGURATIONS, ORDER, ExperimentConfiguration
from marl_agents.evaluation.metrics.efficiency import mean_sd
from marl_agents.evaluation.runs import SavedRun

CMD = "python -m marl_agents.cli eval"
LLM_CONFIG = "--config configs/gemini.yaml"
ALL_CONFIGS = ",".join(ORDER)
# A comparison needs a paired sample large enough to mean something. Smaller ones stay visible,
# labelled preliminary, and are never promoted to a headline.
MIN_PAIRED_N = 30


def ratio(num: float, den: float) -> float | None:
    """num / den, or None (shown as N/A) when the denominator is 0."""
    return num / den if den else None


def prf(tp: int, fp: int, fn: int) -> tuple[float | None, float | None, float | None]:
    """Precision, recall, F1 from counts; an undefined ratio is None, never a made-up 0 or 1."""
    p, r = ratio(tp, tp + fp), ratio(tp, tp + fn)
    if p is None or r is None:
        return p, r, None
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def provider_badge(runs: Iterable[SavedRun]) -> str | None:
    """Names the provider and model behind a table, so eras are never mistaken for each other."""
    pairs = sorted({(str(r.provider), str(r.model)) for r in runs if r.provider and r.model})
    if not pairs:
        return None
    models = ", ".join(sorted({model for _, model in pairs}))
    providers = {provider for provider, _ in pairs}
    if providers == {"gemini"}:
        return f"Gemini: {models}"
    return f"Historical: {', '.join(sorted(p.title() for p in providers))} ({models})"


def is_mock(run: SavedRun) -> bool:
    """LLM configurations run with the offline mock provider test the pipeline; they are not
    results and never enter a comparison table."""
    c = run.configuration
    return bool(c and c.llm and (run.provider == "mock" or run.provider is None))


def pick(runs: list[SavedRun], key: str, valid: Callable[[SavedRun], bool]) -> list[SavedRun]:
    """The latest valid run of a configuration; with all its repeats when it belongs to a group."""
    cands = [r for r in runs if r.configuration and r.configuration.key == key and valid(r)]
    if not cands:
        return []
    latest = cands[-1]
    if latest.group_id:
        return [r for r in cands if r.group_id == latest.group_id]
    return [latest]


def config_row(key: str) -> Row:
    c = CONFIGURATIONS[key]
    return Row(label=c.label, configuration=c)


def not_run_row(key: str, command: str, reason: str = "no saved run") -> Row:
    row = config_row(key)
    row.status = "not_run"
    row.na = {"*": reason}
    row.how_to_run = command
    return row


def fill_mean(
    row: Row, per_run: list[dict[str, float | int | None]], columns: Iterable[Column]
) -> None:
    """Row value = the single run's value, or the mean (+ sample SD) over repeated runs."""
    for col in columns:
        values = [m.get(col.key) for m in per_run]
        mean, sd, n = mean_sd(v for v in values if isinstance(v, int | float))
        if n == 0:
            row.values[col.key] = None
            continue
        if len(per_run) == 1 and isinstance(values[0], int):
            row.values[col.key] = values[0]
        else:
            row.values[col.key] = mean
        if len(per_run) > 1:
            row.sd[col.key] = sd


def flags(c: ExperimentConfiguration | None) -> str:
    if c is None:
        return "?"
    return " / ".join(
        f"{name} {'on' if on else 'off'}"
        for name, on in (("static", c.static), ("LLM", c.llm), ("RAG", c.rag))
    )


def _same(values: list[Any], name: str, what: str) -> FairnessCheck:
    known = [v for v in values if v is not None]
    if not known:
        return FairnessCheck(name=name, ok=None, detail=f"{what} not recorded")
    distinct = sorted({str(v) for v in known})
    missing = len(values) - len(known)
    detail = ", ".join(distinct) + (f" ({missing} run(s) did not record it)" if missing else "")
    return FairnessCheck(name=name, ok=len(distinct) == 1, detail=detail)


def fairness_checks(
    chosen: dict[str, list[SavedRun]], same_samples: FairnessCheck
) -> list[FairnessCheck]:
    runs = [r for rs in chosen.values() for r in rs]
    llm_runs = [r for r in runs if r.configuration and r.configuration.llm]
    groups = {r.group_id for r in runs}
    checks = [same_samples]
    if llm_runs:
        checks.append(_same([r.model for r in llm_runs], "Same LLM model", "model"))
        checks.append(_same([r.temperature for r in llm_runs], "Same temperature", "temperature"))
        checks.append(
            _same(
                [r.experiment.get("prompt_versions") or None for r in llm_runs],
                "Same prompt versions",
                "prompt versions",
            )
        )
        reused = [r for r in llm_runs if r.experiment.get("llm_cache_reused") is True]
        recorded = [r for r in llm_runs if r.experiment.get("llm_cache_reused") is not None]
        if recorded:
            checks.append(
                FairnessCheck(
                    name="Fresh LLM calls",
                    ok=not reused,
                    detail="replies reused from the cache in "
                    + ", ".join(sorted({r.configuration.label for r in reused if r.configuration}))
                    + ": quality metrics compare, times do not"
                    if reused
                    else "every LLM run called the model",
                )
            )
    checks.append(
        _same([r.confidence_threshold for r in runs], "Same confidence threshold", "threshold")
    )
    checks.append(
        _same(
            [r.experiment.get("evaluation_rules") or None for r in runs],
            "Same evaluation rules",
            "evaluation rules",
        )
    )
    if runs:
        checks.append(
            FairnessCheck(
                name="Run together (one ablation group)",
                ok=len(groups) == 1 and None not in groups,
                detail=", ".join(sorted(g or "separate runs" for g in groups)),
            )
        )
    return checks


def fmt(x: float | None, digits: int = 3) -> str:
    return "N/A" if x is None else f"{x:.{digits}f}"


def compare(
    metric: str, a_label: str, a: float | None, b_label: str, b: float | None, digits: int = 3
) -> str | None:
    """A neutral sentence about two numbers (None when either is missing)."""
    if a is None or b is None:
        return None
    if round(a, digits) == round(b, digits):
        text = f"{a_label} and {b_label} have the same {metric} ({fmt(a, digits)})."
        return text[0].upper() + text[1:]
    higher, lower = (a_label, b_label) if a > b else (b_label, a_label)
    hi, lo = max(a, b), min(a, b)
    text = f"{higher} has a higher {metric} than {lower} ({fmt(hi, digits)} vs {fmt(lo, digits)})."
    return text[0].upper() + text[1:]

"""Usefulness of review comments: LLM judge, human-rating kit, judge-vs-human agreement.

BLEU against one human reference punishes a comment that finds a *different* real problem, so we
also rate each comment directly on the two criteria of CodeReviewer's human evaluation (Li et al.,
2022): relevance and informativeness, 1-5.

1. `run_usefulness`: an LLM judge rates the agent's comment AND the human reference comment of the
   same diff, blind (it never knows which is which) and reference-free (it sees only the diff).
   Use a different model from the reviewer to limit self-preference bias.
2. `export_human_kit`: a shuffled, blinded CSV for people to rate the same items, plus a key file.
3. `agreement_from_sheets`: how well the judge agrees with the human raters (weighted kappa,
   Spearman) and what the humans concluded. Only with good agreement is the judge's verdict on the
   larger sample worth citing.
"""

from __future__ import annotations

import csv
import json
import logging
import random
import statistics
import threading
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from marl_agents.evaluation.metrics import (
    agreement_rates,
    bootstrap_ci,
    spearman,
    weighted_kappa,
)
from marl_agents.evaluation.prompts import load_eval_prompt
from marl_agents.evaluation.recorder import RunRecorder
from marl_agents.llm.base import LLMError, LLMProvider, Message, Usage

logger = logging.getLogger(__name__)

CRITERIA = ("relevance", "informativeness")
MAX_DIFF_CHARS = 6000
MAX_COMMENT_CHARS = 2000
SYSTEM = "You are a strict, fair code-review evaluator. Reply with a JSON object only."
Source = Literal["agent", "human"]


class UsefulnessVerdict(BaseModel):
    relevance: int = Field(ge=1, le=5)
    informativeness: int = Field(ge=1, le=5)
    rationale: str = ""


@dataclass
class RatingItem:
    sample_id: str
    source: Source
    diff: str
    comment: str


def judge_comment(
    llm: LLMProvider, diff: str, comment: str, usage: Usage | None = None
) -> UsefulnessVerdict:
    if not comment.strip():
        return UsefulnessVerdict(relevance=1, informativeness=1, rationale="empty comment")
    prompt = load_eval_prompt("usefulness").render(
        diff=diff[:MAX_DIFF_CHARS], comment=comment[:MAX_COMMENT_CHARS]
    )
    return llm.generate_structured(
        [Message(role="system", content=SYSTEM), Message(role="user", content=prompt)],
        UsefulnessVerdict,
        usage=usage,
    )


def items_from_run(run_dir: Path, patches: dict[str, str]) -> tuple[list[RatingItem], int]:
    """Agent + human comment items from a CodeReviewer `msg` run. Returns (items, n_no_comment)."""
    items: list[RatingItem] = []
    no_comment = 0
    with (run_dir / "predictions.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            sid = row["sample_id"]
            if sid not in patches:
                continue
            agent = row.get("comment_full") or row.get("comment") or ""
            if agent.strip():
                items.append(RatingItem(sid, "agent", patches[sid], agent))
            else:
                no_comment += 1
            if (row.get("reference") or "").strip():
                items.append(RatingItem(sid, "human", patches[sid], row["reference"]))
    return items, no_comment


def _mean_ci(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "ci95": None}
    lo, hi = bootstrap_ci(values, lambda s: sum(s) / len(s))
    return {"n": len(values), "mean": round(statistics.fmean(values), 3), "ci95": [lo, hi]}


def usefulness_metrics(scored: list[tuple[RatingItem, UsefulnessVerdict]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for source in ("agent", "human"):
        rows = [v for it, v in scored if it.source == source]
        out[source] = {
            c: {
                **_mean_ci([getattr(v, c) for v in rows]),
                "distribution": dict(sorted(Counter(getattr(v, c) for v in rows).items())),
                "share_ge4": round(sum(1 for v in rows if getattr(v, c) >= 4) / len(rows), 3)
                if rows
                else None,
            }
            for c in CRITERIA
        }
    by_sample: dict[str, dict[str, UsefulnessVerdict]] = {}
    for it, v in scored:
        by_sample.setdefault(it.sample_id, {})[it.source] = v
    pairs = [(d["agent"], d["human"]) for d in by_sample.values() if len(d) == 2]
    paired: dict[str, Any] = {"n": len(pairs)}
    for c in CRITERIA:
        diffs = [getattr(a, c) - getattr(h, c) for a, h in pairs]
        paired[c] = {
            "mean_diff_agent_minus_human": round(statistics.fmean(diffs), 3) if diffs else None,
            "ci95": list(bootstrap_ci(diffs, lambda s: sum(s) / len(s))) if diffs else None,
            "agent_better": sum(1 for d in diffs if d > 0),
            "tie": sum(1 for d in diffs if d == 0),
            "human_better": sum(1 for d in diffs if d < 0),
        }
    out["paired"] = paired
    return out


def run_usefulness(
    llm: LLMProvider,
    items: list[RatingItem],
    recorder: RunRecorder,
    workers: int = 4,
    usage: Usage | None = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[list[tuple[RatingItem, UsefulnessVerdict]], dict[str, Any]]:
    progress = progress or (lambda m: logger.info(m))
    scored: list[tuple[RatingItem, UsefulnessVerdict]] = []
    lock = threading.Lock()
    failures: Counter[str] = Counter()

    def one(item: RatingItem) -> None:
        try:
            verdict = judge_comment(llm, item.diff, item.comment, usage)
        except LLMError as exc:
            with lock:
                failures["llm_error"] += 1
                recorder.error(f"{item.sample_id}:{item.source}", str(exc))
            return
        with lock:
            scored.append((item, verdict))
            recorder.prediction(
                {
                    "sample_id": item.sample_id,
                    "source": item.source,
                    "comment": item.comment,
                    **verdict.model_dump(),
                }
            )
            if len(scored) % 20 == 0:
                progress(f"judged {len(scored)}/{len(items)}")

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(one, items))
    metrics = usefulness_metrics(scored)
    metrics.update(
        n_items=len(items),
        n_judged=len(scored),
        failures=dict(failures),
        prompt_version=load_eval_prompt("usefulness").version,
    )
    return scored, metrics


def usefulness_summary_md(metrics: dict[str, Any], title: str, judge: str, reviewer: str) -> str:
    def fmt(m: dict[str, Any]) -> str:
        if m["mean"] is None:
            return "n/a"
        lo, hi = m["ci95"]
        return f"{m['mean']:.2f} ({lo:.2f}-{hi:.2f})"

    lines = [
        f"# {title}",
        "",
        f"Judge model: `{judge}` (reviewer: `{reviewer}`). Prompt "
        f"`usefulness` v{metrics['prompt_version']}. Blind, reference-free, 1-5 scale.",
        f"Items judged: {metrics['n_judged']} of {metrics['n_items']} "
        f"(failures: {metrics['failures'] or 'none'}); "
        f"samples where the agent produced no comment: {metrics.get('agent_no_comment', 0)}.",
        "",
        "| Comment author | n | Relevance (95% CI) | Informativeness (95% CI) "
        "| Rel >= 4 | Inf >= 4 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for source, label in (("agent", "Agent"), ("human", "Human reviewer (dataset)")):
        m = metrics[source]
        lines.append(
            f"| {label} | {m['relevance']['n']} | {fmt(m['relevance'])} | "
            f"{fmt(m['informativeness'])} | {m['relevance']['share_ge4']} | "
            f"{m['informativeness']['share_ge4']} |"
        )
    p = metrics["paired"]
    lines += ["", f"Paired comparison on {p['n']} diffs with both comments (agent - human):", ""]
    for c in CRITERIA:
        d = p[c]
        if d["mean_diff_agent_minus_human"] is None:
            continue
        lo, hi = d["ci95"]
        lines.append(
            f"- {c}: {d['mean_diff_agent_minus_human']:+.2f} (95% CI {lo:+.2f} to {hi:+.2f}); "
            f"agent better {d['agent_better']}, tie {d['tie']}, human better {d['human_better']}"
        )
    lines += [
        "",
        "An LLM judge is a proxy, not ground truth: check it against human ratings "
        "(`eval agreement`) before citing these numbers.",
        "",
    ]
    return "\n".join(lines)


# ---- human rating kit ---------------------------------------------------------------------------

KIT_README = """How to rate (takes ~1 minute per row)

Open rating_sheet.csv in Excel / LibreOffice / Google Sheets. For each row, read the diff and the
review comment, then fill in two numbers from 1 to 5. You do not know who wrote each comment:
some are from human reviewers, some from the tool. Rate each row on its own.

relevance        5 = real problem/improvement in the changed code, clearly correct
                 3 = related, but weak, debatable or partly wrong
                 1 = irrelevant or wrong about the code
informativeness  5 = says what is wrong, why, and what to do instead
                 3 = a problem without a clear action (or the reverse)
                 1 = no usable information

Use 2 and 4 for in-between. Leave a row blank if you cannot judge it (it is then skipped).
Do not open key.csv until you have finished. Each rater fills in their own copy of the sheet.
"""


def export_human_kit(
    scored: list[tuple[RatingItem, UsefulnessVerdict]], out_dir: Path, size: int, seed: int = 42
) -> dict[str, Path]:
    """Blinded rating sheet for `size` diffs (both comments of each), shuffled, plus the key."""
    rng = random.Random(seed)
    by_sample: dict[str, list[tuple[RatingItem, UsefulnessVerdict]]] = {}
    for it, v in scored:
        by_sample.setdefault(it.sample_id, []).append((it, v))
    complete = sorted(sid for sid, rows in by_sample.items() if len(rows) == 2)
    chosen = rng.sample(complete, min(size, len(complete)))
    rows = [row for sid in chosen for row in by_sample[sid]]
    rng.shuffle(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet, key = out_dir / "rating_sheet.csv", out_dir / "key.csv"
    with sheet.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["item", "diff", "comment", "relevance", "informativeness", "notes"])
        for i, (it, _v) in enumerate(rows, start=1):
            w.writerow([i, it.diff[:MAX_DIFF_CHARS], it.comment, "", "", ""])
    with key.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["item", "sample_id", "source", "judge_relevance", "judge_informativeness"])
        for i, (it, v) in enumerate(rows, start=1):
            w.writerow([i, it.sample_id, it.source, v.relevance, v.informativeness])
    readme = out_dir / "README.txt"
    readme.write_text(KIT_README, encoding="utf-8")
    return {"sheet": sheet, "key": key, "readme": readme}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _rating(value: str | None) -> int | None:
    try:
        r = int(float((value or "").strip()))
    except ValueError:
        return None
    return r if 1 <= r <= 5 else None


def _compare(a: list[int], b: list[int]) -> dict[str, Any]:
    return {
        "n": len(a),
        "weighted_kappa": weighted_kappa(a, b),
        "spearman": spearman(a, b),
        **agreement_rates(a, b),
    }


def agreement_from_sheets(key_csv: Path, sheets: list[Path]) -> dict[str, Any]:
    """Judge vs. each human rater, human vs. human (first two sheets), and the human verdict."""
    key = {row["item"]: row for row in _read_csv(key_csv)}
    raters: list[dict[str, dict[str, int]]] = []
    skipped: list[int] = []
    for sheet in sheets:
        ratings: dict[str, dict[str, int]] = {}
        blank = 0
        for row in _read_csv(sheet):
            vals = {c: _rating(row.get(c)) for c in CRITERIA}
            if row.get("item") in key and all(v is not None for v in vals.values()):
                ratings[row["item"]] = {c: v for c, v in vals.items() if v is not None}
            else:
                blank += 1
        raters.append(ratings)
        skipped.append(blank)

    out: dict[str, Any] = {"n_raters": len(sheets), "skipped_rows": skipped, "judge_vs_human": []}
    for ratings in raters:
        items = sorted(ratings, key=int)
        out["judge_vs_human"].append(
            {
                c: _compare(
                    [int(key[i][f"judge_{c}"]) for i in items], [ratings[i][c] for i in items]
                )
                for c in CRITERIA
            }
        )
    if len(raters) >= 2:
        common = sorted(set(raters[0]) & set(raters[1]), key=int)
        out["human_vs_human"] = {
            c: _compare([raters[0][i][c] for i in common], [raters[1][i][c] for i in common])
            for c in CRITERIA
        }
    # The human verdict: mean human rating per comment author (averaged over raters per item).
    verdict: dict[str, Any] = {}
    for source in ("agent", "human"):
        verdict[source] = {}
        for c in CRITERIA:
            per_item = [
                statistics.fmean(r[i][c] for r in raters if i in r)
                for i, k in key.items()
                if k["source"] == source and any(i in r for r in raters)
            ]
            verdict[source][c] = {
                "n": len(per_item),
                "mean": round(statistics.fmean(per_item), 3) if per_item else None,
            }
    out["human_ratings_by_author"] = verdict
    return out


def agreement_summary_md(m: dict[str, Any]) -> str:
    def f(x: float | None) -> str:
        return "n/a" if x is None else f"{x:.3f}"

    lines = [
        "# LLM judge vs. human ratings",
        "",
        f"{m['n_raters']} rater sheet(s); rows skipped (blank/invalid): {m['skipped_rows']}.",
        "",
        "| Comparison | Criterion | n | Weighted kappa | Spearman | Exact | Within 1 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    comparisons = [(f"judge vs rater {i + 1}", r) for i, r in enumerate(m["judge_vs_human"])]
    if "human_vs_human" in m:
        comparisons.append(("rater 1 vs rater 2", m["human_vs_human"]))
    for name, comp in comparisons:
        for c in CRITERIA:
            x = comp[c]
            lines.append(
                f"| {name} | {c} | {x['n']} | {f(x['weighted_kappa'])} | {f(x['spearman'])} "
                f"| {x['exact']:.2f} | {x['within_one']:.2f} |"
            )
    v = m["human_ratings_by_author"]
    lines += [
        "",
        "Human ratings by comment author (mean of raters):",
        "",
        "| Author | Relevance | Informativeness | n |",
        "|---|---:|---:|---:|",
    ]
    for source, label in (("agent", "Agent"), ("human", "Human reviewer")):
        lines.append(
            f"| {label} | {f(v[source]['relevance']['mean'])} | "
            f"{f(v[source]['informativeness']['mean'])} | {v[source]['relevance']['n']} |"
        )
    lines += [
        "",
        "Rule of thumb (Landis & Koch): kappa 0.41-0.60 moderate, 0.61-0.80 substantial. "
        "Cite the judge's large-sample numbers only if judge-vs-human agreement is comparable "
        "to human-vs-human agreement.",
        "",
    ]
    return "\n".join(lines)

"""Phase 3 evaluation: LLM-judge usefulness, human rating kit + agreement, hunk-risk metrics."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from marl_agents.config import Settings
from marl_agents.evaluation.datasets.codereviewer import CodeReviewerSample
from marl_agents.evaluation.recorder import RunRecorder
from marl_agents.evaluation.runners import change_risk
from marl_agents.evaluation.runners import usefulness as uf
from marl_agents.evaluation.runners.code_review import compose_comment, make_agent
from marl_agents.llm import MockLLMProvider

DIFF = "@@ -1,2 +1,2 @@\n def avg(xs):\n-    return sum(xs) / len(xs)\n+    return sum(xs) / max(len(xs), 1)\n"


def _verdict(rel: int, inf: int) -> str:
    return json.dumps({"relevance": rel, "informativeness": inf, "rationale": "r"})


def test_judge_prompt_is_blind_and_treats_input_as_data() -> None:
    llm = MockLLMProvider(responses=[_verdict(4, 3)])
    v = uf.judge_comment(llm, DIFF, "Division by zero on empty list. Return 0.0 instead.")
    assert (v.relevance, v.informativeness) == (4, 3)
    prompt = llm.calls[0][-1].content
    assert "max(len(xs), 1)" in prompt and "Division by zero" in prompt
    assert "DATA" in prompt and "You do not know who wrote the comment" in prompt
    # empty comment: no LLM call, lowest scores
    empty = uf.judge_comment(llm, DIFF, "  ")
    assert (empty.relevance, empty.informativeness) == (1, 1) and len(llm.calls) == 1


def test_judge_rejects_out_of_range_scores() -> None:
    llm = MockLLMProvider(responses=[_verdict(7, 3), _verdict(5, 3)])  # retried once
    assert uf.judge_comment(llm, DIFF, "x").relevance == 5


def _scored() -> list[tuple[uf.RatingItem, uf.UsefulnessVerdict]]:
    out = []
    for i, (a, h) in enumerate([((5, 4), (3, 3)), ((4, 4), (4, 2)), ((2, 1), (5, 5))]):
        sid = f"s{i}"
        out.append(
            (
                uf.RatingItem(sid, "agent", DIFF, f"agent {i}"),
                uf.UsefulnessVerdict(relevance=a[0], informativeness=a[1]),
            )
        )
        out.append((uf.RatingItem(sid, "human", DIFF, f"human {i}"),
                    uf.UsefulnessVerdict(relevance=h[0], informativeness=h[1])))  # fmt: skip
    return out


def test_usefulness_metrics_hand_computed() -> None:
    m = uf.usefulness_metrics(_scored())
    assert m["agent"]["relevance"]["mean"] == pytest.approx(11 / 3, abs=1e-3)
    assert m["human"]["informativeness"]["mean"] == pytest.approx(10 / 3, abs=1e-3)
    assert m["agent"]["relevance"]["distribution"] == {2: 1, 4: 1, 5: 1}
    assert m["agent"]["relevance"]["share_ge4"] == pytest.approx(0.667, abs=1e-3)
    p = m["paired"]["relevance"]  # diffs +2, 0, -3
    assert m["paired"]["n"] == 3 and p["mean_diff_agent_minus_human"] == pytest.approx(
        -1 / 3, abs=1e-3
    )
    assert (p["agent_better"], p["tie"], p["human_better"]) == (1, 1, 1)


def test_run_usefulness_records_failures(tmp_path: Path, settings: Settings) -> None:
    items = [uf.RatingItem("s1", "agent", DIFF, "a"), uf.RatingItem("s1", "human", DIFF, "h")]
    llm = MockLLMProvider(responses=[_verdict(4, 4), "not json", "still not json"])
    rec = RunRecorder("t", settings, base_dir=tmp_path)
    _scored_items, metrics = uf.run_usefulness(llm, items, rec, workers=1)
    assert metrics["n_judged"] == 1 and metrics["failures"] == {"llm_error": 1}
    rec.finish(metrics, "x")
    assert len((rec.dir / "errors.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_items_from_run_prefers_full_comment(tmp_path: Path) -> None:
    rows = [
        {"sample_id": "a", "comment": "short", "comment_full": "full text", "reference": "ref a"},
        {"sample_id": "b", "comment": "", "reference": "ref b"},
        {"sample_id": "zzz", "comment": "x", "reference": "y"},  # not in the dataset subset
    ]
    (tmp_path / "predictions.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows), encoding="utf-8"
    )
    items, no_comment = uf.items_from_run(tmp_path, {"a": DIFF, "b": DIFF})
    assert [(i.sample_id, i.source, i.comment) for i in items] == [
        ("a", "agent", "full text"), ("a", "human", "ref a"), ("b", "human", "ref b"),
    ]  # fmt: skip
    assert no_comment == 1


def test_human_kit_is_blinded_and_agreement_round_trips(tmp_path: Path) -> None:
    scored = _scored()
    kit = uf.export_human_kit(scored, tmp_path / "kit", size=10, seed=1)
    with kit["sheet"].open(encoding="utf-8-sig") as fh:
        sheet = list(csv.DictReader(fh))
    assert len(sheet) == 6 and set(sheet[0]) == {
        "item", "diff", "comment", "relevance", "informativeness", "notes",
    }  # fmt: skip
    assert "source" not in kit["sheet"].read_text(encoding="utf-8-sig")  # blinded
    with kit["key"].open(encoding="utf-8-sig") as fh:
        key = {r["item"]: r for r in csv.DictReader(fh)}

    def fill(path: Path, offset: int, blank_item: str | None = None) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(sheet[0]))
            w.writeheader()
            for row in sheet:
                k = key[row["item"]]
                if row["item"] == blank_item:
                    w.writerow(row)
                    continue
                rel = min(5, max(1, int(k["judge_relevance"]) + offset))
                w.writerow({**row, "relevance": rel, "informativeness": k["judge_informativeness"]})

    fill(tmp_path / "r1.csv", 0)
    fill(tmp_path / "r2.csv", 1, blank_item="1")
    m = uf.agreement_from_sheets(kit["key"], [tmp_path / "r1.csv", tmp_path / "r2.csv"])
    assert m["skipped_rows"] == [0, 1]
    j1 = m["judge_vs_human"][0]
    assert (
        j1["relevance"]["weighted_kappa"] == pytest.approx(1.0) and j1["relevance"]["exact"] == 1.0
    )
    assert m["judge_vs_human"][1]["relevance"]["n"] == 5
    assert m["human_vs_human"]["informativeness"]["exact"] == 1.0
    assert m["human_ratings_by_author"]["agent"]["informativeness"]["n"] == 3
    assert "Weighted kappa" in uf.agreement_summary_md(m)


def test_compose_full_comment() -> None:
    from marl_agents.core.schemas import Finding

    f = Finding(
        id="CR-1", file="a.py", start_line=1, end_line=1, category="bug", severity="high",
        title="Off by one", description="Skips the first item.\nRelated: x", recommendation="Start at 0.",
        confidence=0.8, sources=["llm"],  # type: ignore[list-item]
    )  # fmt: skip
    assert (
        compose_comment([f], "full") == "Off by one\nSkips the first item.\nSuggestion: Start at 0."
    )


# ---- hunk risk ----------------------------------------------------------------------------------

OLDF = "import os\n\n\ndef run(cmd):\n    return cmd\n"
PATCH = "@@ -3,3 +3,3 @@\n \n def run(cmd):\n-    return cmd\n+    return os.system(cmd)\n"


def test_risk_for_sample_runs_the_change_pipeline(settings: Settings) -> None:
    sample = CodeReviewerSample(
        sample_id="cls-test-1-1", task="cls", split="test", patch=PATCH, oldf=OLDF, label=1
    )
    settings.review.mode = "static_only"
    row = change_risk.risk_for_sample(make_agent(settings, None), sample)
    assert "error" not in row, row
    assert row["label"] == 1 and row["size"] == 2 and row["n_hunks"] == 1
    assert "sensitive_api" in row["signals"] and row["risk"] >= 15
    bad = sample.model_copy(update={"patch": "@@ -90,1 +90,1 @@\n-nope\n+yes\n"})
    assert change_risk.risk_for_sample(make_agent(settings, None), bad)["error"].startswith("patch")


def test_risk_metrics_hand_computed() -> None:
    rows = [
        {"label": 1, "risk": 60, "level": "high", "signals": ["findings_in_hunk"], "size": 3, "finding_score": 0.2},
        {"label": 1, "risk": 30, "level": "medium", "signals": [], "size": 40, "finding_score": 0.0},
        {"label": 0, "risk": 10, "level": "low", "signals": ["findings_in_hunk"], "size": 50, "finding_score": 0.6},
        {"label": 0, "risk": 0, "level": "low", "signals": [], "size": 1, "finding_score": 0.0},
    ]  # fmt: skip
    m = change_risk.risk_metrics(rows)
    assert m["base_rate"] == 0.5
    assert m["auc"]["hunk_risk"]["auc"] == 1.0  # both positives above both negatives
    assert m["auc"]["size_baseline"]["auc"] == 0.5  # (3>1, 40>1, 3<50, 40<50) -> 2/4
    assert m["precision_at_top"]["hunk_risk"]["25%"] == 1.0  # top 1 of 4 is a positive
    assert m["by_level"]["low"] == {"n": 2, "share": 0.5, "commented_rate": 0.0}
    sig = m["signals"]["findings_in_hunk"]
    assert (sig["n_fired"], sig["commented_rate_fired"], sig["commented_rate_not_fired"]) == (
        2,
        0.5,
        0.5,
    )
    assert "| hunk_risk | 1.000" in change_risk.hunk_risk_summary_md(
        {**m, "n_failed": 0, "failure_reasons": {}, "seconds": 1.0}, "t"
    )


def test_signals_of_reason_text() -> None:
    reasons = ["1 finding(s) in this hunk (worst: low)", "large hunk (60 changed lines)", "x"]
    assert change_risk.signals_of(reasons) == {"findings_in_hunk", "size_20plus"}


def test_full_comment_does_not_repeat_the_title() -> None:
    from marl_agents.core.schemas import Finding

    f = Finding(
        id="CR-1", file="a.py", start_line=1, end_line=1, category="quality", severity="low",
        title="F401: `os` imported but unused", description="`os` imported but unused",
        recommendation="Remove the import.", confidence=0.8, sources=["ruff"],  # type: ignore[list-item]
        rule_id="F401",
    )  # fmt: skip
    assert (
        compose_comment([f], "full") == "`os` imported but unused\nSuggestion: Remove the import."
    )


def test_risk_metrics_include_v1_and_random_baselines() -> None:
    rows = [
        {"label": 1, "risk": 60, "risk_v1": 10, "level": "high", "signals": [], "size": 3, "finding_score": 0.2},
        {"label": 0, "risk": 10, "risk_v1": 40, "level": "low", "signals": [], "size": 50, "finding_score": 0.6},
    ]  # fmt: skip
    m = change_risk.risk_metrics(rows)
    assert m["auc"]["risk_v1_baseline"]["auc"] == 0.0 and m["auc"]["hunk_risk"]["auc"] == 1.0
    # top 10% of 2 rows = 1 row: v1 ranks the negative first, v2 the positive
    assert m["precision_at_top"]["risk_v1_baseline"]["10%"] == 0.0
    assert m["precision_at_top"]["hunk_risk"]["10%"] == 1.0
    assert m["random_baseline"] == {"precision_at_top": 0.5, "auc": 0.5}

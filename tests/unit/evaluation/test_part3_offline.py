"""Part 3 work that needs no LLM: classifier metrics, funnel, reanalysis reports, BM25 baseline."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from marl_agents.evaluation.funnel import funnel, funnel_counts, funnel_report
from marl_agents.evaluation.metrics.classification import (
    always_positive,
    average_precision,
    balanced_accuracy,
    binary_metrics,
    brier_score,
    mcc,
    precision_at_fraction,
)
from marl_agents.evaluation.reanalysis import (
    classifier_md,
    classifier_report,
    static_baseline_md,
    static_baseline_report,
)
from marl_agents.evaluation.runners.code_review import bm25_ranker, code_tokens
from marl_agents.evaluation.runs import load_runs
from tests.unit.evaluation.test_comparison import CFG, llm_cfg, save

# ---- classifier metrics (hand-computed) --------------------------------------------------------------


def test_average_precision_by_hand() -> None:
    # thresholds 0.9 (P=1, R=.5), 0.8 (P=.5, R=.5), 0.7 (P=2/3, R=1), 0.1 (P=.5, R=1)
    assert average_precision([1, 0, 1, 0], [0.9, 0.8, 0.7, 0.1]) == pytest.approx(0.5 + 0.5 * 2 / 3)
    assert average_precision([1, 1], [0.5, 0.5]) == pytest.approx(1.0)
    assert average_precision([0, 0], [0.2, 0.1]) is None


def test_mcc_balanced_accuracy_brier_by_hand() -> None:
    m = binary_metrics([1, 1, 1, 0, 0, 0, 0, 1], [1, 1, 0, 0, 0, 1, 0, 1])  # tp3 fp1 tn3 fn1
    assert (m.tp, m.fp, m.tn, m.fn) == (3, 1, 3, 1)
    assert mcc(m) == pytest.approx((9 - 1) / math.sqrt(4 * 4 * 4 * 4))  # 0.5
    assert balanced_accuracy(m) == pytest.approx(0.75)
    assert mcc(binary_metrics([1, 1], [1, 1])) is None  # an empty column
    assert brier_score([1, 0], [0.8, 0.4]) == pytest.approx((0.04 + 0.16) / 2)


def test_precision_at_top_fraction_and_always_positive() -> None:
    y = [1, 0, 1, 1, 0, 0, 0, 0, 0, 1]
    s = [0.9, 0.95, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    assert precision_at_fraction(y, s, 0.2) == (0.5, 2)  # top 2 by score: 0.95 (neg), 0.9 (pos)
    assert precision_at_fraction([1, 0, 0], [0.9, 0.1, 0.2], 0.10) == (1.0, 1)  # ceil(0.3) = 1
    ap = always_positive([1, 0, 1, 1])
    assert ap["precision"] == ap["accuracy"] == 0.75 and ap["recall"] == 1.0
    assert ap["f1"] == pytest.approx(2 * 0.75 / 1.75)


# ---- funnel ---------------------------------------------------------------------------------------


STATS = {
    "llm_items_schema_invalid": 2,
    "llm_findings_raw": 10,
    "llm_findings_valid": 6,
    "llm_findings_actionable": 5,
    "llm_findings_after_dedupe": 4,
    "llm_rejected_by_reason": {"evidence_not_found": 2, "line_out_of_range": 1, "outside_scope": 1},
}


def test_funnel_stages_and_hallucination_rate() -> None:
    f = funnel(STATS)
    assert f is not None
    assert (f.produced, f.passed_schema, f.quote_verified, f.actionable, f.after_dedupe) == (
        12, 10, 7, 5, 4,
    )  # fmt: skip
    assert f.quote_failed == 3 and f.other_rejected == 1
    assert f.hallucination_rate == pytest.approx(0.3)


def test_funnel_old_runs_show_unknown_stages_as_none() -> None:
    f = funnel({"llm_findings_raw": 4, "llm_findings_valid": 4, "vague_dropped": 1})
    assert f is not None and f.produced is None and f.after_dedupe is None and f.actionable == 3
    assert funnel({"mode": "static_only"}) is None


def test_funnel_counts_sum_samples() -> None:
    total = funnel_counts([STATS, {**STATS, "llm_items_schema_invalid": None}])
    assert total["llm_findings_raw"] == 20 and total["llm_items_schema_invalid"] == 2
    assert total["llm_rejected_by_reason"]["evidence_not_found"] == 4


def test_funnel_report_has_one_table_per_model(tmp_path: Path) -> None:
    for i, (model, letter) in enumerate((("m1", "C"), ("m2", "D"))):
        cfg = {**llm_cfg(letter), "llm": {"provider": "groq", "model": model, "temperature": 0.0}}
        save(tmp_path, f"2026010{i + 1}T000000Z_planted_x", {"pipeline": STATS, "detection": {}},
             meta={"llm_provider": "groq", "llm_model": model}, config=cfg)  # fmt: skip
    md, rows = funnel_report(load_runs(tmp_path))
    assert "## groq / m1" in md and "## groq / m2" in md and len(rows) == 2
    assert "0.300" in md


def test_agent_records_the_new_funnel_counters(settings, make_repo) -> None:  # type: ignore[no-untyped-def]
    from marl_agents.agents.code_review import CodeReviewAgent
    from marl_agents.core.schemas import AgentRequest
    from marl_agents.llm import MockLLMProvider

    reply = json.dumps({"findings": [
        {"file": "app/db.py", "start_line": 2, "category": "bug", "severity": "high",
         "title": "Unchecked query", "evidence": ["return conn.execute(name)"],
         "recommendation": "validate name before executing the query"},
        {"start_line": 0, "category": "bug", "severity": "high", "title": "bad line"},
    ], "static_assessments": []})  # fmt: skip
    settings.review.mode = "llm_only"
    repo = make_repo({"app/db.py": "def query(conn, name):\n    return conn.execute(name)\n"})
    agent = CodeReviewAgent(MockLLMProvider(responder=lambda m: reply), settings=settings)
    stats = agent.run(AgentRequest(repo_path=str(repo.root))).stats
    assert stats["llm_items_schema_invalid"] == 1  # start_line 0 fails the schema
    assert stats["llm_findings_raw"] == 1
    assert "llm_findings_actionable" in stats and "llm_findings_after_dedupe" in stats


# ---- reanalysis of saved runs ------------------------------------------------------------------------


def test_classifier_report_uses_the_saved_threshold(tmp_path: Path) -> None:
    preds = [
        {"sample_id": f"s{i}", "label": y, "score": s, "repo_disjoint": True, "official_test": True}
        for i, (y, s) in enumerate([(1, 0.9), (0, 0.8), (1, 0.7), (0, 0.1)])
    ]
    save(tmp_path, "20260101T000000Z_classifier_cls_test_n4", {"threshold": 0.75},
         meta={}, config=CFG["A"], predictions=preds)  # fmt: skip
    r = classifier_report(load_runs(tmp_path)[0])
    b = r["repo_disjoint"]
    assert r["threshold"] == 0.75 and b["confusion"] == {"tp": 1, "fp": 1, "tn": 1, "fn": 1}
    assert b["pr_auc"] == pytest.approx(0.5 + 0.5 * 2 / 3) and b["pr_auc_chance"] == 0.5
    assert b["mcc"] == 0.0 and b["balanced_accuracy"] == 0.5
    assert "PR-AUC (average precision)" in classifier_md(r)


def test_static_baseline_report_with_and_without_single_hunk_rules(tmp_path: Path) -> None:
    f401 = {"severity": "low", "confidence": 0.9, "rule": "F401"}
    hi = {"severity": "high", "confidence": 0.9, "rule": "S101"}
    preds: list[dict[str, Any]] = [
        {"sample_id": "a", "label": 1, "findings": [hi]},
        {"sample_id": "b", "label": 0, "findings": [f401]},
        {"sample_id": "c", "label": 0, "findings": []},
    ]
    save(tmp_path, "20260101T000000Z_codereviewer_cls_test_static_only_n3",
         {"task": "cls", "n_evaluated": 3}, meta={"split": "test"}, config=CFG["A"],
         predictions=preds)  # fmt: skip
    r = static_baseline_report(load_runs(tmp_path)[0])
    assert r["all_rules"]["confusion"]["fp"] == 1
    assert r["without_single_hunk_rules"]["confusion"]["fp"] == 0
    assert r["all_rules"]["majority_baseline_accuracy"] == pytest.approx(2 / 3)
    assert "Balanced accuracy" in static_baseline_md(r)


# ---- BM25 baseline ------------------------------------------------------------------------------------


def test_code_tokens_split_identifiers() -> None:
    assert code_tokens("loadUserConfig(user_id)") == [
        "load", "user", "config", "loaduserconfig", "user", "id", "user_id",
    ]  # fmt: skip


def test_bm25_ranks_the_lexically_closest_chunk_first() -> None:
    pytest.importorskip("rank_bm25")
    from marl_agents.rag.chunking import Chunk

    def chunk(cid: str, text: str) -> Chunk:
        return Chunk(id=cid, repo_id="r", file="a.py", symbol=cid, kind="function",
                     start_line=1, end_line=2, language="python", source_type="code",
                     text=text)  # fmt: skip

    chunks = [
        chunk("q", "def handler(): return parse_config(path)"),
        chunk("cfg", "def parse_config(path): return read_yaml(path)"),
        chunk("db", "def open_database(url): return connect(url)"),
        chunk("log", "def write_log(msg): print(msg)"),
        # filler, so the shared words are common and parse_config is rare (BM25 needs an IDF)
        *[chunk(f"f{i}", f"def helper_{i}(a, b): return a + b + {i}") for i in range(8)],
    ]
    rank = bm25_ranker(chunks)
    assert rank is not None
    ranked = rank(chunks[0])
    assert ranked[0] == "cfg" and "q" not in ranked


# ---- 3.8 saved-score ranker comparison ----------------------------------------------------------------


def test_saved_score_ranker_comparison_reads_only_saved_runs(tmp_path: Path) -> None:
    from marl_agents.evaluation.saved_score_ranking import compare_md, compare_saved_rankers

    labels = [1, 0, 1, 0, 1, 0]
    hunk = [{"sample_id": f"s{i}", "label": y, "risk": float(i), "size": float(6 - i)}
            for i, y in enumerate(labels)]  # fmt: skip
    cls = [{"sample_id": f"s{i}", "label": y, "score": 0.9 if y else 0.1,
            "repo_disjoint": i != 5} for i, y in enumerate(labels)]  # fmt: skip
    cls.append({"sample_id": "only-cls", "label": 1, "score": 0.5, "repo_disjoint": True})
    save(tmp_path, "20260101T000000Z_hunkrisk_cls_test_n6", {"n_evaluated": 6}, meta={},
         config=CFG["A"], predictions=hunk)  # fmt: skip
    save(tmp_path, "20260102T000000Z_classifier_cls_test_n7", {"threshold": 0.5}, meta={},
         config=CFG["A"], predictions=cls)  # fmt: skip
    runs = {r.name: r for r in load_runs(tmp_path)}
    r = compare_saved_rankers(runs["20260101T000000Z_hunkrisk_cls_test_n6"],
                              runs["20260102T000000Z_classifier_cls_test_n7"])  # fmt: skip
    assert r["n"] == 5 and r["scored_by_both"] == 5  # s5 is not repo-disjoint; only-cls unmatched
    assert r["rankers"]["classifier_saved_score"]["auc"] == 1.0
    assert r["default_ranker"] == "risk_v2 (unchanged)"
    assert "secondary analysis" in compare_md(r)


def test_snapshot_paths_too_long_for_windows_are_detected(tmp_path: Path) -> None:
    from marl_agents.evaluation.datasets.bugsinpy_repo import MAX_PATH_CHARS, fits_windows_path

    assert fits_windows_path(tmp_path / "pkg" / "module.py")
    deep = tmp_path.joinpath(*(["placebo_recordings_directory"] * 12), "recording.json")
    assert len(str(deep.resolve())) > MAX_PATH_CHARS and not fits_windows_path(deep)

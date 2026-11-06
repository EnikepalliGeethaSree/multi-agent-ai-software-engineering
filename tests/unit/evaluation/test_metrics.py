import math

import pytest

from marl_agents.core.schemas import Finding
from marl_agents.evaluation.metrics import (
    ExpectedIssue,
    binary_metrics,
    bootstrap_ci,
    chrf,
    corpus_bleu_avg,
    detection_metrics,
    hit_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    roc_auc,
    rouge_l,
    sentence_bleu,
    tokenize,
)

# ---- text metrics (hand-computed) ----------------------------------------------------------------


def test_tokenize() -> None:
    assert tokenize("Use `is None`, please!") == ["use", "`", "is", "none", "`", ",", "please", "!"]


def test_bleu_identical_and_disjoint() -> None:
    assert sentence_bleu("the cat sat on the mat", "the cat sat on the mat") == pytest.approx(1.0)
    assert sentence_bleu("the cat", "dog runs") == 0.0
    assert sentence_bleu("", "x") == 0.0 and sentence_bleu("x", "") == 0.0


def test_bleu_smoothing_hand_computed() -> None:
    # p1 = 3/4, p2 = (1+1)/(3+1), p3 = (0+1)/(2+1), p4 = (0+1)/(1+1); BP = 1
    # BLEU = (0.75 * 0.5 * 1/3 * 0.5) ** (1/4) = 0.0625 ** 0.25 = 0.5
    assert sentence_bleu("a b x d", "a b c d") == pytest.approx(0.5)


def test_bleu_brevity_penalty_hand_computed() -> None:
    # hyp "the cat" vs ref "the cat sat": all smoothed precisions = 1, BP = exp(1 - 3/2)
    assert sentence_bleu("the cat sat", "the cat") == pytest.approx(math.exp(-0.5))


def test_corpus_bleu_is_mean_times_100() -> None:
    assert corpus_bleu_avg(["a b x d", "q"], ["a b c d", "q"]) == pytest.approx(
        100 * (0.5 + 1.0) / 2
    )


def test_rouge_l_hand_computed() -> None:
    # LCS("a b c d", "a c d e") = "a c d" = 3, P = R = 3/4
    assert rouge_l("a b c d", "a c d e") == pytest.approx(0.75)
    assert rouge_l("a b", "c d") == 0.0


def test_chrf_bounds() -> None:
    assert chrf("hello world", "hello world") == pytest.approx(1.0)
    assert chrf("abc", "xyz") == 0.0
    assert 0 < chrf("remove unused import", "unused import") < 1


# ---- classification ----------------------------------------------------------------------------


def test_binary_metrics_hand_computed() -> None:
    m = binary_metrics([1, 1, 0, 0, 1], [1, 0, 1, 0, 1])
    assert (m.tp, m.fp, m.tn, m.fn) == (2, 1, 1, 1)
    assert m.precision == pytest.approx(2 / 3) and m.recall == pytest.approx(2 / 3)
    assert m.f1 == pytest.approx(2 / 3) and m.accuracy == pytest.approx(0.6)
    empty = binary_metrics([0, 0], [0, 0])
    assert empty.precision == 0.0 and empty.f1 == 0.0 and empty.accuracy == 1.0
    with pytest.raises(ValueError):
        binary_metrics([1], [1, 0])


def test_roc_auc_hand_computed_and_ties() -> None:
    assert roc_auc([0, 0, 1, 1], [0.1, 0.4, 0.35, 0.8]) == pytest.approx(0.75)
    assert roc_auc([0, 1], [0.5, 0.5]) == pytest.approx(0.5)
    assert roc_auc([0, 1, 1], [0.0, 1.0, 1.0]) == pytest.approx(1.0)
    assert roc_auc([1, 1], [0.2, 0.3]) is None


def test_bootstrap_ci_is_deterministic_and_brackets_mean() -> None:
    values = [0.0, 1.0] * 50
    lo, hi = bootstrap_ci(values, lambda s: sum(s) / len(s))
    assert lo < 0.5 < hi and (lo, hi) == bootstrap_ci(values, lambda s: sum(s) / len(s))


# ---- retrieval -----------------------------------------------------------------------------------


def test_retrieval_metrics_hand_computed() -> None:
    ranked, rel = ["a", "b", "c", "d"], {"b", "d"}
    assert recall_at_k(ranked, rel, 1) == 0.0 and recall_at_k(ranked, rel, 2) == 0.5
    assert recall_at_k(ranked, rel, 4) == 1.0
    assert precision_at_k(ranked, rel, 2) == 0.5 and hit_at_k(ranked, rel, 2) == 1.0
    assert reciprocal_rank(ranked, rel) == 0.5
    # DCG = 1/log2(3) + 1/log2(5); IDCG = 1 + 1/log2(3)
    expected = (1 / math.log2(3) + 1 / math.log2(5)) / (1 + 1 / math.log2(3))
    assert ndcg_at_k(ranked, rel, 4) == pytest.approx(expected)
    assert reciprocal_rank(ranked, {"z"}) == 0.0 and ndcg_at_k(ranked, set(), 3) == 0.0


# ---- detection (planted benchmark) ---------------------------------------------------------------


def _f(file: str, line: int, category: str, title: str = "t") -> Finding:
    return Finding(
        id="X",
        file=file,
        start_line=line,
        end_line=line,
        category=category,  # type: ignore[arg-type]
        severity="medium",
        title=title,
        description="d",
        confidence=0.5,  # type: ignore[arg-type]
    )


def test_detection_metrics() -> None:
    expected = [
        ExpectedIssue(id="E1", file="a.py", line=10, category="security", detectable_by="static"),  # type: ignore[arg-type]
        ExpectedIssue(id="E2", file="a.py", line=30, category="bug", detectable_by="llm"),  # type: ignore[arg-type]
    ]
    findings = [
        _f("a.py", 11, "security"),  # matches E1 within tolerance
        _f("a.py", 10, "security"),  # second finding on the same issue: still a true positive
        _f("clean.py", 3, "bug", "fp"),  # false positive in the negative-control file
        _f("a.py", 30, "documentation"),  # right place, incompatible category: no match
    ]
    m = detection_metrics(findings, expected, negative_files=["clean.py"])
    assert m.matched == 1 and m.recall == 0.5 and m.recall_static == 1.0 and m.recall_llm == 0.0
    assert m.defect_findings == 3 and m.defect_true_positives == 2
    assert m.defect_precision == pytest.approx(2 / 3)
    assert m.negative_file_false_positives == 1 and m.false_positive_titles == ["fp"]
    assert m.mean_line_error == 0.0 and m.missed == ["E2"]

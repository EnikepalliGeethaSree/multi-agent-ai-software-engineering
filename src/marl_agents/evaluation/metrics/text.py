"""Text-generation metrics for review comments: smoothed BLEU-4, ROUGE-L, chrF.

BLEU follows the smoothed sentence-level BLEU-4 used by the CodeReviewer / CodeXGLUE evaluation
scripts (Lin & Och 2004 "+1" smoothing for n >= 2, averaged over sentences, reported x100).
Our tokenizer is a simple lowercase word/punctuation split, so numbers are close to but not
guaranteed identical with the official script.
"""

from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN = re.compile(r"\w+|[^\w\s]")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _ngrams(tokens: list[str], n: int) -> Counter[tuple[str, ...]]:
    return Counter(tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1))


def sentence_bleu(reference: str, hypothesis: str, max_n: int = 4) -> float:
    """Smoothed sentence BLEU in [0, 1]."""
    ref, hyp = tokenize(reference), tokenize(hypothesis)
    if not hyp or not ref:
        return 0.0
    log_precision = 0.0
    for n in range(1, max_n + 1):
        hyp_ngrams = _ngrams(hyp, n)
        ref_ngrams = _ngrams(ref, n)
        matches = sum(min(c, ref_ngrams[g]) for g, c in hyp_ngrams.items())
        total = max(len(hyp) - n + 1, 0)
        if n == 1:
            if matches == 0:
                return 0.0
            p = matches / total
        else:
            p = (matches + 1) / (total + 1)
        log_precision += math.log(p) / max_n
    bp = 1.0 if len(hyp) > len(ref) else math.exp(1 - len(ref) / len(hyp))
    return bp * math.exp(log_precision)


def corpus_bleu_avg(references: list[str], hypotheses: list[str]) -> float:
    """Mean smoothed sentence BLEU-4 x100 (the CodeReviewer reporting convention)."""
    if not references:
        return 0.0
    return (
        100.0
        * sum(sentence_bleu(r, h) for r, h in zip(references, hypotheses, strict=True))
        / len(references)
    )


def _lcs(a: list[str], b: list[str]) -> int:
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b, start=1):
            cur.append(prev[j - 1] + 1 if x == y else max(prev[j], cur[j - 1]))
        prev = cur
    return prev[-1]


def rouge_l(reference: str, hypothesis: str) -> float:
    """ROUGE-L F1 (beta = 1) in [0, 1]."""
    ref, hyp = tokenize(reference), tokenize(hypothesis)
    lcs = _lcs(ref, hyp)
    if lcs == 0:
        return 0.0
    p, r = lcs / len(hyp), lcs / len(ref)
    return 2 * p * r / (p + r)


def chrf(reference: str, hypothesis: str, max_n: int = 6, beta: float = 2.0) -> float:
    """Character n-gram F-score (Popovic 2015), whitespace removed, in [0, 1]."""
    ref = re.sub(r"\s+", "", reference.lower())
    hyp = re.sub(r"\s+", "", hypothesis.lower())
    if not ref or not hyp:
        return 0.0
    precisions, recalls = [], []
    for n in range(1, max_n + 1):
        r_ngr = Counter(ref[i : i + n] for i in range(len(ref) - n + 1))
        h_ngr = Counter(hyp[i : i + n] for i in range(len(hyp) - n + 1))
        if not r_ngr or not h_ngr:
            continue
        match = sum(min(c, r_ngr[g]) for g, c in h_ngr.items())
        precisions.append(match / sum(h_ngr.values()))
        recalls.append(match / sum(r_ngr.values()))
    if not precisions:
        return 0.0
    p, r = sum(precisions) / len(precisions), sum(recalls) / len(recalls)
    if p == 0 and r == 0:
        return 0.0
    b2 = beta * beta
    return (1 + b2) * p * r / (b2 * p + r)

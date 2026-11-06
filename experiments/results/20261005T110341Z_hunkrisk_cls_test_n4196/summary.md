# Hunk-risk ranking vs. human review comments (CodeReviewer cls test, Python, n=4196, seed=42)

n = 4195 evaluated (1 failed: {'patch': 1}); share of hunks that received a human comment (base rate) = 0.485; runtime 431.9 s.

| Score | ROC-AUC (95% CI) | Precision top 5% | top 10% | top 25% |
|---|---:|---:|---:|---:|
| hunk_risk | 0.434 (0.418-0.452) | 0.373 | 0.365 | 0.357 |
| size_baseline | 0.624 (0.607-0.641) | 0.344 | 0.530 | 0.635 |
| finding_score_baseline | 0.407 (0.392-0.424) | 0.325 | 0.279 | 0.327 |

Risk level of the top hunk vs. how often humans commented:

| Level | Samples | Share | Commented rate |
|---|---:|---:|---:|
| high | 354 | 0.084 | 0.359 |
| medium | 445 | 0.106 | 0.364 |
| low | 3396 | 0.809 | 0.513 |

Individual signals (commented rate when the signal fires vs. when it does not):

| Signal | Fired | Rate if fired | Rate if not |
|---|---:|---:|---:|
| breaks_callers | 0 | n/a | 0.485 |
| error_handling | 379 | 0.662 | 0.467 |
| findings_in_hunk | 1563 | 0.399 | 0.536 |
| has_dependents | 1131 | 0.375 | 0.525 |
| removes_function | 110 | 0.382 | 0.487 |
| sensitive_api | 219 | 0.676 | 0.474 |
| signature_change | 218 | 0.532 | 0.482 |
| size_20plus | 780 | 0.637 | 0.450 |
| untested | 0 | n/a | 0.485 |

Each sample is one file, so cross-file signals (breaks_callers, has_dependents) rarely fire here; they are exercised by the git-based change tests instead.

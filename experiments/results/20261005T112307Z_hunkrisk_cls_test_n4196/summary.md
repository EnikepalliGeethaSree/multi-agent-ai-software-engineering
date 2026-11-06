# Hunk-risk ranking vs. human review comments (CodeReviewer cls test, Python, n=4196, seed=42)

n = 4195 evaluated (1 failed: {'patch': 1}); share of hunks that received a human comment (base rate) = 0.485; runtime 405.5 s.

| Score | ROC-AUC (95% CI) | Precision top 5% | top 10% | top 25% |
|---|---:|---:|---:|---:|
| hunk_risk | 0.624 (0.608-0.641) | 0.612 | 0.671 | 0.604 |
| hunk_risk_adjusted | 0.624 (0.608-0.641) | 0.612 | 0.671 | 0.604 |
| size_baseline | 0.624 (0.607-0.641) | 0.344 | 0.530 | 0.635 |
| finding_score_baseline | 0.407 (0.392-0.424) | 0.325 | 0.279 | 0.327 |

`hunk_risk_adjusted` ignores findings of the cross-hunk rules (F401, F403, F405, F811, F821): one hunk applied to the old file lacks the
imports/definitions added by the commit's other hunks, so they misfire on this benchmark
(but not on real changes, where the whole new version is available).

Risk level of the top hunk vs. how often humans commented (as shipped):

| Level | Samples | Share | Commented rate |
|---|---:|---:|---:|
| high | 438 | 0.104 | 0.678 |
| medium | 1352 | 0.322 | 0.457 |
| low | 2405 | 0.573 | 0.465 |

Individual signals, as shipped (commented rate when the signal fires vs. not):

| Signal | Fired | Rate if fired | Rate if not |
|---|---:|---:|---:|
| breaks_callers | 0 | n/a | 0.485 |
| error_handling | 379 | 0.662 | 0.467 |
| findings_in_hunk | 1791 | 0.422 | 0.532 |
| has_dependents | 1131 | 0.375 | 0.525 |
| removes_function | 110 | 0.382 | 0.487 |
| sensitive_api | 219 | 0.676 | 0.474 |
| signature_change | 218 | 0.532 | 0.482 |
| size_20plus | 780 | 0.637 | 0.450 |
| untested | 0 | n/a | 0.485 |

Risk level of the top hunk vs. how often humans commented (adjusted):

| Level | Samples | Share | Commented rate |
|---|---:|---:|---:|
| high | 438 | 0.104 | 0.678 |
| medium | 1038 | 0.247 | 0.585 |
| low | 2719 | 0.648 | 0.415 |

Individual signals, adjusted (commented rate when the signal fires vs. not):

| Signal | Fired | Rate if fired | Rate if not |
|---|---:|---:|---:|
| breaks_callers | 0 | n/a | 0.485 |
| error_handling | 379 | 0.662 | 0.467 |
| findings_in_hunk | 1106 | 0.536 | 0.466 |
| has_dependents | 1131 | 0.375 | 0.525 |
| removes_function | 110 | 0.382 | 0.487 |
| sensitive_api | 219 | 0.676 | 0.474 |
| signature_change | 218 | 0.532 | 0.482 |
| size_20plus | 780 | 0.637 | 0.450 |
| untested | 0 | n/a | 0.485 |

Each sample is one file, so cross-file signals (breaks_callers) cannot fire here; they are exercised by the git-based change tests instead.

# Hunk-risk ranking vs. human review comments (CodeReviewer cls valid, Python, n=4220, seed=42)

n = 4219 evaluated (1 failed: {'patch': 1}); share of hunks that received a human comment (base rate) = 0.487; runtime 426.2 s.

| Score | ROC-AUC (95% CI) | Precision top 5% | top 10% | top 25% |
|---|---:|---:|---:|---:|
| hunk_risk | 0.453 (0.436-0.470) | 0.343 | 0.354 | 0.376 |
| hunk_risk_adjusted | 0.527 (0.510-0.545) | 0.376 | 0.489 | 0.479 |
| size_baseline | 0.616 (0.600-0.631) | 0.329 | 0.544 | 0.640 |
| finding_score_baseline | 0.417 (0.401-0.432) | 0.405 | 0.297 | 0.326 |

`hunk_risk_adjusted` ignores findings of the cross-hunk rules (F401, F403, F405, F811, F821): one hunk applied to the old file lacks the
imports/definitions added by the commit's other hunks, so they misfire on this benchmark
(but not on real changes, where the whole new version is available).

Risk level of the top hunk vs. how often humans commented (as shipped):

| Level | Samples | Share | Commented rate |
|---|---:|---:|---:|
| high | 317 | 0.075 | 0.372 |
| medium | 447 | 0.106 | 0.360 |
| low | 3455 | 0.819 | 0.513 |

Individual signals, as shipped (commented rate when the signal fires vs. not):

| Signal | Fired | Rate if fired | Rate if not |
|---|---:|---:|---:|
| breaks_callers | 0 | n/a | 0.487 |
| error_handling | 369 | 0.669 | 0.469 |
| findings_in_hunk | 1584 | 0.402 | 0.538 |
| has_dependents | 1070 | 0.394 | 0.518 |
| removes_function | 136 | 0.338 | 0.492 |
| sensitive_api | 222 | 0.626 | 0.479 |
| signature_change | 200 | 0.530 | 0.484 |
| size_20plus | 795 | 0.653 | 0.448 |
| untested | 0 | n/a | 0.487 |

Risk level of the top hunk vs. how often humans commented (adjusted):

| Level | Samples | Share | Commented rate |
|---|---:|---:|---:|
| high | 222 | 0.053 | 0.383 |
| medium | 264 | 0.063 | 0.587 |
| low | 3733 | 0.885 | 0.486 |

Individual signals, adjusted (commented rate when the signal fires vs. not):

| Signal | Fired | Rate if fired | Rate if not |
|---|---:|---:|---:|
| breaks_callers | 0 | n/a | 0.487 |
| error_handling | 369 | 0.669 | 0.469 |
| findings_in_hunk | 857 | 0.536 | 0.474 |
| has_dependents | 1070 | 0.394 | 0.518 |
| removes_function | 136 | 0.338 | 0.492 |
| sensitive_api | 222 | 0.626 | 0.479 |
| signature_change | 200 | 0.530 | 0.484 |
| size_20plus | 795 | 0.653 | 0.448 |
| untested | 0 | n/a | 0.487 |

Each sample is one file, so cross-file signals (breaks_callers) cannot fire here; they are exercised by the git-based change tests instead.

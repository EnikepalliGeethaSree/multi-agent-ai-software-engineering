# Hunk-risk ranking vs. human review comments (CodeReviewer cls test, Python, n=4196, seed=42)

n = 4194 evaluated (2 failed: {'ChangeError': 1, 'patch': 1}); share of hunks that received a human comment (base rate) = 0.484; runtime 333.4 s.

| Score | ROC-AUC (95% CI) | Precision top 5% | top 10% | top 25% |
|---|---:|---:|---:|---:|
| hunk_risk | 0.644 (0.627-0.662) | 0.761 | 0.733 | 0.662 |
| hunk_risk_adjusted | 0.644 (0.627-0.662) | 0.761 | 0.733 | 0.662 |
| size_baseline | 0.651 (0.634-0.669) | 0.823 | 0.792 | 0.677 |
| finding_score_baseline | 0.407 (0.392-0.423) | 0.282 | 0.224 | 0.321 |
| risk_v1_baseline | 0.431 (0.415-0.449) | 0.230 | 0.305 | 0.353 |

`hunk_risk_adjusted` ignores findings of the cross-hunk rules (F401, F403, F405, F811, F821): one hunk applied to the old file lacks the
imports/definitions added by the commit's other hunks, so they misfire on this benchmark
(but not on real changes, where the whole new version is available).

Risk level of the top hunk vs. how often humans commented (as shipped):

| Level | Samples | Share | Commented rate |
|---|---:|---:|---:|
| high | 347 | 0.083 | 0.738 |
| medium | 1219 | 0.291 | 0.460 |
| low | 2628 | 0.627 | 0.462 |

Individual signals, as shipped (commented rate when the signal fires vs. not):

| Signal | Fired | Rate if fired | Rate if not |
|---|---:|---:|---:|
| breaks_callers | 0 | n/a | 0.484 |
| error_handling | 294 | 0.721 | 0.467 |
| findings_in_hunk | 1634 | 0.415 | 0.529 |
| has_dependents | 1163 | 0.369 | 0.529 |
| removes_function | 110 | 0.382 | 0.487 |
| sensitive_api | 204 | 0.686 | 0.474 |
| signature_change | 218 | 0.532 | 0.482 |
| size_20plus | 464 | 0.780 | 0.448 |
| untested | 0 | n/a | 0.484 |

Risk level of the top hunk vs. how often humans commented (adjusted):

| Level | Samples | Share | Commented rate |
|---|---:|---:|---:|
| high | 347 | 0.083 | 0.738 |
| medium | 871 | 0.208 | 0.625 |
| low | 2976 | 0.710 | 0.414 |

Individual signals, adjusted (commented rate when the signal fires vs. not):

| Signal | Fired | Rate if fired | Rate if not |
|---|---:|---:|---:|
| breaks_callers | 0 | n/a | 0.484 |
| error_handling | 294 | 0.721 | 0.467 |
| findings_in_hunk | 870 | 0.577 | 0.460 |
| has_dependents | 1163 | 0.369 | 0.529 |
| removes_function | 110 | 0.382 | 0.487 |
| sensitive_api | 204 | 0.686 | 0.474 |
| signature_change | 218 | 0.532 | 0.482 |
| size_20plus | 464 | 0.780 | 0.448 |
| untested | 0 | n/a | 0.484 |

Each sample is one file, so cross-file signals (breaks_callers) cannot fire here; they are exercised by the git-based change tests instead.

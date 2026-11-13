# CodeReviewer msg (test, Python, n=40, seed=42, Static Only)

n = 40 evaluated (0 failed: {}). Runtime 5.3 s.

## All rules

Comment coverage (a comment was produced): 0.425

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 0.77 | 2.31 | 5.18 |
| title_fix | 1.78 | 4.90 | 7.86 |
| description | 0.96 | 2.91 | 5.48 |

- BLEU-4 (title_fix) 95% CI: 0.99-2.55

## Sensitivity: without cross-hunk rules F401, F403, F405, F811, F821

Comment coverage (a comment was produced): 0.225

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 0.45 | 1.05 | 2.56 |
| title_fix | 0.83 | 1.86 | 3.74 |
| description | 0.65 | 1.66 | 2.86 |

- BLEU-4 (title_fix) 95% CI: 0.28-1.52

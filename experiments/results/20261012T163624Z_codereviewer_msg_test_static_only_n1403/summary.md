# CodeReviewer msg (test, Python, n=1403, seed=42, Static Only)

n = 1403 evaluated (0 failed: {}). Runtime 72.0 s.

## All rules

Comment coverage (a comment was produced): 0.281

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 0.73 | 1.95 | 3.62 |
| title_fix | 1.18 | 3.03 | 4.83 |
| description | 0.92 | 2.43 | 3.84 |

- BLEU-4 (title_fix) 95% CI: 1.05-1.30

## Sensitivity: without cross-hunk rules F401, F403, F405, F811, F821

Comment coverage (a comment was produced): 0.182

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 0.41 | 1.04 | 2.37 |
| title_fix | 0.74 | 1.82 | 2.99 |
| description | 0.61 | 1.57 | 2.60 |

- BLEU-4 (title_fix) 95% CI: 0.65-0.84

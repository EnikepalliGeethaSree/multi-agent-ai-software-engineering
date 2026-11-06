# CodeReviewer msg (test, Python, n=40, seed=42, full)

n = 36 evaluated (4 failed: {'llm': 4}). Runtime 2623.0 s.

## All rules

Comment coverage (a comment was produced): 0.778

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 1.66 | 3.35 | 9.55 |
| title_fix | 2.14 | 6.91 | 13.60 |
| description | 1.77 | 5.31 | 12.38 |

- BLEU-4 (title_fix) 95% CI: 1.53-2.75

## Sensitivity: without cross-hunk rules F401, F403, F405, F811, F821

Comment coverage (a comment was produced): 0.667

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 1.41 | 2.31 | 7.83 |
| title_fix | 1.93 | 5.92 | 11.71 |
| description | 1.61 | 4.86 | 11.43 |

- BLEU-4 (title_fix) 95% CI: 1.18-2.81

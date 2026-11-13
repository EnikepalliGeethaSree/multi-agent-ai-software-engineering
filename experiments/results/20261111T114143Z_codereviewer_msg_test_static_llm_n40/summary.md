# CodeReviewer msg (test, Python, n=40, seed=42, Static + LLM)

n = 40 evaluated (0 failed: {}). Runtime 227.4 s.

## All rules

Comment coverage (a comment was produced): 0.700

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 1.02 | 1.71 | 8.25 |
| title_fix | 1.71 | 5.22 | 12.73 |
| description | 1.96 | 6.27 | 12.96 |

- BLEU-4 (title_fix) 95% CI: 1.22-2.21

## Sensitivity: without cross-hunk rules F401, F403, F405, F811, F821

Comment coverage (a comment was produced): 0.525

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 0.71 | 1.37 | 6.49 |
| title_fix | 1.09 | 3.12 | 9.22 |
| description | 1.45 | 4.27 | 9.70 |

- BLEU-4 (title_fix) 95% CI: 0.70-1.54
